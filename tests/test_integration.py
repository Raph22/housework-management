"""Exercise the integration with real Home Assistant config entries and entities."""

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def setup_housework(hass, task_data=None, options=None, task_id=None):
    """Create and load the integration, optionally with one task."""
    subentries = []
    if task_data is not None:
        subentries.append(
            {
                "data": task_data,
                "subentry_type": "task",
                "title": task_data["title"],
                "unique_id": None,
            }
        )
        if task_id is not None:
            subentries[0]["subentry_id"] = task_id
    entry = MockConfigEntry(
        domain="housework",
        data={},
        title="Housework",
        unique_id="housework",
        subentries_data=subentries,
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_empty_integration_loads_and_registers_services(hass):
    """Initial setup creates the hub and all eight actions."""
    entry = await setup_housework(hass)
    assert entry.runtime_data.coordinator.data == {}
    assert len(hass.services.async_services()["housework"]) == 8
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {entity.domain for entity in entities} == {"calendar", "sensor"}
    assert len(entities) == 3


async def test_button_completion_survives_immediate_reload(hass):
    """A real button press followed by reload keeps completed once-tasks done."""
    entry = await setup_housework(
        hass,
        {
            "title": "Bathroom",
            "frequency_type": "once",
            "next_due": dt_util.now().date().isoformat(),
        },
    )
    task_id = next(iter(entry.subentries))
    registry = er.async_get(hass)
    button_id = registry.async_get_entity_id(
        "button", "housework", f"housework_{task_id}_mark_done"
    )
    assert button_id is not None
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] is None
    assert len(entry.runtime_data.store.get_history(task_id)) == 1

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] is None
    assert len(entry.runtime_data.store.get_history(task_id)) == 1
    due_id = registry.async_get_entity_id("binary_sensor", "housework", f"housework_{task_id}_due")
    assert hass.states.get(due_id).state == "off"


async def test_priority_edit_preserves_recent_completion(hass):
    """A subentry-triggered reload must keep recent history and runtime dates."""
    entry = await setup_housework(
        hass,
        {
            "title": "Bathroom",
            "frequency_type": "weekly",
            "assignees": ["person.alice", "person.bob"],
        },
    )
    task_id = next(iter(entry.subentries))
    registry = er.async_get(hass)
    button_id = registry.async_get_entity_id(
        "button", "housework", f"housework_{task_id}_mark_done"
    )
    priority_id = registry.async_get_entity_id(
        "select", "housework", f"housework_{task_id}_priority"
    )
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    next_due = entry.runtime_data.store.get_runtime_state(task_id)["next_due"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": priority_id, "option": "1"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.subentries[task_id].data["priority"] == 1
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] == next_due
    assert entry.runtime_data.store.get_runtime_state(task_id)["current_assignee"] == "person.bob"
    assert len(entry.runtime_data.store.get_history(task_id)) == 1


async def test_task_service_lifecycle_with_subentry_reloads(hass, hass_storage):
    """Create, complete, edit and remove through registered HA services."""
    entry = await setup_housework(
        hass, options={"default_priority": 1, "default_assignment_strategy": "fixed"}
    )
    await hass.services.async_call(
        "housework", "add_task", {"title": "Bathroom", "frequency_type": "weekly"}, blocking=True
    )
    await hass.async_block_till_done()
    task_id = next(iter(entry.subentries))
    registry = er.async_get(hass)
    assert entry.subentries[task_id].data["priority"] == 1
    assert entry.subentries[task_id].data["assignment_strategy"] == "fixed"
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 7
    next_due_id = registry.async_get_entity_id(
        "sensor", "housework", f"housework_{task_id}_next_due"
    )
    due_id = registry.async_get_entity_id("binary_sensor", "housework", f"housework_{task_id}_due")
    await hass.services.async_call(
        "housework", "complete_task", {"entity_id": next_due_id}, blocking=True
    )
    next_due = entry.runtime_data.store.get_runtime_state(task_id)["next_due"]
    assert len(entry.runtime_data.store.get_history(task_id)) == 1
    await hass.services.async_call(
        "housework",
        "update_task",
        {"entity_id": due_id, "title": "Bathroom updated"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.subentries[task_id].title == "Bathroom updated"
    assert entry.runtime_data.store.get_runtime_state(task_id)["next_due"] == next_due
    assert len(entry.runtime_data.store.get_history(task_id)) == 1
    await hass.services.async_call("housework", "remove_task", {"entity_id": due_id}, blocking=True)
    await hass.async_block_till_done()
    assert entry.subentries == {}
    assert entry.runtime_data.store.get_runtime_state(task_id) == {}
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 3

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert "housework" not in hass_storage


async def test_v040_storage_loads_in_place_with_completed_task(hass, hass_storage):
    """Updating existing subentry-format storage must preserve its runtime data."""
    data = {
        "title": "Bathroom",
        "frequency_type": "once",
        "next_due": "2026-10-01",
        "assignees": ["person.alice", "person.bob"],
    }
    signature = {
        "frequency_type": "once",
        "frequency_value": None,
        "frequency_days_of_week": None,
        "frequency_day_of_month": None,
        "scheduling_mode": None,
        "next_due": "2026-10-01",
    }
    completed_at = "2026-10-01T10:00:00+00:00"
    hass_storage["housework"] = {
        "version": 1,
        "minor_version": 1,
        "key": "housework",
        "data": {
            "runtime_state": {
                "saved-task": {
                    "next_due": None,
                    "last_completed": completed_at,
                    "current_assignee": "person.bob",
                    "created_at": "2026-09-30T10:00:00+00:00",
                    "scheduling_signature": signature,
                }
            },
            "history": [
                {
                    "id": "saved-completion",
                    "task_id": "saved-task",
                    "completed_by": "person.alice",
                    "completed_at": completed_at,
                    "action": "completed",
                    "notes": "",
                    "snooze_until": None,
                }
            ],
            "assignment_state": {
                "saved-task": {
                    "last_assignee": "person.alice",
                    "completion_counts": {"person.alice": 1},
                }
            },
        },
    }
    entry = await setup_housework(hass, data, task_id="saved-task")
    task = entry.runtime_data.coordinator.data["saved-task"]
    assert task.next_due is None
    assert task.last_completed == completed_at
    assert task.current_assignee == "person.bob"
    record = entry.runtime_data.store.get_history("saved-task")[0]
    assert record.id == "saved-completion"
    assert record.completed_by == "person.alice"
    assert entry.runtime_data.store.get_assignment_state("saved-task")["completion_counts"] == {
        "person.alice": 1
    }
    assert entry.subentries["saved-task"].data == data
