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


class HouseworkCoordinator(DataUpdateCoordinator[dict[str, Task]]):
    """Coordinator that keeps task state in sync across all entities."""

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
        """Fetch current task data from the store."""
        return self.store.get_all_tasks()
