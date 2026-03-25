"""Storage layer for the Housework integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import CompletionRecord, Label, Task

_LOGGER = logging.getLogger(__name__)


class HouseworkStore:
    """Manage persistent storage for housework tasks."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._tasks: dict[str, Task] = {}
        self._history: list[CompletionRecord] = []
        self._labels: dict[str, Label] = {}
        self._assignment_state: dict[str, dict] = {}

    async def async_load(self) -> None:
        """Load data from storage."""
        data = await self._store.async_load()
        if data is None:
            return

        for task_data in data.get("tasks", {}).values():
            task = Task.from_dict(task_data)
            self._tasks[task.id] = task

        for record_data in data.get("history", []):
            self._history.append(CompletionRecord.from_dict(record_data))

        for label_data in data.get("labels", {}).values():
            label = Label.from_dict(label_data)
            self._labels[label.id] = label

        self._assignment_state = data.get("assignment_state", {})

    async def _async_save(self) -> None:
        """Save data to storage."""
        data = {
            "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
            "history": [r.to_dict() for r in self._history],
            "labels": {lid: l.to_dict() for lid, l in self._labels.items()},
            "assignment_state": self._assignment_state,
        }
        await self._store.async_save(data)

    # --- Tasks ---

    def get_all_tasks(self) -> dict[str, Task]:
        """Return all tasks."""
        return dict(self._tasks)

    def get_task(self, task_id: str) -> Task | None:
        """Return a task by ID."""
        return self._tasks.get(task_id)

    def get_task_by_entity_unique_id(self, unique_id: str) -> Task | None:
        """Return a task by its entity unique_id (housework_{task_id})."""
        prefix = "housework_"
        if unique_id.startswith(prefix):
            task_id = unique_id[len(prefix):]
            return self._tasks.get(task_id)
        return None

    async def async_add_task(self, task: Task) -> Task:
        """Add a new task."""
        self._tasks[task.id] = task
        await self._async_save()
        return task

    async def async_update_task(self, task_id: str, updates: dict) -> Task | None:
        """Update a task with partial data."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
        await self._async_save()
        return task

    async def async_remove_task(self, task_id: str) -> bool:
        """Remove a task."""
        if task_id not in self._tasks:
            return False
        del self._tasks[task_id]
        # Clean up assignment state
        self._assignment_state.pop(task_id, None)
        await self._async_save()
        return True

    # --- History ---

    def get_history(
        self,
        task_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompletionRecord]:
        """Return completion history, optionally filtered by task."""
        records = self._history
        if task_id:
            records = [r for r in records if r.task_id == task_id]
        # Most recent first
        records = sorted(records, key=lambda r: r.completed_at, reverse=True)
        return records[offset : offset + limit]

    async def async_add_history(self, record: CompletionRecord) -> None:
        """Add a completion record."""
        self._history.append(record)
        await self._async_save()

    # --- Labels ---

    def get_all_labels(self) -> dict[str, Label]:
        """Return all labels."""
        return dict(self._labels)

    def get_label(self, label_id: str) -> Label | None:
        """Return a label by ID."""
        return self._labels.get(label_id)

    async def async_add_label(self, label: Label) -> Label:
        """Add a new label."""
        self._labels[label.id] = label
        await self._async_save()
        return label

    async def async_update_label(self, label_id: str, updates: dict) -> Label | None:
        """Update a label."""
        label = self._labels.get(label_id)
        if label is None:
            return None
        for key, value in updates.items():
            if hasattr(label, key):
                setattr(label, key, value)
        await self._async_save()
        return label

    async def async_remove_label(self, label_id: str) -> bool:
        """Remove a label."""
        if label_id not in self._labels:
            return False
        del self._labels[label_id]
        await self._async_save()
        return True

    # --- Assignment State ---

    def get_assignment_state(self, task_id: str) -> dict:
        """Return assignment state for a task."""
        return self._assignment_state.get(task_id, {})

    async def async_update_assignment_state(
        self, task_id: str, state: dict
    ) -> None:
        """Update assignment state for a task."""
        self._assignment_state[task_id] = state
        await self._async_save()
