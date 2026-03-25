"""Binary sensor platform for the Housework integration."""

from __future__ import annotations

import logging
from datetime import date

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import HouseworkCoordinator, SUBENTRY_TYPE_TASK
from .models import Task
from .scheduling import format_frequency

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Housework binary sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator

    known_task_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        """Add entities for any new tasks."""
        if not coordinator.data:
            return
        for task_id, task in coordinator.data.items():
            if task_id not in known_task_ids:
                known_task_ids.add(task_id)
                async_add_entities(
                    [HouseworkTaskSensor(coordinator, task)],
                    config_subentry_id=task_id,
                )

    # Add entities for existing task subentries
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_TASK:
            continue
        task_id = subentry.subentry_id
        if coordinator.data and task_id in coordinator.data:
            known_task_ids.add(task_id)
            async_add_entities(
                [HouseworkTaskSensor(coordinator, coordinator.data[task_id])],
                config_subentry_id=task_id,
            )

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class HouseworkTaskSensor(CoordinatorEntity[HouseworkCoordinator], BinarySensorEntity):
    """Binary sensor for a housework task. On when due or overdue."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HouseworkCoordinator,
        task: Task,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, context=task.id)
        self._task_id = task.id
        self._attr_unique_id = f"housework_{task.id}"
        self._attr_icon = task.icon

    @property
    def task_id(self) -> str:
        """Return the task ID."""
        return self._task_id

    @property
    def _task(self) -> Task | None:
        """Return the current task from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._task_id)
        return None

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        task = self._task
        return task.title if task else "Unknown Task"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._task is not None

    @property
    def is_on(self) -> bool | None:
        """Return True if the task is due or overdue, False if completed/upcoming."""
        task = self._task
        if task is None:
            return None

        # Once tasks with no next_due are completed — not due
        if task.next_due is None:
            return False

        try:
            due_date = date.fromisoformat(task.next_due)
        except (ValueError, TypeError):
            return None

        return dt_util.now().date() >= due_date

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra state attributes."""
        task = self._task
        if task is None:
            return None

        days_overdue = 0
        if task.next_due:
            try:
                due_date = date.fromisoformat(task.next_due)
                days_overdue = (dt_util.now().date() - due_date).days
            except (ValueError, TypeError):
                pass

        assignee_name = None
        if task.current_assignee:
            state = self.hass.states.get(task.current_assignee)
            if state:
                assignee_name = state.attributes.get(
                    "friendly_name", task.current_assignee
                )

        label_names = []
        all_labels = self.coordinator.store.get_all_labels()
        for label_id in task.labels:
            label = all_labels.get(label_id)
            if label:
                label_names.append(label.name)

        return {
            "task_id": task.id,
            "title": task.title,
            "priority": task.priority,
            "next_due": task.next_due,
            "last_completed": task.last_completed,
            "current_assignee": task.current_assignee,
            "assignee_name": assignee_name,
            "frequency": format_frequency(task),
            "labels": label_names,
            "days_overdue": max(days_overdue, 0),
            "scheduling_mode": task.scheduling_mode,
            "assignment_strategy": task.assignment_strategy,
        }

    @property
    def icon(self) -> str:
        """Return the icon."""
        task = self._task
        return task.icon if task else "mdi:broom"
