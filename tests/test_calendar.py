"""Calendar projections through Home Assistant's real CalendarEvent API."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.housework.calendar import HouseworkCalendar
from custom_components.housework.const import DOMAIN, FrequencyType
from custom_components.housework.coordinator import HouseworkCoordinator
from custom_components.housework.models import Task
from custom_components.housework.store import HouseworkStore

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture(autouse=True)
async def local_timezone(hass: HomeAssistant) -> None:
    """Match the user's Home Assistant timezone."""
    await hass.config.async_set_time_zone("Europe/Paris")


def make_calendar(hass: HomeAssistant, *tasks: Task) -> HouseworkCalendar:
    """Build a real coordinator-backed calendar without loading other platforms."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coordinator = HouseworkCoordinator(hass, HouseworkStore(hass), entry)
    coordinator.async_set_updated_data({task.id: task for task in tasks})
    calendar = HouseworkCalendar(coordinator)
    calendar.hass = hass
    return calendar


async def test_range_end_is_exclusive(hass: HomeAssistant) -> None:
    """A midnight upper bound excludes the all-day event starting then."""
    calendar = make_calendar(
        hass,
        Task(id="daily", title="Sweep", frequency_type=FrequencyType.DAILY, next_due="2026-10-13"),
    )
    events = await calendar.async_get_events(
        hass, datetime(2026, 10, 13, tzinfo=PARIS), datetime(2026, 10, 14, tzinfo=PARIS)
    )
    assert [event.start for event in events] == [date(2026, 10, 13)]


async def test_range_uses_home_assistant_timezone(hass: HomeAssistant) -> None:
    """UTC bounds select all-day occurrences in the Home Assistant timezone."""
    calendar = make_calendar(
        hass,
        Task(id="once", title="Sweep", frequency_type=FrequencyType.ONCE, next_due="2026-10-14"),
    )
    events = await calendar.async_get_events(
        hass,
        datetime.fromisoformat("2026-10-13T22:30:00+00:00"),
        datetime.fromisoformat("2026-10-13T23:00:00+00:00"),
    )
    assert [event.start for event in events] == [date(2026, 10, 14)]


async def test_all_day_overlap_with_midday_bounds(hass: HomeAssistant) -> None:
    """Events crossing either midday boundary belong to the requested window."""
    calendar = make_calendar(
        hass,
        Task(id="daily", title="Sweep", frequency_type=FrequencyType.DAILY, next_due="2026-10-13"),
    )
    events = await calendar.async_get_events(
        hass, datetime(2026, 10, 13, 12, tzinfo=PARIS), datetime(2026, 10, 14, 12, tzinfo=PARIS)
    )
    assert [event.start for event in events] == [date(2026, 10, 13), date(2026, 10, 14)]
    assert all(isinstance(event, CalendarEvent) and event.all_day for event in events)


async def test_range_start_excludes_an_event_that_ended(hass: HomeAssistant) -> None:
    """An event ending exactly at the lower bound does not overlap the window."""
    calendar = make_calendar(
        hass,
        Task(id="once", title="Sweep", frequency_type=FrequencyType.ONCE, next_due="2026-10-12"),
    )
    assert not await calendar.async_get_events(
        hass, datetime(2026, 10, 13, tzinfo=PARIS), datetime(2026, 10, 14, tzinfo=PARIS)
    )


@pytest.mark.parametrize("end_hour", [12, 11])
async def test_empty_or_reversed_window_has_no_events(hass: HomeAssistant, end_hour: int) -> None:
    """Equal or reversed bounds cannot overlap an all-day occurrence."""
    calendar = make_calendar(
        hass,
        Task(id="once", title="Sweep", frequency_type=FrequencyType.ONCE, next_due="2026-10-13"),
    )
    assert not await calendar.async_get_events(
        hass,
        datetime(2026, 10, 13, 12, tzinfo=PARIS),
        datetime(2026, 10, 13, end_hour, tzinfo=PARIS),
    )


async def test_full_year_includes_every_daily_occurrence(hass: HomeAssistant) -> None:
    """Projection count follows the requested window rather than a weekly cap."""
    calendar = make_calendar(
        hass,
        Task(id="daily", title="Sweep", frequency_type=FrequencyType.DAILY, next_due="2025-01-01"),
    )
    events = await calendar.async_get_events(
        hass, datetime(2026, 1, 1, tzinfo=PARIS), datetime(2027, 1, 1, tzinfo=PARIS)
    )
    assert len(events) == 365
    assert events[0].start == date(2026, 1, 1)
    assert events[-1].start == date(2026, 12, 31)


async def test_events_sorted_and_malformed_dates_skipped(hass: HomeAssistant) -> None:
    """Bad persisted dates do not hide valid occurrences from other tasks."""
    calendar = make_calendar(
        hass,
        Task(id="late", title="Later", frequency_type=FrequencyType.ONCE, next_due="2026-10-14"),
        Task(id="bad", title="Invalid", next_due="bad-date"),
        Task(id="early", title="Earlier", frequency_type=FrequencyType.ONCE, next_due="2026-10-13"),
        Task(id="completed", title="Completed", next_due=None),
    )
    events = await calendar.async_get_events(
        hass, datetime(2026, 10, 13, tzinfo=PARIS), datetime(2026, 10, 15, tzinfo=PARIS)
    )
    assert [event.summary for event in events] == ["Earlier", "Later"]
    assert len({event.uid for event in events}) == 2


@pytest.mark.parametrize("invalid_due", ["2026-10-01", "2026-10-13"])
async def test_legacy_zero_frequency_does_not_hide_valid_tasks(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, invalid_due: str
) -> None:
    """Invalid pre-0.5 recurrence data is isolated before making any events."""
    calendar = make_calendar(
        hass,
        Task(
            id="legacy-zero",
            title="Invalid",
            frequency_type=FrequencyType.DAILY,
            frequency_value=0,
            next_due=invalid_due,
        ),
        Task(id="valid", title="Valid", frequency_type=FrequencyType.ONCE, next_due="2026-10-13"),
    )
    events = await calendar.async_get_events(
        hass, datetime(2026, 10, 13, tzinfo=PARIS), datetime(2026, 10, 14, tzinfo=PARIS)
    )
    assert [event.summary for event in events] == ["Valid"]
    assert "legacy-zero" in caplog.text


async def test_next_period_overflow_preserves_requested_occurrence(
    hass: HomeAssistant,
) -> None:
    """An unreachable next recurrence cannot discard the last valid event."""
    calendar = make_calendar(
        hass,
        Task(
            id="last",
            title="Last occurrence",
            frequency_type=FrequencyType.MONTHLY,
            frequency_value=365,
            next_due="9999-10-13",
        ),
    )
    events = await calendar.async_get_events(
        hass, datetime(9999, 10, 13, tzinfo=PARIS), datetime(9999, 10, 14, tzinfo=PARIS)
    )
    assert [event.start for event in events] == [date(9999, 10, 13)]


async def test_unrepresentable_all_day_end_does_not_hide_other_tasks(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """date.max has no following day to represent an all-day event end."""
    calendar = make_calendar(
        hass,
        Task(
            id="unrepresentable",
            title="Last day",
            frequency_type=FrequencyType.ONCE,
            next_due="9999-12-31",
        ),
        Task(id="valid", title="Valid", frequency_type=FrequencyType.ONCE, next_due="9999-12-30"),
    )
    events = await calendar.async_get_events(
        hass, datetime(9999, 12, 30, tzinfo=PARIS), datetime(9999, 12, 31, 12, tzinfo=PARIS)
    )
    assert [event.summary for event in events] == ["Valid"]
    assert "unrepresentable" in caplog.text
