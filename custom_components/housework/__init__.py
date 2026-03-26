"""The Housework integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HouseworkCoordinator
from .services import async_setup_services, async_unload_services
from .store import HouseworkStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "button", "calendar", "select", "sensor"]

type HouseworkConfigEntry = ConfigEntry[HouseworkRuntimeData]


@dataclass
class HouseworkRuntimeData:
    """Runtime data for the Housework integration."""

    store: HouseworkStore
    coordinator: HouseworkCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: HouseworkConfigEntry) -> bool:
    """Set up Housework from a config entry."""
    store = HouseworkStore(hass)
    await store.async_load()

    # Runtime state initialization is handled by the coordinator's
    # _async_update_data on first refresh (and every subsequent refresh).
    coordinator = HouseworkCoordinator(hass, store, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = HouseworkRuntimeData(store=store, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)

    # Reload integration when options change
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: HouseworkConfigEntry
) -> None:
    """Reload the integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HouseworkConfigEntry) -> bool:
    """Unload a Housework config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await async_unload_services(hass)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: HouseworkConfigEntry) -> None:
    """Clean up storage when the integration is removed."""
    if hasattr(entry, "runtime_data") and entry.runtime_data:
        await entry.runtime_data.store.async_remove()
    else:
        store = HouseworkStore(hass)
        await store.async_remove()
