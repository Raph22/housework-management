"""Select platform for the Housework integration."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HouseworkCoordinator, SUBENTRY_TYPE_TASK
from .entity import task_device_info
from .models import Task

_LOGGER = logging.getLogger(__name__)

PRIORITY_OPTIONS = ["1", "2", "3", "4"]
PRIORITY_LABELS = {
    "1": "P1",
    "2": "P2",
    "3": "P3",
    "4": "P4",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Housework select entities from a config entry."""
    coordinator = entry.runtime_data.coordinator

    known_task_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if not coordinator.data:
            known_task_ids.clear()
            return
        known_task_ids.difference_update(
            known_task_ids - set(coordinator.data.keys())
        )
        for task_id, task in coordinator.data.items():
            if task_id not in known_task_ids:
                known_task_ids.add(task_id)
                async_add_entities(
                    [HouseworkPrioritySelect(coordinator, task, entry)],
                    config_subentry_id=task_id,
                )

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_TASK:
            continue
        task_id = subentry.subentry_id
        if coordinator.data and task_id in coordinator.data:
            known_task_ids.add(task_id)
            async_add_entities(
                [HouseworkPrioritySelect(coordinator, coordinator.data[task_id], entry)],
                config_subentry_id=task_id,
            )

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class HouseworkPrioritySelect(CoordinatorEntity[HouseworkCoordinator], SelectEntity):
    """Select entity to view and change task priority."""

    _attr_has_entity_name = True
    _attr_translation_key = "priority"
    _attr_icon = "mdi:flag"
    _attr_options = PRIORITY_OPTIONS

    def __init__(
        self,
        coordinator: HouseworkCoordinator,
        task: Task,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, context=task.id)
        self._task_id = task.id
        self._entry = entry
        self._attr_unique_id = f"housework_{task.id}_priority"
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
    def current_option(self) -> str | None:
        task = self._task
        if task is None:
            return None
        return str(task.priority)

    async def async_select_option(self, option: str) -> None:
        """Handle priority change from the UI."""
        task = self._task
        if task is None:
            return

        new_priority = int(option)

        # Update subentry data
        subentry = self._entry.subentries.get(self._task_id)
        if subentry is None:
            return

        new_data = dict(subentry.data)
        new_data["priority"] = new_priority
        self.hass.config_entries.async_update_subentry(
            self._entry, subentry, data=new_data
        )
        await self.coordinator.async_request_refresh()
        _LOGGER.info("Changed priority of %s to P%s", task.title, new_priority)
