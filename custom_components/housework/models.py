"""Data models for the Housework integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .const import (
    DEFAULT_ASSIGNMENT_STRATEGY,
    DEFAULT_FREQUENCY_VALUE,
    DEFAULT_ICON,
    DEFAULT_PRIORITY,
    DEFAULT_SCHEDULING_MODE,
    CompletionAction,
    FrequencyType,
)


def _new_id() -> str:
    return uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    """A housework task (merged from subentry config + runtime state)."""

    id: str = field(default_factory=_new_id)
    title: str = ""
    description: str = ""
    priority: int = DEFAULT_PRIORITY

    # Scheduling
    frequency_type: str = FrequencyType.WEEKLY
    frequency_value: int = DEFAULT_FREQUENCY_VALUE
    frequency_days_of_week: list[int] = field(default_factory=list)
    frequency_day_of_month: int | None = None
    scheduling_mode: str = DEFAULT_SCHEDULING_MODE

    # Assignment
    assignees: list[str] = field(default_factory=list)
    assignment_strategy: str = DEFAULT_ASSIGNMENT_STRATEGY
    current_assignee: str | None = None

    # State (runtime, stored in HouseworkStore)
    last_completed: str | None = None
    next_due: str | None = None
    created_at: str = field(default_factory=_now_iso)

    # Metadata
    labels: list[str] = field(default_factory=list)
    icon: str = DEFAULT_ICON
    enabled: bool = True

    @classmethod
    def from_subentry(
        cls,
        subentry_id: str,
        subentry_data: dict[str, Any],
        runtime_state: dict[str, Any] | None = None,
    ) -> Task:
        """Create a Task from a config subentry + optional runtime state."""
        state = runtime_state or {}
        days_of_week = subentry_data.get("frequency_days_of_week", [])
        if isinstance(days_of_week, list):
            days_of_week = [int(d) for d in days_of_week]

        return cls(
            id=subentry_id,
            title=subentry_data.get("title", ""),
            description=subentry_data.get("description", ""),
            priority=int(subentry_data.get("priority", DEFAULT_PRIORITY)),
            frequency_type=subentry_data.get("frequency_type", FrequencyType.WEEKLY),
            frequency_value=int(subentry_data.get("frequency_value", DEFAULT_FREQUENCY_VALUE)),
            frequency_days_of_week=days_of_week,
            frequency_day_of_month=subentry_data.get("frequency_day_of_month"),
            scheduling_mode=subentry_data.get("scheduling_mode", DEFAULT_SCHEDULING_MODE),
            assignees=subentry_data.get("assignees", []),
            assignment_strategy=subentry_data.get(
                "assignment_strategy", DEFAULT_ASSIGNMENT_STRATEGY
            ),
            current_assignee=state.get("current_assignee"),
            last_completed=state.get("last_completed"),
            next_due=state.get("next_due"),
            created_at=state.get("created_at", _now_iso()),
            labels=subentry_data.get("labels", []),
            icon=subentry_data.get("icon", DEFAULT_ICON),
            enabled=True,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "frequency_type": self.frequency_type,
            "frequency_value": self.frequency_value,
            "frequency_days_of_week": self.frequency_days_of_week,
            "frequency_day_of_month": self.frequency_day_of_month,
            "scheduling_mode": self.scheduling_mode,
            "assignees": self.assignees,
            "assignment_strategy": self.assignment_strategy,
            "current_assignee": self.current_assignee,
            "last_completed": self.last_completed,
            "next_due": self.next_due,
            "created_at": self.created_at,
            "labels": self.labels,
            "icon": self.icon,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        """Create from dictionary (legacy storage format)."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            priority=data.get("priority", DEFAULT_PRIORITY),
            frequency_type=data.get("frequency_type", FrequencyType.WEEKLY),
            frequency_value=data.get("frequency_value", DEFAULT_FREQUENCY_VALUE),
            frequency_days_of_week=data.get("frequency_days_of_week", []),
            frequency_day_of_month=data.get("frequency_day_of_month"),
            scheduling_mode=data.get("scheduling_mode", DEFAULT_SCHEDULING_MODE),
            assignees=data.get("assignees", []),
            assignment_strategy=data.get(
                "assignment_strategy", DEFAULT_ASSIGNMENT_STRATEGY
            ),
            current_assignee=data.get("current_assignee"),
            last_completed=data.get("last_completed"),
            next_due=data.get("next_due"),
            created_at=data.get("created_at", _now_iso()),
            labels=data.get("labels", []),
            icon=data.get("icon", DEFAULT_ICON),
            enabled=data.get("enabled", True),
        )


@dataclass
class CompletionRecord:
    """A record of a task completion, skip, or snooze."""

    id: str = field(default_factory=_new_id)
    task_id: str = ""
    completed_by: str = ""
    completed_at: str = field(default_factory=_now_iso)
    action: str = CompletionAction.COMPLETED
    notes: str = ""
    snooze_until: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "completed_by": self.completed_by,
            "completed_at": self.completed_at,
            "action": self.action,
            "notes": self.notes,
            "snooze_until": self.snooze_until,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CompletionRecord:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            task_id=data["task_id"],
            completed_by=data.get("completed_by", ""),
            completed_at=data.get("completed_at", _now_iso()),
            action=data.get("action", CompletionAction.COMPLETED),
            notes=data.get("notes", ""),
            snooze_until=data.get("snooze_until"),
        )


@dataclass
class Label:
    """A label/category for tasks."""

    id: str = field(default_factory=_new_id)
    name: str = ""
    color: str = ""
    icon: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "icon": self.icon,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Label:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            color=data.get("color", ""),
            icon=data.get("icon", ""),
        )
