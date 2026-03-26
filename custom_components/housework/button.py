"""Button platform for the Housework integration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .assignment import determine_next_assignee, update_assignment_state
from .const import CompletionAction, FrequencyType
from .coordinator import HouseworkCoordinator, SUBENTRY_TYPE_TASK
from .entity import task_device_info
from .models import CompletionRecord, Task
from .scheduling import calculate_next_due

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Housework buttons from a config entry."""
    coordinator = entry.runtime_data.coordinator

    known_task_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if not coordinator.data:
            return
        for task_id, task in coordinator.data.items():
            if task_id not in known_task_ids:
                known_task_ids.add(task_id)
                async_add_entities(
                    [HouseworkMarkDoneButton(coordinator, task)],
                    config_subentry_id=task_id,
                )

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_TASK:
            continue
        task_id = subentry.subentry_id
        if coordinator.data and task_id in coordinator.data:
            known_task_ids.add(task_id)
            async_add_entities(
                [HouseworkMarkDoneButton(coordinator, coordinator.data[task_id])],
                config_subentry_id=task_id,
            )

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class HouseworkMarkDoneButton(CoordinatorEntity[HouseworkCoordinator], ButtonEntity):
    """Button to mark a housework task as done."""

    _attr_has_entity_name = True
    _attr_translation_key = "mark_done"
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coordinator: HouseworkCoordinator, task: Task) -> None:
        """Initialize the button."""
        super().__init__(coordinator, context=task.id)
        self._task_id = task.id
        self._attr_unique_id = f"housework_{task.id}_mark_done"
        self._attr_device_info = task_device_info(task)

    @property
    def _task(self) -> Task | None:
        if self.coordinator.data:
            return self.coordinator.data.get(self._task_id)
        return None

    @property
    def available(self) -> bool:
        return super().available and self._task is not None

    async def async_press(self) -> None:
        """Handle button press — complete the task."""
        task = self._task
        if task is None:
            return

        store = self.coordinator.store
        completed_at = datetime.now(timezone.utc).isoformat()
        completed_by = task.current_assignee or ""

        # Record history
        record = CompletionRecord(
            task_id=task.id,
            completed_by=completed_by,
            completed_at=completed_at,
            action=CompletionAction.COMPLETED,
        )
        await store.async_add_history(record)

        # Calculate next due
        runtime_updates: dict = {"last_completed": completed_at}
        if task.frequency_type != FrequencyType.ONCE:
            next_due = calculate_next_due(task, last_completed_override=completed_at)
            runtime_updates["next_due"] = next_due.isoformat() if next_due else None
        else:
            runtime_updates["next_due"] = None

        # Update assignment
        current_assignee = task.current_assignee
        if completed_by and task.assignees:
            state = store.get_assignment_state(task.id)
            state = update_assignment_state(state, completed_by)
            current_assignee = determine_next_assignee(task, state)
            await store.async_update_assignment_state(task.id, state)
        runtime_updates["current_assignee"] = current_assignee

        await store.async_update_runtime_state(task.id, runtime_updates)
        await self.coordinator.async_request_refresh()

        # Fire event
        self.hass.bus.async_fire(
            "housework_task_completed",
            {
                "task_id": task.id,
                "title": task.title,
                "completed_by": completed_by,
                "next_due": runtime_updates["next_due"],
            },
        )
        _LOGGER.info("Completed task via button: %s", task.title)
