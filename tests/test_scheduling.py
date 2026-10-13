"""Regression tests for task recurrence in the Home Assistant timezone."""

from datetime import date

import pytest

from custom_components.housework.const import FrequencyType, SchedulingMode
from custom_components.housework.models import Task
from custom_components.housework.scheduling import (
    advance_one_period,
    calculate_initial_due,
    calculate_next_due,
    calculate_next_due_after_skip,
    fast_forward_to,
)


async def test_rolling_completion_uses_local_calendar_date(hass):
    """Completing after midnight in Paris advances from the new local day."""
    await hass.config.async_set_time_zone("Europe/Paris")
    task = Task(frequency_type=FrequencyType.DAILY)

    assert calculate_next_due(
        task,
        reference_date=date(2026, 10, 13),
        last_completed_override="2026-10-12T22:30:00+00:00",
    ) == date(2026, 10, 14)


def test_fixed_late_completion_advances_past_today():
    """An overdue completion cannot leave another occurrence due today."""
    task = Task(
        frequency_type=FrequencyType.DAILY,
        scheduling_mode=SchedulingMode.FIXED,
        next_due="2026-10-11",
    )

    assert calculate_next_due(task, reference_date=date(2026, 10, 13)) == date(2026, 10, 14)


@pytest.mark.parametrize(
    "frequency",
    [FrequencyType.DAILY, FrequencyType.WEEKLY, FrequencyType.MONTHLY, FrequencyType.DAY_OF_WEEK],
)
@pytest.mark.parametrize("value", [0, -1])
def test_advancement_rejects_nonpositive_frequency(frequency, value):
    """Malformed runtime tasks cannot move backward or keep the same date."""
    task = Task(frequency_type=frequency, frequency_value=value)

    with pytest.raises(ValueError, match="frequency_value"):
        advance_one_period(date(2026, 10, 13), task)


@pytest.mark.parametrize(
    "day_of_month, expected", [(None, date(2026, 7, 28)), (15, date(2026, 7, 15))]
)
def test_monthly_fast_forward_matches_repeated_advancement(day_of_month, expected):
    """Bulk advancement preserves the same month clamping as each occurrence."""
    task = Task(
        frequency_type=FrequencyType.MONTHLY,
        frequency_day_of_month=day_of_month,
    )

    assert fast_forward_to(date(2026, 1, 31), task, date(2026, 7, 1)) == expected


def test_weekday_fast_forward_does_not_return_unselected_start_day():
    """An explicit date outside the chosen weekdays cannot become an occurrence."""
    task = Task(
        frequency_type=FrequencyType.DAY_OF_WEEK,
        frequency_value=2,
        frequency_days_of_week=[0, 2],
    )
    base = date(2026, 1, 6)  # Tuesday
    target = date(2026, 7, 7)  # Tuesday
    expected = base
    while expected < target:
        expected = advance_one_period(expected, task)

    assert fast_forward_to(base, task, target) == expected


def test_weekday_fast_forward_without_selected_days_reaches_target():
    """The daily fallback still reaches a distant target with a large interval."""
    task = Task(frequency_type=FrequencyType.DAY_OF_WEEK, frequency_value=365)
    assert fast_forward_to(date(2020, 1, 1), task, date(2026, 10, 13)) == date(2026, 10, 13)


@pytest.mark.parametrize(
    "task, today, expected",
    [
        (Task(frequency_type=FrequencyType.DAILY), date(2026, 10, 13), date(2026, 10, 13)),
        (
            Task(frequency_type=FrequencyType.MONTHLY, frequency_day_of_month=31),
            date(2026, 2, 1),
            date(2026, 2, 28),
        ),
        (
            Task(frequency_type=FrequencyType.MONTHLY, frequency_day_of_month=15),
            date(2026, 10, 20),
            date(2026, 11, 15),
        ),
        (
            Task(frequency_type=FrequencyType.DAY_OF_WEEK, frequency_days_of_week=[0, 2]),
            date(2026, 10, 13),
            date(2026, 10, 14),
        ),
        (
            Task(frequency_type=FrequencyType.ONCE, next_due="2026-11-15"),
            date(2026, 10, 13),
            date(2026, 11, 15),
        ),
    ],
)
def test_initial_due(task, today, expected):
    assert calculate_initial_due(task, reference_date=today) == expected


def test_fixed_on_time_completion_preserves_original_cadence():
    task = Task(
        frequency_type=FrequencyType.WEEKLY,
        scheduling_mode=SchedulingMode.FIXED,
        next_due="2026-10-13",
    )
    assert calculate_next_due(task, reference_date=date(2026, 10, 13)) == date(2026, 10, 20)


def test_rolling_late_completion_starts_from_completion_day():
    task = Task(
        frequency_type=FrequencyType.WEEKLY,
        scheduling_mode=SchedulingMode.ROLLING,
        next_due="2026-10-01",
        last_completed="2026-10-13T12:00:00+00:00",
    )
    assert calculate_next_due(task, reference_date=date(2026, 10, 13)) == date(2026, 10, 20)


def test_skip_overdue_task_advances_past_today():
    task = Task(frequency_type=FrequencyType.DAILY, next_due="2026-10-01")
    assert calculate_next_due_after_skip(task, reference_date=date(2026, 10, 13)) == date(
        2026, 10, 14
    )


def test_skip_once_task_finishes_it():
    task = Task(frequency_type=FrequencyType.ONCE, next_due="2026-10-01")
    assert calculate_next_due_after_skip(task, reference_date=date(2026, 10, 13)) is None


def test_monthly_day_31_recovers_after_short_month():
    task = Task(frequency_type=FrequencyType.MONTHLY, frequency_day_of_month=31)
    february = advance_one_period(date(2026, 1, 31), task)
    assert february == date(2026, 2, 28)
    assert advance_one_period(february, task) == date(2026, 3, 31)


def test_every_second_week_across_iso_year():
    task = Task(
        frequency_type=FrequencyType.DAY_OF_WEEK,
        frequency_value=2,
        frequency_days_of_week=[0, 2],
    )
    assert advance_one_period(date(2026, 12, 28), task) == date(2026, 12, 30)
    assert advance_one_period(date(2026, 12, 30), task) == date(2027, 1, 11)
