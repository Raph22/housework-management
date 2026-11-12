"""Task form regression tests using Home Assistant's subentry flow manager."""

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.housework import HouseworkRuntimeData
from custom_components.housework.const import DOMAIN
from custom_components.housework.coordinator import HouseworkCoordinator
from custom_components.housework.store import HouseworkStore


def schema_field(result: dict, name: str):
    """Get field metadata from a returned form schema."""
    return next(key for key in result["data_schema"].schema if key.schema == name)


def task_entry(hass: HomeAssistant, **kwargs) -> MockConfigEntry:
    """Add a real task config entry with test-only deterministic identifiers."""
    entry = MockConfigEntry(domain=DOMAIN, **kwargs)
    entry.add_to_hass(hass)
    return entry


async def test_new_task_form_uses_entry_defaults(hass: HomeAssistant) -> None:
    entry = task_entry(
        hass, options={"default_priority": 1, "default_assignment_strategy": "least_completed"}
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert schema_field(result, "priority").default() == "1"
    assert schema_field(result, "assignment_strategy").default() == "least_completed"


async def test_reconfigure_keeps_existing_task_defaults(hass: HomeAssistant) -> None:
    entry = task_entry(
        hass,
        options={"default_priority": 1, "default_assignment_strategy": "least_completed"},
        subentries_data=[
            {
                "subentry_id": "task",
                "subentry_type": "task",
                "title": "Sweep",
                "unique_id": None,
                "data": {"title": "Sweep", "priority": 4, "assignment_strategy": "fixed"},
            }
        ],
    )
    result = await entry.start_subentry_reconfigure_flow(hass, "task")
    assert schema_field(result, "priority").default() == "4"
    assert schema_field(result, "assignment_strategy").default() == "fixed"


async def test_completed_once_form_does_not_suggest_stale_due(hass: HomeAssistant) -> None:
    entry = task_entry(
        hass,
        subentries_data=[
            {
                "subentry_id": "task",
                "subentry_type": "task",
                "title": "Repair",
                "unique_id": None,
                "data": {"title": "Repair", "frequency_type": "once", "next_due": "2026-10-01"},
            }
        ],
    )
    store = HouseworkStore(hass)
    await store.async_update_runtime_state(
        "task", {"next_due": None, "last_completed": "2026-10-01T12:00:00+02:00"}
    )
    entry.runtime_data = HouseworkRuntimeData(store, HouseworkCoordinator(hass, store, entry))
    result = await entry.start_subentry_reconfigure_flow(hass, "task")
    assert schema_field(result, "next_due").description["suggested_value"] is None


@pytest.mark.parametrize("title", ["", "   ", "\n\t"])
@pytest.mark.parametrize("reconfigure", [False, True])
async def test_form_rejects_blank_titles(
    hass: HomeAssistant, title: str, reconfigure: bool
) -> None:
    entry = task_entry(
        hass,
        subentries_data=[
            {
                "subentry_id": "task",
                "subentry_type": "task",
                "title": "Sweep",
                "unique_id": None,
                "data": {"title": "Sweep"},
            }
        ],
    )
    if reconfigure:
        result = await entry.start_subentry_reconfigure_flow(hass, "task")
    else:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "task"), context={"source": SOURCE_USER}
        )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"title": title, "frequency_type": "weekly"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "title_required"}


@pytest.mark.parametrize("reconfigure", [False, True])
async def test_form_rejects_invalid_recurrence(hass: HomeAssistant, reconfigure: bool) -> None:
    entry = task_entry(
        hass,
        subentries_data=[
            {
                "subentry_id": "task",
                "subentry_type": "task",
                "title": "Sweep",
                "unique_id": None,
                "data": {"title": "Sweep"},
            }
        ],
    )
    if reconfigure:
        result = await entry.start_subentry_reconfigure_flow(hass, "task")
    else:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "task"), context={"source": SOURCE_USER}
        )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"title": "Sweep", "frequency_type": "weekly", "frequency_value": 1.5}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "frequency_value_invalid"}


@pytest.mark.parametrize("value", [0, -1])
async def test_form_schema_requires_positive_recurrence(hass: HomeAssistant, value: int) -> None:
    entry = task_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"title": "Sweep", "frequency_type": "weekly", "frequency_value": value},
        )


async def test_form_stores_integral_selector_number(hass: HomeAssistant) -> None:
    entry = task_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"title": "Sweep", "frequency_type": "weekly", "frequency_value": 2.0}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["frequency_value"] == 2
    assert isinstance(result["data"]["frequency_value"], int)


async def test_form_normalizes_title(hass: HomeAssistant) -> None:
    """Creation follows the same whitespace handling as service-created tasks."""
    entry = task_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"title": "  Sweep  ", "frequency_type": "weekly"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sweep"
    assert result["data"]["title"] == "Sweep"


async def completed_once_from_flow(hass: HomeAssistant):
    """Create and complete a once task through real config and button flows."""
    entry = task_entry(hass, unique_id=DOMAIN)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    due = dt_util.now().date().isoformat()
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"title": "Repair", "frequency_type": "once", "next_due": due}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    task_id = next(iter(entry.subentries))
    registry = er.async_get(hass)
    button_id = registry.async_get_entity_id("button", DOMAIN, f"housework_{task_id}_mark_done")
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] is None
    return entry, task_id, due


@pytest.mark.parametrize("change_title", [False, True])
async def test_completed_once_reopens_when_original_date_is_explicit(
    hass: HomeAssistant, change_title: bool
) -> None:
    """Submitting a date is an intentional reopening even if config is unchanged."""
    entry, task_id, due = await completed_once_from_flow(hass)
    original_data = dict(entry.subentries[task_id].data)
    result = await entry.start_subentry_reconfigure_flow(hass, task_id)
    assert schema_field(result, "next_due").description["suggested_value"] is None
    user_input = dict(original_data)
    user_input["priority"] = str(user_input["priority"])
    if change_title:
        user_input["title"] = "Repair updated"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)
    assert result["type"] == FlowResultType.ABORT
    await hass.async_block_till_done()
    if not change_title:
        assert dict(entry.subentries[task_id].data) == original_data
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] == due
    assert entry.runtime_data.coordinator.data[task_id].next_due == due
    due_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"housework_{task_id}_due"
    )
    assert hass.states.get(due_id).state == "on"
    assert len(entry.runtime_data.store.get_history(task_id)) == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] == due


async def test_completed_once_edit_without_date_stays_completed(hass: HomeAssistant) -> None:
    """Ordinary task edits keep the terminal state until a date is submitted."""
    entry, task_id, _ = await completed_once_from_flow(hass)
    result = await entry.start_subentry_reconfigure_flow(hass, task_id)
    user_input = dict(entry.subentries[task_id].data)
    user_input.pop("next_due")
    user_input["priority"] = str(user_input["priority"])
    user_input["title"] = "Repair updated"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)
    assert result["type"] == FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] is None
    assert len(entry.runtime_data.store.get_history(task_id)) == 1


async def test_invalid_reconfigure_cannot_reopen_completed_once(hass: HomeAssistant) -> None:
    """A date only takes effect after the rest of the form is validated."""
    entry, task_id, due = await completed_once_from_flow(hass)
    result = await entry.start_subentry_reconfigure_flow(hass, task_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"title": "  ", "frequency_type": "once", "next_due": due}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "title_required"}
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] is None
    assert len(entry.runtime_data.store.get_history(task_id)) == 1
