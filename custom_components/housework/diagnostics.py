"""Diagnostics support for the Housework integration."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

REDACT_KEYS = {
    "title",
    "description",
    "assignees",
    "current_assignee",
    "completed_by",
    "last_assignee",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return diagnostics for a config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    store = getattr(runtime_data, "store", None)

    runtime_state = store.get_all_runtime_state() if store else {}
    assignment_state = store.get_all_assignment_state() if store else {}

    diagnostics = {
        "entry_id": entry.entry_id,
        "data": dict(entry.data),
        "options": dict(entry.options),
        "subentries": {
            subentry_id: dict(subentry.data)
            for subentry_id, subentry in entry.subentries.items()
        },
        "runtime_state": runtime_state,
        "assignment_state": assignment_state,
    }
    return async_redact_data(diagnostics, REDACT_KEYS)
