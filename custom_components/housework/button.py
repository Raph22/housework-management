"""Button platform for the Housework integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .actions import async_complete_task
from .coordinator import SUBENTRY_TYPE_TASK, HouseworkCoordinator
from .entity import task_device_info
from .models import Task


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
            known_task_ids.clear()
            return
        known_task_ids.difference_update(known_task_ids - set(coordinator.data.keys()))
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

        await async_complete_task(
            self.hass,
            task,
            self.coordinator.store,
            self.coordinator,
        )
