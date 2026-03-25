"""Scheduling engine for calculating next due dates."""

from __future__ import annotations

import calendar as cal_mod
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
        if task.next_due:
            return date.fromisoformat(task.next_due)
        return today

    # Determine the base date for calculation
    if task.scheduling_mode == SchedulingMode.ROLLING:
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
        return date.today()

    current_due = date.fromisoformat(task.next_due)
    return advance_one_period(current_due, task)


def calculate_initial_due(
    task: Task,
    reference_date: date | None = None,
) -> date:
    """Calculate the initial next_due when a task is first created."""
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
            return _next_matching_weekday(
                base + timedelta(days=1),
                task.frequency_days_of_week,
            )
        return base + timedelta(days=1)

    # Fallback (once or unknown)
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
    return cal_mod.monthrange(year, month)[1]


def _next_matching_weekday(from_date: date, weekdays: list[int]) -> date:
    """Find the next date on or after from_date matching one of the weekdays.

    Weekdays: 0=Monday, 6=Sunday (Python convention).
    """
    if not weekdays:
        return from_date

    for offset in range(7):
        candidate = from_date + timedelta(days=offset)
        if candidate.weekday() in weekdays:
            return candidate

    return from_date


def format_frequency(task: Task, translations: dict | None = None) -> str:
    """Return a human-readable frequency string for a task."""
    t = translations or {}
    freq = task.frequency_type
    value = task.frequency_value

    if freq == FrequencyType.ONCE:
        return t.get("once", "Once")

    if freq == FrequencyType.DAILY:
        if value == 1:
            return t.get("daily", "Daily")
        template = t.get("every_n_days", "Every {n} days")
        return template.format(n=value)

    if freq == FrequencyType.WEEKLY:
        if value == 1:
            return t.get("weekly", "Weekly")
        template = t.get("every_n_weeks", "Every {n} weeks")
        return template.format(n=value)

    if freq == FrequencyType.MONTHLY:
        if value == 1:
            suffix = ""
            if task.frequency_day_of_month:
                day_template = t.get("day_suffix", " (day {day})")
                suffix = day_template.format(day=task.frequency_day_of_month)
            return t.get("monthly", "Monthly") + suffix
        template = t.get("every_n_months", "Every {n} months")
        return template.format(n=value)

    if freq == FrequencyType.DAY_OF_WEEK:
        day_names_default = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_names = t.get("day_names", day_names_default)
        days = [day_names[d] for d in sorted(task.frequency_days_of_week) if 0 <= d <= 6]
        if days:
            template = t.get("every_days", "Every {days}")
            return template.format(days=", ".join(days))
        return t.get("weekly", "Weekly")

    return t.get("unknown", "Unknown")
