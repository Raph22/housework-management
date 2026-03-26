"""Constants for the Housework integration."""

from enum import StrEnum

DOMAIN = "housework"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

MAX_HISTORY_RECORDS = 500


class FrequencyType(StrEnum):
    """Frequency types for task scheduling."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    DAY_OF_WEEK = "day_of_week"
    ONCE = "once"


class AssignmentStrategy(StrEnum):
    """Assignment strategies for task rotation."""

    ROUND_ROBIN = "round_robin"
    LEAST_COMPLETED = "least_completed"
    RANDOM = "random"
    FIXED = "fixed"


class SchedulingMode(StrEnum):
    """Scheduling modes for next due date calculation."""

    ROLLING = "rolling"
    FIXED = "fixed"


class CompletionAction(StrEnum):
    """Actions that can be recorded in completion history."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    SNOOZED = "snoozed"


DEFAULT_ICON = "mdi:broom"
DEFAULT_PRIORITY = 3
DEFAULT_FREQUENCY_VALUE = 1
DEFAULT_SCHEDULING_MODE = SchedulingMode.ROLLING
DEFAULT_ASSIGNMENT_STRATEGY = AssignmentStrategy.ROUND_ROBIN

SCHEDULING_FIELDS = frozenset({
    "frequency_type",
    "frequency_value",
    "frequency_days_of_week",
    "frequency_day_of_month",
    "scheduling_mode",
    "next_due",
})

FREQUENCY_TYPES = [ft.value for ft in FrequencyType]
ASSIGNMENT_STRATEGIES = [s.value for s in AssignmentStrategy]
SCHEDULING_MODES = [m.value for m in SchedulingMode]
