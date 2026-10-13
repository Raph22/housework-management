"""Shared task actions for Housework entities and services."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import NamedTuple

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .assignment import determine_next_assignee, update_assignment_state
from .const import DOMAIN, CompletionAction, FrequencyType
from .coordinator import HouseworkCoordinator
from .models import CompletionRecord, Task
from .scheduling import calculate_next_due
from .store import HouseworkStore

_LOGGER = logging.getLogger(__name__)


class TaskCompletion(NamedTuple):
    """An occurrence whose next due date was validated before any write."""

    task: Task
    completed_by: str
    completed_at: str
    next_due: str | None


def prepare_task_completion(
    task: Task,
    store: HouseworkStore,
    *,
    completed_by: str | None = None,
    completed_at: datetime | str | None = None,
) -> TaskCompletion | None:
    """Validate and calculate a completion without changing history or state."""
    runtime = store.get_runtime_state(task.id)
    # A requested coordinator refresh can be debounced. Use persisted values
    # when several occurrences are completed before the next refresh.
    task = replace(
        task,
        **{
            key: runtime[key]
            for key in ("next_due", "last_completed", "current_assignee")
            if key in runtime
        },
    )
    if task.frequency_type == FrequencyType.ONCE and task.next_due is None:
        return None

    if completed_by is None:
        completed_by = task.current_assignee or ""
    if completed_at is None:
        completed_at = datetime.now(timezone.utc)
    completed_at_str = completed_at if isinstance(completed_at, str) else completed_at.isoformat()

    try:
        next_due = (
            calculate_next_due(task, last_completed_override=completed_at_str)
            if task.frequency_type != FrequencyType.ONCE
            else None
        )
    except (ValueError, OverflowError) as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_task_configuration",
            translation_placeholders={"title": task.title},
        ) from err
    return TaskCompletion(
        task,
        completed_by,
        completed_at_str,
        next_due.isoformat() if next_due else None,
    )


async def async_apply_task_completion(
    hass: HomeAssistant,
    completion: TaskCompletion,
    store: HouseworkStore,
    coordinator: HouseworkCoordinator,
) -> None:
    """Apply one validated completion, preserving history, rotation and event."""
    task, completed_by, completed_at_str, next_due = completion
    runtime_updates = {
        "last_completed": completed_at_str,
        "next_due": next_due,
        "current_assignee": task.current_assignee,
    }
    await store.async_add_history(
        CompletionRecord(
            task_id=task.id,
            completed_by=completed_by,
            completed_at=completed_at_str,
            action=CompletionAction.COMPLETED,
        )
    )

    if completed_by and task.assignees:
        state = update_assignment_state(store.get_assignment_state(task.id), completed_by)
        runtime_updates["current_assignee"] = determine_next_assignee(task, state)
        await store.async_update_assignment_state(task.id, state)

    await store.async_update_runtime_state(task.id, runtime_updates)
    await coordinator.async_request_refresh()
    hass.bus.async_fire(
        "housework_task_completed",
        {
            "task_id": task.id,
            "title": task.title,
            "completed_by": completed_by,
            "next_due": runtime_updates["next_due"],
        },
    )
    _LOGGER.info("Completed task: %s by %s", task.title, completed_by)


async def async_complete_task(
    hass: HomeAssistant,
    task: Task,
    store: HouseworkStore,
    coordinator: HouseworkCoordinator,
    *,
    completed_by: str | None = None,
    completed_at: datetime | str | None = None,
) -> None:
    """Prepare and apply a single completion, used by the task button."""
    completion = prepare_task_completion(
        task,
        store,
        completed_by=completed_by,
        completed_at=completed_at,
    )
    if completion is not None:
        await async_apply_task_completion(hass, completion, store, coordinator)
