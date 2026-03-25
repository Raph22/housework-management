"""The Housework integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .coordinator import HouseworkCoordinator
from .models import Task
from .scheduling import calculate_initial_due, calculate_next_due
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
        await _ensure_runtime_state(store, subentry)

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

    # Listen for subentry changes (reconfigure) to reconcile runtime state
    @callback
    def _async_on_subentry_changed(
        change: str,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Handle subentry added/updated/removed."""
        if subentry.subentry_type != "task":
            return

        if change == "removed":
            hass.async_create_task(
                store.async_remove_runtime_state(subentry.subentry_id)
            )
            hass.async_create_task(coordinator.async_request_refresh())
            return

        if change == "added":
            hass.async_create_task(
                _ensure_runtime_state(store, subentry)
            )
            hass.async_create_task(coordinator.async_request_refresh())
            return

        if change == "updated":
            hass.async_create_task(
                _reconcile_runtime_after_edit(store, subentry)
            )
            hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        entry.async_on_subentry_change(_async_on_subentry_changed)
    )

    return True


async def _ensure_runtime_state(
    store: HouseworkStore, subentry: ConfigSubentry
) -> None:
    """Initialize runtime state for a new task subentry if needed."""
    state = store.get_runtime_state(subentry.subentry_id)
    if state.get("next_due"):
        return

    task = Task.from_subentry(subentry.subentry_id, dict(subentry.data))
    initial_due = calculate_initial_due(task)
    updates = {
        "next_due": initial_due.isoformat(),
        "created_at": state.get("created_at", task.created_at),
    }
    if task.assignees and not state.get("current_assignee"):
        updates["current_assignee"] = task.assignees[0]
    await store.async_update_runtime_state(subentry.subentry_id, updates)


async def _reconcile_runtime_after_edit(
    store: HouseworkStore, subentry: ConfigSubentry
) -> None:
    """Reconcile runtime state after a subentry is reconfigured.

    - If frequency changed, recalculate next_due from last_completed
    - If assignees changed and current_assignee is no longer valid, reset it
    """
    state = store.get_runtime_state(subentry.subentry_id)
    data = dict(subentry.data)
    updates = {}

    # Rebuild task to check new config vs current runtime
    task = Task.from_subentry(subentry.subentry_id, data, state)

    # Recalculate next_due based on new frequency settings
    if task.last_completed:
        new_next_due = calculate_next_due(task)
        if new_next_due:
            updates["next_due"] = new_next_due.isoformat()
    elif not state.get("next_due"):
        initial_due = calculate_initial_due(task)
        updates["next_due"] = initial_due.isoformat()

    # Reconcile assignee
    new_assignees = data.get("assignees", [])
    current_assignee = state.get("current_assignee")
    if new_assignees and (not current_assignee or current_assignee not in new_assignees):
        updates["current_assignee"] = new_assignees[0]
    elif not new_assignees:
        updates["current_assignee"] = None

    if updates:
        await store.async_update_runtime_state(subentry.subentry_id, updates)


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
