"""Scheduling engine for calculating next due dates."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from .const import FrequencyType, SchedulingMode
from .models import Task


def calculate_next_due(
    task: Task,
    reference_date: date | None = None,
) -> date | None:
    """Calculate the next due date for a task after completion.

    Args:
        task: The task to calculate for.
        reference_date: Override for "today" (useful for testing).

    Returns:
        The next due date, or None for disabled/once tasks with no date.
    """
    today = reference_date or date.today()

    if task.frequency_type == FrequencyType.ONCE:
        # One-time tasks: next_due is set manually, no recalculation
        if task.next_due:
            return date.fromisoformat(task.next_due)
        return today

    # Determine the base date for calculation
    if task.scheduling_mode == SchedulingMode.ROLLING:
        # Rolling: from last completion
        if task.last_completed:
            base = date.fromisoformat(task.last_completed[:10])
        else:
            return today
    else:
        # Fixed: from the previous next_due, advancing forward
        if task.next_due:
            base = date.fromisoformat(task.next_due)
        elif task.last_completed:
            base = date.fromisoformat(task.last_completed[:10])
        else:
            return today

    next_due = _advance_one_period(base, task)

    # For fixed scheduling: advance past today if in the past
    if task.scheduling_mode == SchedulingMode.FIXED:
        while next_due < today:
            next_due = _advance_one_period(next_due, task)

    return next_due


def calculate_initial_due(
    task: Task,
    reference_date: date | None = None,
) -> date:
    """Calculate the initial next_due when a task is first created.

    Args:
        task: The newly created task.
        reference_date: Override for "today".

    Returns:
        The first due date.
    """
    today = reference_date or date.today()

    if task.frequency_type == FrequencyType.ONCE:
        if task.next_due:
            return date.fromisoformat(task.next_due)
        return today

    if task.frequency_type == FrequencyType.DAY_OF_WEEK:
        if task.frequency_days_of_week:
            return _next_matching_weekday(today, task.frequency_days_of_week)
        return today

    if task.frequency_type == FrequencyType.MONTHLY and task.frequency_day_of_month:
        # Next occurrence of this day-of-month
        try:
            candidate = today.replace(day=min(
                task.frequency_day_of_month,
                _days_in_month(today.year, today.month),
            ))
        except ValueError:
            candidate = today
        if candidate <= today:
            candidate = _add_months(candidate, 1)
            candidate = candidate.replace(day=min(
                task.frequency_day_of_month,
                _days_in_month(candidate.year, candidate.month),
            ))
        return candidate

    # Default: due today
    return today


def _advance_one_period(base: date, task: Task) -> date:
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
            return _next_matching_weekday(
                base + timedelta(days=1),
                task.frequency_days_of_week,
            )
        return base + timedelta(days=1)

    if freq == FrequencyType.CUSTOM_DAYS:
        return base + timedelta(days=value)

    if freq == FrequencyType.CUSTOM_WEEKS:
        return base + timedelta(weeks=value)

    if freq == FrequencyType.CUSTOM_MONTHS:
        return _add_months(base, value)

    # Fallback
    return base + timedelta(days=1)


def _add_months(d: date, months: int) -> date:
    """Add N months to a date, handling end-of-month edge cases."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in a given month."""
    return calendar.monthrange(year, month)[1]


def _next_matching_weekday(from_date: date, weekdays: list[int]) -> date:
    """Find the next date on or after from_date that matches one of the weekdays.

    Weekdays: 0=Monday, 6=Sunday (Python convention).
    """
    if not weekdays:
        return from_date

    for offset in range(7):
        candidate = from_date + timedelta(days=offset)
        if candidate.weekday() in weekdays:
            return candidate

    # Should never reach here if weekdays is valid
    return from_date


def format_frequency(task: Task) -> str:
    """Return a human-readable frequency string for a task."""
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
        return f"Every {', '.join(days)}" if days else "Weekly"

    if freq == FrequencyType.CUSTOM_DAYS:
        return f"Every {value} days"

    if freq == FrequencyType.CUSTOM_WEEKS:
        return f"Every {value} weeks"

    if freq == FrequencyType.CUSTOM_MONTHS:
        return f"Every {value} months"

    return "Unknown"
