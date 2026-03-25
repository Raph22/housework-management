"""The Housework integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HouseworkCoordinator
from .scheduling import calculate_initial_due
from .models import Task
from .services import async_setup_services, async_unload_services
from .store import HouseworkStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "calendar", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Housework from a config entry."""
    store = HouseworkStore(hass)
    await store.async_load()

    # Ensure runtime state exists for all task subentries
    for subentry in entry.subentries.values():
        if subentry.subentry_type != "task":
            continue
        state = store.get_runtime_state(subentry.subentry_id)
        if not state.get("next_due"):
            task = Task.from_subentry(subentry.subentry_id, dict(subentry.data))
            initial_due = calculate_initial_due(task)
            await store.async_update_runtime_state(subentry.subentry_id, {
                "next_due": initial_due.isoformat(),
                "created_at": state.get("created_at", task.created_at),
            })
            # Set initial assignee
            if task.assignees and not state.get("current_assignee"):
                await store.async_update_runtime_state(subentry.subentry_id, {
                    "current_assignee": task.assignees[0],
                })

    coordinator = HouseworkCoordinator(hass, store, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)

    # Reload integration when options change
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Housework config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up storage when the integration is removed."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data and "store" in entry_data:
        await entry_data["store"].async_remove()
    else:
        store = HouseworkStore(hass)
        await store.async_remove()
