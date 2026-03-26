"""The Housework integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HouseworkCoordinator
from .models import Task
from .scheduling import calculate_initial_due
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

    # Ensure runtime state exists for all task subentries
    for subentry in entry.subentries.values():
        if subentry.subentry_type != "task":
            continue
        state = store.get_runtime_state(subentry.subentry_id)
        if not state.get("next_due"):
            data = dict(subentry.data)
            task = Task.from_subentry(subentry.subentry_id, data)
            if data.get("next_due"):
                initial_due_str = data["next_due"]
            else:
                initial_due_str = calculate_initial_due(task).isoformat()
            updates = {
                "next_due": initial_due_str,
                "created_at": state.get("created_at", task.created_at),
            }
            if task.assignees and not state.get("current_assignee"):
                updates["current_assignee"] = task.assignees[0]
            await store.async_update_runtime_state(subentry.subentry_id, updates)

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
