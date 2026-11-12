"""Regression tests for runtime-state persistence."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.housework import HouseworkRuntimeData, async_unload_entry
from custom_components.housework.models import CompletionRecord
from custom_components.housework.services import async_setup_services
from custom_components.housework.store import HouseworkStore


async def test_unload_persists_delayed_completion_before_replacement_load(hass):
    """A reload must not restore the state preceding a recent completion."""
    store = HouseworkStore(hass)
    await store.async_load()
    await store.async_update_runtime_state(
        "task", {"next_due": None, "last_completed": "2026-10-13T10:00:00+00:00"}
    )
    await store.async_add_history(CompletionRecord(task_id="task", completed_by="person.alice"))
    await store.async_update_assignment_state("task", {"completion_counts": {"person.alice": 1}})
    entry = MockConfigEntry(domain="housework", data={}, title="Housework")
    entry.add_to_hass(hass)
    entry.runtime_data = HouseworkRuntimeData(store=store, coordinator=AsyncMock())
    await async_setup_services(hass)

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry)

    replacement = HouseworkStore(hass)
    await replacement.async_load()
    assert replacement.get_runtime_state("task")["last_completed"] == "2026-10-13T10:00:00+00:00"
    assert replacement.get_runtime_state("task")["next_due"] is None
    assert len(replacement.get_history("task")) == 1
    assert replacement.get_assignment_state("task")["completion_counts"] == {"person.alice": 1}


async def test_remove_cancels_pending_write(hass, hass_storage):
    """Deleting the integration must prevent an old timer recreating its store."""
    store = HouseworkStore(hass)
    await store.async_load()
    await store.async_update_runtime_state("task", {"next_due": "2026-10-14"})
    await store.async_remove()
    assert "housework" not in hass_storage
