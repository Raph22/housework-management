"""Sensor platform for the Housework integration."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HouseworkCoordinator, SUBENTRY_TYPE_TASK
from .entity import hub_device_info, task_device_info
from .models import Task


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Housework sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator

    # Global hub sensors
    async_add_entities([
        HouseworkDueTodaySensor(coordinator),
        HouseworkOverdueSensor(coordinator),
    ])

    # Per-task next_due sensors
    known_task_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if not coordinator.data:
            return
        for task_id, task in coordinator.data.items():
            if task_id not in known_task_ids:
                known_task_ids.add(task_id)
                async_add_entities(
                    [HouseworkNextDueSensor(coordinator, task)],
                    config_subentry_id=task_id,
                )

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_TASK:
            continue
        task_id = subentry.subentry_id
        if coordinator.data and task_id in coordinator.data:
            known_task_ids.add(task_id)
            async_add_entities(
                [HouseworkNextDueSensor(coordinator, coordinator.data[task_id])],
                config_subentry_id=task_id,
            )

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


# --- Per-task sensor ---


class HouseworkNextDueSensor(CoordinatorEntity[HouseworkCoordinator], SensorEntity):
    """Sensor showing the next due date for a task."""

    _attr_has_entity_name = True
    _attr_translation_key = "next_due"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: HouseworkCoordinator, task: Task) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, context=task.id)
        self._task_id = task.id
        self._attr_unique_id = f"housework_{task.id}_next_due"
        self._attr_device_info = task_device_info(task)

    @property
    def _task(self) -> Task | None:
        if self.coordinator.data:
            return self.coordinator.data.get(self._task_id)
        return None

    @property
    def available(self) -> bool:
        return super().available and self._task is not None

    @property
    def native_value(self) -> date | None:
        task = self._task
        if task is None or task.next_due is None:
            return None
        try:
            return date.fromisoformat(task.next_due)
        except (ValueError, TypeError):
            return None


# --- Global hub sensors ---


class HouseworkDueTodaySensor(CoordinatorEntity[HouseworkCoordinator], SensorEntity):
    """Sensor showing count of tasks due today (not overdue)."""

    _attr_has_entity_name = True
    _attr_translation_key = "tasks_due_today"
    _attr_icon = "mdi:calendar-today"
    _attr_native_unit_of_measurement = "tasks"

    def __init__(self, coordinator: HouseworkCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "housework_tasks_due_today"
        self._attr_device_info = hub_device_info()

    @property
    def native_value(self) -> int:
        return len(self._due_tasks())

    @property
    def extra_state_attributes(self) -> dict:
        tasks = self._due_tasks()
        return {
            "tasks": [t.title for t in tasks],
            "task_ids": [t.id for t in tasks],
        }

    def _due_tasks(self) -> list:
        if not self.coordinator.data:
            return []
        today = dt_util.now().date()
        return [
            task for task in self.coordinator.data.values()
            if task.next_due
            and self._parse_date(task.next_due) == today
        ]

    @staticmethod
    def _parse_date(s: str) -> date | None:
        try:
            return date.fromisoformat(s)
        except (ValueError, TypeError):
            return None


class HouseworkOverdueSensor(CoordinatorEntity[HouseworkCoordinator], SensorEntity):
    """Sensor showing count of overdue tasks."""

    _attr_has_entity_name = True
    _attr_translation_key = "overdue_tasks"
    _attr_icon = "mdi:calendar-alert"
    _attr_native_unit_of_measurement = "tasks"

    def __init__(self, coordinator: HouseworkCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "housework_overdue_tasks"
        self._attr_device_info = hub_device_info()

    @property
    def native_value(self) -> int:
        return len(self._overdue_tasks())

    @property
    def extra_state_attributes(self) -> dict:
        today = dt_util.now().date()
        tasks = self._overdue_tasks()
        task_details = []
        for task in tasks:
            try:
                due = date.fromisoformat(task.next_due)
                days = (today - due).days
            except (ValueError, TypeError):
                days = 0
            task_details.append({"title": task.title, "days_overdue": days})

        return {
            "tasks": [t.title for t in tasks],
            "task_ids": [t.id for t in tasks],
            "details": task_details,
        }

    def _overdue_tasks(self) -> list:
        if not self.coordinator.data:
            return []
        today = dt_util.now().date()
        result = []
        for task in self.coordinator.data.values():
            if not task.next_due:
                continue
            try:
                due = date.fromisoformat(task.next_due)
            except (ValueError, TypeError):
                continue
            if due < today:
                result.append(task)
        return result
