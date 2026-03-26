"""Scheduling engine for calculating next due dates."""

from __future__ import annotations

import calendar as cal_mod
from datetime import date, timedelta

from homeassistant.util import dt as dt_util

from .const import FrequencyType, SchedulingMode
from .models import Task


def _ha_today() -> date:
    """Return today's date in the HA-configured timezone."""
    return dt_util.now().date()


def calculate_next_due(
    task: Task,
    reference_date: date | None = None,
    last_completed_override: str | None = None,
) -> date | None:
    """Calculate the next due date for a task after completion.

    Args:
        task: The task to calculate for.
        reference_date: Override for "today" (useful for testing).
        last_completed_override: Use this instead of task.last_completed
            (avoids mutating the task object).

    Returns:
        The next due date, or None for once tasks that are done.
    """
    today = reference_date or _ha_today()
    last_completed = last_completed_override or task.last_completed

    if task.frequency_type == FrequencyType.ONCE:
        if task.next_due:
            return date.fromisoformat(task.next_due)
        return today

    # Determine the base date for calculation
    if task.scheduling_mode == SchedulingMode.ROLLING:
        if last_completed:
            base = date.fromisoformat(last_completed[:10])
        else:
            return today
    else:
        # Fixed: from the previous next_due, advancing forward
        if task.next_due:
            base = date.fromisoformat(task.next_due)
        elif last_completed:
            base = date.fromisoformat(last_completed[:10])
        else:
            return today

    next_due = advance_one_period(base, task)

    # For fixed scheduling: advance past today if in the past
    if task.scheduling_mode == SchedulingMode.FIXED:
        while next_due < today:
            next_due = advance_one_period(next_due, task)

    return next_due


def calculate_next_due_after_skip(task: Task) -> date | None:
    """Calculate the next due date when a task is skipped.

    Unlike complete, skip advances from the current next_due date
    rather than from last_completed, regardless of scheduling mode.
    """
    if task.frequency_type == FrequencyType.ONCE:
        return None

    if not task.next_due:
        return _ha_today()

    current_due = date.fromisoformat(task.next_due)
    return advance_one_period(current_due, task)


def calculate_initial_due(
    task: Task,
    reference_date: date | None = None,
) -> date:
    """Calculate the initial next_due when a task is first created."""
    today = reference_date or _ha_today()

    if task.frequency_type == FrequencyType.ONCE:
        if task.next_due:
            return date.fromisoformat(task.next_due)
        return today

    if task.frequency_type == FrequencyType.DAY_OF_WEEK:
        if task.frequency_days_of_week:
            return _next_matching_weekday(today, task.frequency_days_of_week)
        return today

    if task.frequency_type == FrequencyType.MONTHLY and task.frequency_day_of_month:
        try:
            candidate = today.replace(day=min(
                task.frequency_day_of_month,
                _days_in_month(today.year, today.month),
            ))
        except ValueError:
            candidate = today
        if candidate < today:
            candidate = _add_months(candidate, 1)
            candidate = candidate.replace(day=min(
                task.frequency_day_of_month,
                _days_in_month(candidate.year, candidate.month),
            ))
        return candidate

    return today


def advance_one_period(base: date, task: Task) -> date:
    """Advance a date by one period of the task's frequency."""
    freq = task.frequency_type
    value = task.frequency_value

    if freq == FrequencyType.DAILY:
        return base + timedelta(days=value)

    if freq == FrequencyType.WEEKLY:
        return base + timedelta(weeks=value)

    if freq == FrequencyType.MONTHLY:
        result = _add_months(base, value)
        if task.frequency_day_of_month:
            result = result.replace(day=min(
                task.frequency_day_of_month,
                _days_in_month(result.year, result.month),
            ))
        return result

    if freq == FrequencyType.DAY_OF_WEEK:
        if task.frequency_days_of_week:
            next_day = _next_matching_weekday(
                base + timedelta(days=1),
                task.frequency_days_of_week,
            )
            # frequency_value > 1 means "every Nth week". Only add extra
            # weeks when we've wrapped past the last selected day in the
            # week (i.e., the next matching day is in a new week).
            if value > 1 and next_day.isocalendar()[1] != base.isocalendar()[1]:
                next_day += timedelta(weeks=value - 1)
            return next_day
        return base + timedelta(days=1)

    # Fallback (once or unknown)
    return base + timedelta(days=1)


def fast_forward_to(base: date, task: Task, target: date) -> date:
    """Advance base date forward until it reaches or passes target.

    Uses bulk calculation for daily/weekly/monthly to avoid looping.
    """
    if task.frequency_type == FrequencyType.ONCE:
        return base

    if base >= target:
        return base

    freq = task.frequency_type
    value = task.frequency_value

    # For simple periodic types, calculate how many periods to skip
    if freq == FrequencyType.DAILY and value > 0:
        days_gap = (target - base).days
        periods = max(0, days_gap // value - 1)
        base = base + timedelta(days=periods * value)
    elif freq == FrequencyType.WEEKLY and value > 0:
        days_gap = (target - base).days
        periods = max(0, days_gap // (7 * value) - 1)
        base = base + timedelta(weeks=periods * value)

    # Final fine-grained advancement
    count = 0
    while base < target and count < 200:
        base = advance_one_period(base, task)
        count += 1

    return base


def format_frequency(task: Task) -> str:
    """Return a human-readable frequency string for a task (English)."""
    freq = task.frequency_type
    value = task.frequency_value

    if freq == FrequencyType.ONCE:
        return "Once"

    if freq == FrequencyType.DAILY:
        if value == 1:
            return "Daily"
        return f"Every {value} days"

    if freq == FrequencyType.WEEKLY:
        if value == 1:
            return "Weekly"
        return f"Every {value} weeks"

    if freq == FrequencyType.MONTHLY:
        if value == 1:
            suffix = ""
            if task.frequency_day_of_month:
                suffix = f" (day {task.frequency_day_of_month})"
            return f"Monthly{suffix}"
        return f"Every {value} months"

    if freq == FrequencyType.DAY_OF_WEEK:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = [day_names[d] for d in sorted(task.frequency_days_of_week) if 0 <= d <= 6]
        if days:
            days_str = ", ".join(days)
            if value > 1:
                return f"Every {days_str} (every {value} weeks)"
            return f"Every {days_str}"
        return "Weekly"

    return "Unknown"


def _add_months(d: date, months: int) -> date:
    """Add N months to a date, handling end-of-month edge cases."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in a given month."""
    return cal_mod.monthrange(year, month)[1]


def _next_matching_weekday(from_date: date, weekdays: list[int]) -> date:
    """Find the next date on or after from_date matching one of the weekdays."""
    if not weekdays:
        return from_date

    for offset in range(7):
        candidate = from_date + timedelta(days=offset)
        if candidate.weekday() in weekdays:
            return candidate

    return from_date
