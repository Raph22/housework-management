"""Fresh installation through Home Assistant's actual configuration flows."""

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.housework.const import DOMAIN


async def install_from_user_flow(hass):
    """Create the singleton integration as a user installing it for the first time."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state == ConfigEntryState.LOADED
    return entry


async def test_fresh_user_flow_loads_hub_and_actions(hass, hass_storage):
    """An empty installation needs no saved tasks or pre-existing configuration."""
    assert DOMAIN not in hass_storage
    assert hass.config_entries.async_entries(DOMAIN) == []
    entry = await install_from_user_flow(hass)

    assert entry.title == "Housework"
    assert entry.unique_id == DOMAIN
    assert entry.data == {}
    assert entry.subentries == {}
    assert entry.runtime_data.coordinator.data == {}
    assert set(hass.services.async_services()[DOMAIN]) == {
        "add_task",
        "complete_task",
        "skip_task",
        "snooze_task",
        "reassign_task",
        "update_task",
        "remove_task",
        "reopen_task",
    }
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 3
    assert {entity.domain for entity in entities} == {"calendar", "sensor"}


async def test_fresh_task_ui_completion_survives_reload(hass):
    """UI creation initializes entities and persists subsequent completion and rotation."""
    entry = await install_from_user_flow(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "title": "Bathroom",
            "frequency_type": "weekly",
            "frequency_value": 2.0,
            "next_due": dt_util.now().date().isoformat(),
            "assignees": ["person.alice", "person.bob"],
            "assignment_strategy": "round_robin",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    task_id = next(iter(entry.subentries))
    registry = er.async_get(hass)
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 7
    assert entry.subentries[task_id].data["frequency_value"] == 2
    assert entry.runtime_data.coordinator.data[task_id].current_assignee == "person.alice"
    button_id = registry.async_get_entity_id("button", DOMAIN, f"housework_{task_id}_mark_done")
    assert button_id is not None
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)

    original_store = entry.runtime_data.store
    runtime = original_store.get_runtime_state(task_id)
    history = original_store.get_history(task_id)
    assignment = dict(original_store.get_assignment_state(task_id))
    assert runtime["next_due"] > dt_util.now().date().isoformat()
    assert runtime["current_assignee"] == "person.bob"
    assert len(history) == 1
    assert history[0].completed_by == "person.alice"

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    assert entry.runtime_data.store is not original_store
    assert entry.runtime_data.store.get_runtime_state(task_id) == runtime
    assert entry.runtime_data.store.get_history(task_id) == history
    assert entry.runtime_data.store.get_assignment_state(task_id) == assignment
    assert entry.runtime_data.coordinator.data[task_id].current_assignee == "person.bob"
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 7


async def test_fresh_install_rejects_second_parent_entry(hass):
    """The singleton manifest prevents a second integration configuration."""
    entry = await install_from_user_flow(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
