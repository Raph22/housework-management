"""Assignment engine for determining task assignees."""

from __future__ import annotations

import random

from .const import AssignmentStrategy
from .models import Task


def determine_next_assignee(
    task: Task,
    assignment_state: dict,
    completed_by: str | None = None,
) -> str | None:
    """Determine who should be assigned to the next occurrence of a task.

    Args:
        task: The task being assigned.
        assignment_state: Persistent state dict with 'last_assignee' and 'completion_counts'.
        completed_by: Who just completed the task (if applicable).

    Returns:
        The person entity_id of the next assignee, or None if no assignees.
    """
    if not task.assignees:
        return None

    if len(task.assignees) == 1:
        return task.assignees[0]

    strategy = task.assignment_strategy

    if strategy == AssignmentStrategy.FIXED:
        return task.assignees[0]

    if strategy == AssignmentStrategy.ROUND_ROBIN:
        last = assignment_state.get("last_assignee")
        if last in task.assignees:
            idx = task.assignees.index(last)
            return task.assignees[(idx + 1) % len(task.assignees)]
        return task.assignees[0]

    if strategy == AssignmentStrategy.LEAST_COMPLETED:
        counts = assignment_state.get("completion_counts", {})
        return min(
            task.assignees,
            key=lambda p: counts.get(p, 0),
        )

    if strategy == AssignmentStrategy.RANDOM:
        return random.choice(task.assignees)

    return task.assignees[0]


def update_assignment_state(
    assignment_state: dict,
    completed_by: str,
) -> dict:
    """Update assignment state after a task completion.

    Args:
        assignment_state: Current state dict (mutated and returned).
        completed_by: Who completed the task.

    Returns:
        The updated state dict.
    """
    assignment_state["last_assignee"] = completed_by
    counts = assignment_state.setdefault("completion_counts", {})
    counts[completed_by] = counts.get(completed_by, 0) + 1
    return assignment_state
