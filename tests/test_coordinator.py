"""Regression tests for schedule reconciliation on task reconfiguration."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.housework.const import DOMAIN, FrequencyType, SchedulingMode
from custom_components.housework.coordinator import (
    HouseworkCoordinator,
    _resolve_reconfigured_next_due,
    _scheduling_signature,
)
from custom_components.housework.store import HouseworkStore


@pytest.mark.parametrize("completed_at", ["2026-10-12T12:00:00+00:00", None])
@pytest.mark.parametrize(
    "changed_field, new_value", [("frequency_value", 2), ("scheduling_mode", SchedulingMode.FIXED)]
)
def test_finished_once_task_stays_inactive_when_schedule_options_change(
    completed_at, changed_field, new_value, monkeypatch
):
    """Both completed and skipped one-time tasks preserve their terminal state."""
    monkeypatch.setattr(
        dt_util, "now", lambda: datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("Europe/Paris"))
    )
    old_data = {
        "frequency_type": FrequencyType.ONCE,
        "frequency_value": 1,
        "next_due": "2026-10-12",
    }
    new_data = {**old_data, changed_field: new_value}
    runtime = {"next_due": None, "last_completed": completed_at}

    assert (
        _resolve_reconfigured_next_due(new_data, runtime, _scheduling_signature(old_data)) is None
    )


def test_recurring_task_converted_to_once_keeps_existing_due(monkeypatch):
    """Changing frequency to once must retain the already scheduled occurrence."""
    monkeypatch.setattr(
        dt_util, "now", lambda: datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("Europe/Paris"))
    )
    old_data = {"frequency_type": FrequencyType.WEEKLY, "frequency_value": 1}
    new_data = {**old_data, "frequency_type": FrequencyType.ONCE}
    runtime = {"next_due": "2026-10-20", "last_completed": None}

    assert (
        _resolve_reconfigured_next_due(new_data, runtime, _scheduling_signature(old_data))
        == "2026-10-20"
    )


def test_finished_once_task_can_receive_explicit_new_due():
    old_data = {"frequency_type": FrequencyType.ONCE, "next_due": "2026-10-12"}
    new_data = {**old_data, "next_due": "2026-10-20"}
    runtime = {"next_due": None, "last_completed": "2026-10-12T12:00:00+00:00"}

    assert (
        _resolve_reconfigured_next_due(new_data, runtime, _scheduling_signature(old_data))
        == "2026-10-20"
    )


@pytest.mark.parametrize("completed_at", ["2026-10-12T12:00:00+00:00", None])
def test_finished_once_task_can_be_converted_to_recurring(completed_at, monkeypatch):
    monkeypatch.setattr(
        dt_util, "now", lambda: datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("Europe/Paris"))
    )
    old_data = {"frequency_type": FrequencyType.ONCE, "frequency_value": 1}
    new_data = {**old_data, "frequency_type": FrequencyType.WEEKLY}
    runtime = {"next_due": None, "last_completed": completed_at}

    expected = "2026-10-19" if completed_at else "2026-10-13"
    assert (
        _resolve_reconfigured_next_due(new_data, runtime, _scheduling_signature(old_data))
        == expected
    )


@pytest.mark.parametrize("completed_at", ["2026-10-12T12:00:00+00:00", None])
async def test_coordinator_persists_terminal_once_state_after_reconfigure(hass, completed_at):
    """The real coordinator/store path retains completion and reconciles its signature."""
    task_data = {
        "title": "Clean the oven",
        "frequency_type": FrequencyType.ONCE,
        "frequency_value": 1,
        "next_due": "2026-10-12",
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        subentries_data=[
            {
                "subentry_id": "oven",
                "subentry_type": "task",
                "title": task_data["title"],
                "data": task_data,
            }
        ],
    )
    entry.add_to_hass(hass)
    store = HouseworkStore(hass)
    coordinator = HouseworkCoordinator(hass, store, entry)
    try:
        tasks = await coordinator._async_update_data()
        assert tasks["oven"].next_due == "2026-10-12"

        await store.async_update_runtime_state(
            "oven", {"next_due": None, "last_completed": completed_at}
        )
        updated_data = {**task_data, "frequency_value": 2}
        hass.config_entries.async_update_subentry(
            entry, entry.subentries["oven"], data=updated_data
        )
        tasks = await coordinator._async_update_data()
        assert tasks["oven"].next_due is None
        assert store.get_runtime_state("oven")["scheduling_signature"] == _scheduling_signature(
            updated_data
        )
        assert (await coordinator._async_update_data())["oven"].next_due is None
    finally:
        await store.async_save()
