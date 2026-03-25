"""Sensor platform for the Housework integration."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HouseworkCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Housework sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HouseworkCoordinator = data["coordinator"]

    async_add_entities([
        HouseworkDueTodaySensor(coordinator, entry),
        HouseworkOverdueSensor(coordinator, entry),
    ])


class HouseworkDueTodaySensor(CoordinatorEntity[HouseworkCoordinator], SensorEntity):
    """Sensor showing count of tasks due today."""

    _attr_has_entity_name = True
    _attr_name = "Tasks Due Today"
    _attr_icon = "mdi:calendar-today"
    _attr_native_unit_of_measurement = "tasks"

    def __init__(
        self,
        coordinator: HouseworkCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "housework_tasks_due_today"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "housework_hub")},
        }

    @property
    def native_value(self) -> int:
        """Return the count of tasks due today."""
        return len(self._due_tasks())

    @property
    def extra_state_attributes(self) -> dict:
        """Return task titles as attributes."""
        tasks = self._due_tasks()
        return {
            "tasks": [t.title for t in tasks],
            "task_ids": [t.id for t in tasks],
        }

    def _due_tasks(self) -> list:
        """Return tasks due today or overdue."""
        if not self.coordinator.data:
            return []

        today = date.today()
        result = []
        for task in self.coordinator.data.values():
            if not task.enabled or not task.next_due:
                continue
            try:
                due = date.fromisoformat(task.next_due)
            except (ValueError, TypeError):
                continue
            if due <= today:
                result.append(task)
        return result


class HouseworkOverdueSensor(CoordinatorEntity[HouseworkCoordinator], SensorEntity):
    """Sensor showing count of overdue tasks."""

    _attr_has_entity_name = True
    _attr_name = "Overdue Tasks"
    _attr_icon = "mdi:calendar-alert"
    _attr_native_unit_of_measurement = "tasks"

    def __init__(
        self,
        coordinator: HouseworkCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "housework_overdue_tasks"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "housework_hub")},
        }

    @property
    def native_value(self) -> int:
        """Return the count of overdue tasks."""
        return len(self._overdue_tasks())

    @property
    def extra_state_attributes(self) -> dict:
        """Return overdue task details as attributes."""
        today = date.today()
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
        """Return tasks that are overdue (due before today, not today)."""
        if not self.coordinator.data:
            return []

        today = date.today()
        result = []
        for task in self.coordinator.data.values():
            if not task.enabled or not task.next_due:
                continue
            try:
                due = date.fromisoformat(task.next_due)
            except (ValueError, TypeError):
                continue
            if due < today:
                result.append(task)
        return result
