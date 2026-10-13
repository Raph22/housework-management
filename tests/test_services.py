"""Regression tests for Housework actions on current Home Assistant."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.selector import NumberSelector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.housework import HouseworkRuntimeData
from custom_components.housework.button import HouseworkMarkDoneButton
from custom_components.housework.const import DOMAIN, FrequencyType
from custom_components.housework.coordinator import HouseworkCoordinator
from custom_components.housework.services import (
    ADD_TASK_SCHEMA,
    UPDATE_TASK_SCHEMA,
    async_setup_services,
)
from custom_components.housework.store import HouseworkStore

ENTITY_TYPES = (
    ("binary_sensor", "due"),
    ("button", "mark_done"),
    ("select", "priority"),
    ("sensor", "next_due"),
)
ACTION_DATA = {
    "complete_task": {"completed_at": "2026-10-13T10:00:00+00:00"},
    "skip_task": {},
    "snooze_task": {"snooze_until": "2026-11-01"},
    "reassign_task": {"assignee": "person.bob"},
    "update_task": {"title": "Changed title"},
    "remove_task": {},
    "reopen_task": {"next_due": "2026-11-01"},
}


@pytest.fixture
async def housework_runtime(hass, entity_registry, device_registry, area_registry, label_registry):
    """Create real tasks, storage, coordinator and linked registry entities."""
    area = area_registry.async_create("Kitchen")
    label = label_registry.async_create("Housework")
    coordinators = []

    async def make_entry(entry_id="housework-entry", task_ids=("task-a", "task-b")):
        entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id=entry_id,
            subentries_data=[
                {
                    "subentry_id": task_id,
                    "subentry_type": "task",
                    "unique_id": None,
                    "title": task_id,
                    "data": {
                        "title": task_id,
                        "frequency_type": "daily",
                        "frequency_value": 1,
                        "assignees": ["person.alice", "person.bob"],
                        "next_due": "2026-10-13",
                    },
                }
                for task_id in task_ids
            ],
        )
        entry.add_to_hass(hass)
        store = HouseworkStore(hass)
        coordinator = HouseworkCoordinator(hass, store, entry)
        coordinators.append(coordinator)
        await coordinator.async_refresh()
        entry.runtime_data = HouseworkRuntimeData(store, coordinator)
        entities = {}
        devices = {}
        for task_id in task_ids:
            device = device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                config_subentry_id=task_id,
                identifiers={(DOMAIN, f"{entry_id}-{task_id}")},
            )
            device_registry.async_update_device(device.id, area_id=area.id, labels={label.label_id})
            devices[task_id] = device
            for domain, suffix in ENTITY_TYPES:
                entity = entity_registry.async_get_or_create(
                    domain,
                    DOMAIN,
                    f"housework_{task_id}_{suffix}",
                    config_entry=entry,
                    config_subentry_id=task_id,
                    device_id=device.id,
                )
                entities[(task_id, suffix)] = entity.entity_id
        return SimpleNamespace(
            entry=entry, store=store, coordinator=coordinator, entities=entities, devices=devices
        )

    runtime = await make_entry()
    runtime.make_entry = make_entry
    runtime.area = area
    runtime.label = label
    await async_setup_services(hass)
    yield runtime
    for coordinator in coordinators:
        await coordinator.async_shutdown()


@pytest.mark.parametrize("service", ACTION_DATA)
@pytest.mark.parametrize("suffix", [suffix for _, suffix in ENTITY_TYPES])
async def test_actions_accept_each_task_entity(hass, housework_runtime, service, suffix):
    """Every public action resolves all four task entities on HA 2026.10."""
    runtime = housework_runtime
    await hass.services.async_call(
        DOMAIN,
        service,
        {"entity_id": runtime.entities[("task-a", suffix)], **ACTION_DATA[service]},
        blocking=True,
    )
    state = runtime.store.get_runtime_state("task-a")
    if service == "complete_task":
        assert len(runtime.store.get_history("task-a")) == 1
        assert state["next_due"] == "2026-10-14"
        assert state["current_assignee"] == "person.bob"
    elif service == "skip_task":
        assert len(runtime.store.get_history("task-a")) == 1
        assert state["next_due"] != "2026-10-13"
    elif service in ("snooze_task", "reopen_task"):
        assert state["next_due"] == "2026-11-01"
    elif service == "reassign_task":
        assert state["current_assignee"] == "person.bob"
    elif service == "update_task":
        assert runtime.entry.subentries["task-a"].title == "Changed title"
    elif service == "remove_task":
        assert "task-a" not in runtime.entry.subentries
        assert state == {}


@pytest.mark.parametrize("service", ["complete_task", "skip_task", "snooze_task", "remove_task"])
@pytest.mark.parametrize("target", ["device_id", "area_id", "label_id", "entity_id"])
async def test_targets_act_once_per_task(hass, housework_runtime, service, target):
    """Device, area and label targeting does not act once for each entity."""
    runtime = housework_runtime
    selection = {
        "device_id": runtime.devices["task-a"].id,
        "area_id": runtime.area.id,
        "label_id": runtime.label.label_id,
        "entity_id": [runtime.entities[("task-a", suffix)] for _, suffix in ENTITY_TYPES],
    }[target]
    task_ids = ("task-a", "task-b") if target in ("area_id", "label_id") else ("task-a",)
    await hass.services.async_call(
        DOMAIN,
        service,
        {target: selection, **ACTION_DATA[service]},
        blocking=True,
    )
    for task_id in task_ids:
        if service == "remove_task":
            assert task_id not in runtime.entry.subentries
            assert runtime.store.get_runtime_state(task_id) == {}
        else:
            assert len(runtime.store.get_history(task_id)) == 1
            if service == "complete_task":
                assert runtime.store.get_assignment_state(task_id)["completion_counts"] == {
                    "person.alice": 1,
                }


async def test_rapid_skips_advance_each_occurrence(hass, housework_runtime, freezer):
    """Blocking calls must use the current due date even when refresh is delayed."""
    freezer.move_to("2026-10-13T10:00:00+00:00")
    runtime = housework_runtime
    await runtime.store.async_update_runtime_state("task-a", {"next_due": "2026-10-23"})
    await runtime.coordinator.async_refresh()
    for expected_due in ("2026-10-24", "2026-10-25", "2026-10-26"):
        await hass.services.async_call(
            DOMAIN,
            "skip_task",
            {"entity_id": runtime.entities[("task-a", "due")]},
            blocking=True,
        )
        assert runtime.store.get_runtime_state("task-a")["next_due"] == expected_due
    assert len(runtime.store.get_history("task-a")) == 3


async def test_skip_immediately_after_snooze_uses_snoozed_date(
    hass,
    housework_runtime,
    freezer,
):
    """A snooze during the refresh cooldown must be visible to the next action."""
    freezer.move_to("2026-10-13T10:00:00+00:00")
    runtime = housework_runtime
    target = {"entity_id": runtime.entities[("task-a", "due")]}
    # The first action starts the coordinator's refresh cooldown.
    await hass.services.async_call(
        DOMAIN,
        "reassign_task",
        {**target, "assignee": "person.bob"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "snooze_task",
        {**target, "snooze_until": "2026-10-23"},
        blocking=True,
    )
    await hass.services.async_call(DOMAIN, "skip_task", target, blocking=True)
    assert runtime.store.get_runtime_state("task-a")["next_due"] == "2026-10-24"
    assert len(runtime.store.get_history("task-a")) == 2


@pytest.mark.parametrize("service", ["complete_task", "skip_task"])
@pytest.mark.parametrize("invalid_case", ["legacy_zero", "date_overflow"])
async def test_invalid_schedule_rejects_whole_batch_before_mutation(
    hass,
    housework_runtime,
    service,
    invalid_case,
):
    """An old invalid interval or overflowing date must not consume earlier tasks."""
    runtime = housework_runtime
    await _set_invalid_schedule(hass, runtime, invalid_case)
    state_before = deepcopy(runtime.store.get_all_runtime_state())
    assignment_before = deepcopy(runtime.store.get_all_assignment_state())
    events = []
    hass.bus.async_listen("housework_task_completed", events.append)
    hass.bus.async_listen("housework_task_skipped", events.append)
    with pytest.raises(Exception) as raised:
        await hass.services.async_call(
            DOMAIN,
            service,
            {
                "entity_id": [
                    runtime.entities[("task-a", "due")],
                    runtime.entities[("task-b", "due")],
                ],
                **ACTION_DATA[service],
            },
            blocking=True,
        )
    await hass.async_block_till_done()
    assert runtime.store.get_history() == []
    assert runtime.store.get_all_runtime_state() == state_before
    assert runtime.store.get_all_assignment_state() == assignment_before
    assert events == []
    assert isinstance(raised.value, ServiceValidationError)
    assert raised.value.translation_key == "invalid_task_configuration"


@pytest.mark.parametrize("invalid_case", ["legacy_zero", "date_overflow"])
async def test_button_invalid_schedule_has_clear_error_without_mutation(
    hass,
    housework_runtime,
    invalid_case,
):
    runtime = housework_runtime
    await _set_invalid_schedule(hass, runtime, invalid_case)
    state_before = deepcopy(runtime.store.get_all_runtime_state())
    button = HouseworkMarkDoneButton(runtime.coordinator, runtime.coordinator.data["task-b"])
    button.hass = hass
    with pytest.raises(ServiceValidationError) as raised:
        await button.async_press()
    assert raised.value.translation_key == "invalid_task_configuration"
    assert runtime.store.get_history() == []
    assert runtime.store.get_all_assignment_state() == {}
    assert runtime.store.get_all_runtime_state() == state_before


@pytest.mark.parametrize("service", ["remove_task", "snooze_task"])
async def test_invalid_legacy_interval_can_be_managed(hass, housework_runtime, service):
    """Users can still remove or postpone a task with an old zero interval."""
    runtime = housework_runtime
    await _set_invalid_schedule(hass, runtime, "legacy_zero")
    await hass.services.async_call(
        DOMAIN,
        service,
        {"entity_id": runtime.entities[("task-b", "due")], **ACTION_DATA[service]},
        blocking=True,
    )
    if service == "remove_task":
        assert "task-b" not in runtime.entry.subentries
    else:
        assert runtime.store.get_runtime_state("task-b")["next_due"] == "2026-11-01"


async def _set_invalid_schedule(hass, runtime, invalid_case):
    """Load the kind of interval accepted by 0.4, or an extreme fixed due date."""
    subentry = runtime.entry.subentries["task-b"]
    hass.config_entries.async_update_subentry(
        runtime.entry,
        subentry,
        data={
            **subentry.data,
            "frequency_value": 0 if invalid_case == "legacy_zero" else 1,
            "scheduling_mode": "fixed",
        },
    )
    await runtime.coordinator.async_refresh()
    if invalid_case == "date_overflow":
        await runtime.store.async_update_runtime_state("task-b", {"next_due": "9999-12-31"})
        await runtime.coordinator.async_refresh()


async def test_registry_relationship_resolves_task_without_unique_id_parsing(
    hass,
    housework_runtime,
    entity_registry,
):
    runtime = housework_runtime
    entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "opaque-identifier",
        config_entry=runtime.entry,
        config_subentry_id="task-a",
    )
    await hass.services.async_call(
        DOMAIN,
        "reopen_task",
        {"entity_id": entity.entity_id, "next_due": "2026-11-01"},
        blocking=True,
    )
    assert runtime.store.get_runtime_state("task-a")["next_due"] == "2026-11-01"


async def test_target_resolves_correct_config_entry(hass, housework_runtime):
    runtime = housework_runtime
    second = await runtime.make_entry("second-housework", ("task-second",))
    await hass.services.async_call(
        DOMAIN,
        "complete_task",
        {"entity_id": second.entities[("task-second", "mark_done")]},
        blocking=True,
    )
    assert len(second.store.get_history("task-second")) == 1
    assert runtime.store.get_history() == []


@pytest.mark.parametrize("target", ["area_id", "label_id"])
async def test_indirect_targets_ignore_foreign_entities(
    hass,
    housework_runtime,
    entity_registry,
    target,
):
    runtime = housework_runtime
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    entity = entity_registry.async_get_or_create(
        "light",
        "other",
        "foreign",
        config_entry=other,
    )
    entity_registry.async_update_entity(
        entity.entity_id,
        area_id=runtime.area.id,
        labels={runtime.label.label_id},
    )
    selection = runtime.area.id if target == "area_id" else runtime.label.label_id
    await hass.services.async_call(
        DOMAIN,
        "complete_task",
        {target: selection},
        blocking=True,
    )
    assert len(runtime.store.get_history("task-a")) == 1
    assert len(runtime.store.get_history("task-b")) == 1


@pytest.mark.parametrize("target", ["area_id", "label_id"])
@pytest.mark.parametrize("entity_domain", ["calendar", "sensor"])
async def test_indirect_targets_ignore_global_housework_entities(
    hass,
    housework_runtime,
    entity_registry,
    target,
    entity_domain,
):
    """The shared calendar and counters are not tasks in an area/label batch."""
    runtime = housework_runtime
    global_entity = entity_registry.async_get_or_create(
        entity_domain,
        DOMAIN,
        "housework-global",
        config_entry=runtime.entry,
    )
    entity_registry.async_update_entity(
        global_entity.entity_id,
        area_id=runtime.area.id,
        labels={runtime.label.label_id},
    )
    selection = runtime.area.id if target == "area_id" else runtime.label.label_id
    await hass.services.async_call(DOMAIN, "complete_task", {target: selection}, blocking=True)
    assert len(runtime.store.get_history("task-a")) == 1
    assert len(runtime.store.get_history("task-b")) == 1


async def test_explicit_global_housework_entity_rejects_batch(
    hass,
    housework_runtime,
    entity_registry,
):
    runtime = housework_runtime
    global_entity = entity_registry.async_get_or_create(
        "calendar",
        DOMAIN,
        "housework-global",
        config_entry=runtime.entry,
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "complete_task",
            {"entity_id": [runtime.entities[("task-a", "due")], global_entity.entity_id]},
            blocking=True,
        )
    assert runtime.store.get_history() == []


async def test_indirect_invalid_task_rejects_batch(hass, housework_runtime):
    """A task registry entry without a loaded task must remain a validation error."""
    runtime = housework_runtime
    del runtime.coordinator.data["task-b"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "complete_task",
            {"area_id": runtime.area.id},
            blocking=True,
        )
    assert runtime.store.get_history() == []


@pytest.mark.parametrize("service", ACTION_DATA)
async def test_invalid_explicit_batch_does_not_mutate_tasks(
    hass,
    housework_runtime,
    entity_registry,
    service,
):
    """An explicit foreign target must reject the whole batch before changes."""
    runtime = housework_runtime
    foreign = entity_registry.async_get_or_create("sensor", "other", "housework_task-a_due")
    state_before = deepcopy(runtime.store.get_all_runtime_state())
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            service,
            {
                "entity_id": [runtime.entities[("task-a", "due")], foreign.entity_id],
                **ACTION_DATA[service],
            },
            blocking=True,
        )
    assert runtime.store.get_history() == []
    assert runtime.store.get_all_runtime_state() == state_before
    assert set(runtime.entry.subentries) == {"task-a", "task-b"}
    assert runtime.entry.subentries["task-a"].title == "task-a"


async def test_batch_reassign_validation_precedes_mutation(hass, housework_runtime):
    runtime = housework_runtime
    subentry = runtime.entry.subentries["task-b"]
    hass.config_entries.async_update_subentry(
        runtime.entry,
        subentry,
        data={**subentry.data, "assignees": ["person.alice"]},
    )
    await runtime.coordinator.async_refresh()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "reassign_task",
            {
                "entity_id": [
                    runtime.entities[("task-a", "due")],
                    runtime.entities[("task-b", "due")],
                ],
                "assignee": "person.bob",
            },
            blocking=True,
        )
    assert runtime.store.get_runtime_state("task-a")["current_assignee"] == "person.alice"


@pytest.mark.parametrize(
    "frequency",
    [0, -1, 366, 1.5, True, "1.5", 0.0, 366.0, float("nan"), float("inf"), float("-inf")],
)
def test_add_schema_rejects_invalid_frequency(frequency):
    with pytest.raises(vol.Invalid):
        ADD_TASK_SCHEMA({"title": "Task", "frequency_type": "daily", "frequency_value": frequency})


@pytest.mark.parametrize("frequency", [1, 365, "2"])
def test_add_schema_accepts_integral_frequency(frequency):
    result = ADD_TASK_SCHEMA(
        {"title": "Task", "frequency_type": "daily", "frequency_value": frequency}
    )
    assert result["frequency_value"] == int(frequency)


@pytest.mark.parametrize("frequency", [1, 365])
async def test_add_action_accepts_frequency_from_real_number_selector(
    hass,
    housework_runtime,
    frequency,
):
    """HA action forms send integral frequencies as floats through NumberSelector."""
    selected = NumberSelector({"min": 1, "max": 365, "mode": "box"})(frequency)
    assert isinstance(selected, float)
    await hass.services.async_call(
        DOMAIN,
        "add_task",
        {"title": "From action form", "frequency_type": "daily", "frequency_value": selected},
        blocking=True,
    )
    task = next(
        subentry
        for subentry in housework_runtime.entry.subentries.values()
        if subentry.title == "From action form"
    )
    assert task.data["frequency_value"] == frequency
    assert isinstance(task.data["frequency_value"], int)


@pytest.mark.parametrize("title", ["", " ", "\t\n"])
@pytest.mark.parametrize("schema", [ADD_TASK_SCHEMA, UPDATE_TASK_SCHEMA])
def test_task_schemas_reject_blank_titles(schema, title):
    data = {"title": title}
    if schema is ADD_TASK_SCHEMA:
        data["frequency_type"] = "daily"
    with pytest.raises(vol.Invalid):
        schema(data)


@pytest.mark.parametrize("schema", [ADD_TASK_SCHEMA, UPDATE_TASK_SCHEMA])
def test_task_schemas_trim_title(schema):
    data = {"title": "  Clean kitchen  "}
    if schema is ADD_TASK_SCHEMA:
        data["frequency_type"] = "daily"
    assert schema(data)["title"] == "Clean kitchen"


@pytest.mark.parametrize("data", [{}, {"entity_id": "sensor.missing"}, {"area_id": "missing"}])
async def test_missing_target_rejects_without_mutation(hass, housework_runtime, data):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "complete_task", data, blocking=True)
    assert housework_runtime.store.get_history() == []


@pytest.mark.parametrize("via_button", [False, True])
async def test_rapid_completions_use_current_assignment(hass, housework_runtime, via_button):
    """Coordinator refresh debouncing must not repeat a stale assignee."""
    runtime = housework_runtime
    button = HouseworkMarkDoneButton(runtime.coordinator, runtime.coordinator.data["task-a"])
    button.hass = hass
    for _ in range(3):
        if via_button:
            await button.async_press()
        else:
            await hass.services.async_call(
                DOMAIN,
                "complete_task",
                {"entity_id": runtime.entities[("task-a", "due")]},
                blocking=True,
            )
    assert runtime.store.get_assignment_state("task-a")["completion_counts"] == {
        "person.alice": 2,
        "person.bob": 1,
    }
    assert runtime.store.get_runtime_state("task-a")["current_assignee"] == "person.bob"


@pytest.mark.parametrize("via_button", [False, True])
async def test_completed_once_task_cannot_be_completed_twice(hass, housework_runtime, via_button):
    runtime = housework_runtime
    subentry = runtime.entry.subentries["task-a"]
    hass.config_entries.async_update_subentry(
        runtime.entry,
        subentry,
        data={**subentry.data, "frequency_type": FrequencyType.ONCE},
    )
    await runtime.coordinator.async_refresh()
    button = HouseworkMarkDoneButton(runtime.coordinator, runtime.coordinator.data["task-a"])
    button.hass = hass
    for _ in range(2):
        if via_button:
            await button.async_press()
        else:
            await hass.services.async_call(
                DOMAIN,
                "complete_task",
                {"entity_id": runtime.entities[("task-a", "due")]},
                blocking=True,
            )
    assert len(runtime.store.get_history("task-a")) == 1
    assert runtime.store.get_assignment_state("task-a")["completion_counts"] == {"person.alice": 1}


async def test_completion_preserves_event_and_assignment(hass, housework_runtime):
    runtime = housework_runtime
    events = []
    hass.bus.async_listen("housework_task_completed", events.append)
    button = HouseworkMarkDoneButton(runtime.coordinator, runtime.coordinator.data["task-a"])
    button.hass = hass
    await button.async_press()
    await hass.async_block_till_done()
    assert len(events) == 1
    state = runtime.store.get_runtime_state("task-a")
    assert events[0].data == {
        "task_id": "task-a",
        "title": "task-a",
        "completed_by": "person.alice",
        "next_due": state["next_due"],
    }
    record = runtime.store.get_history("task-a")[0]
    assert record.completed_by == "person.alice"
    assert record.action == "completed"
    assert record.completed_at == state["last_completed"]
    assert state["current_assignee"] == "person.bob"
