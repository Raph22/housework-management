"""DataUpdateCoordinator for the Housework integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .models import Task
from .store import HouseworkStore

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=15)

SUBENTRY_TYPE_TASK = "task"


class HouseworkCoordinator(DataUpdateCoordinator[dict[str, Task]]):
    """Coordinator that merges subentry config + runtime state into Task objects."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        store: HouseworkStore,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=config_entry,
        )
        self.store = store

    async def _async_update_data(self) -> dict[str, Task]:
        """Build Task objects from subentries + runtime state."""
        tasks: dict[str, Task] = {}
        all_runtime = self.store.get_all_runtime_state()

        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_TASK:
                continue

            runtime = all_runtime.get(subentry.subentry_id, {})
            task = Task.from_subentry(
                subentry_id=subentry.subentry_id,
                subentry_data=dict(subentry.data),
                runtime_state=runtime,
            )
            tasks[subentry.subentry_id] = task

        return tasks
