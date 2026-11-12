"""Private person IDs must be absent from downloaded diagnostics."""

import json

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.housework import HouseworkRuntimeData
from custom_components.housework.const import DOMAIN
from custom_components.housework.coordinator import HouseworkCoordinator
from custom_components.housework.diagnostics import async_get_config_entry_diagnostics
from custom_components.housework.store import HouseworkStore


async def test_diagnostics_redact_person_ids_in_count_keys(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        subentries_data=[
            {
                "subentry_id": "task",
                "subentry_type": "task",
                "title": "Sweep",
                "unique_id": None,
                "data": {
                    "title": "Sweep",
                    "description": "Bedroom",
                    "priority": 2,
                    "assignees": ["person.alice"],
                },
            }
        ],
    )
    entry.add_to_hass(hass)
    store = HouseworkStore(hass)
    await store.async_update_assignment_state(
        "task",
        {
            "last_assignee": "person.alice",
            "completion_counts": {"person.alice": 3, "person.bob": 5},
        },
    )
    await store.async_update_runtime_state(
        "task", {"current_assignee": "person.bob", "next_due": "2026-10-13"}
    )
    entry.runtime_data = HouseworkRuntimeData(store, HouseworkCoordinator(hass, store, entry))
    result = await async_get_config_entry_diagnostics(hass, entry)
    encoded = json.dumps(result)
    assert "person.alice" not in encoded
    assert "person.bob" not in encoded
    assert result["subentries"]["task"]["title"] == REDACTED
    assert result["subentries"]["task"]["priority"] == 2
    assert result["runtime_state"]["task"]["next_due"] == "2026-10-13"
    assert store.get_assignment_state("task")["completion_counts"] == {
        "person.alice": 3,
        "person.bob": 5,
    }
