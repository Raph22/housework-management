"""Storage layer for the Housework integration (runtime state only).

Task definitions are stored in config subentries. This store holds:
- Runtime state per task (last_completed, next_due, current_assignee)
- Completion history
- Labels
- Assignment state (rotation tracking)
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import MAX_HISTORY_RECORDS, STORAGE_KEY, STORAGE_VERSION
from .models import CompletionRecord, Label

_LOGGER = logging.getLogger(__name__)


class HouseworkStore:
    """Manage persistent runtime state for housework tasks."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._runtime_state: dict[str, dict[str, Any]] = {}
        self._history: list[CompletionRecord] = []
        self._labels: dict[str, Label] = {}
        self._assignment_state: dict[str, dict] = {}

    async def async_load(self) -> None:
        """Load data from storage."""
        data = await self._store.async_load()
        if data is None:
            return

        self._runtime_state = data.get("runtime_state", {})

        for record_data in data.get("history", []):
            self._history.append(CompletionRecord.from_dict(record_data))

        for label_data in data.get("labels", {}).values():
            label = Label.from_dict(label_data)
            self._labels[label.id] = label

        self._assignment_state = data.get("assignment_state", {})

    async def async_remove(self) -> None:
        """Remove the storage file."""
        await self._store.async_remove()

    @callback
    def _async_schedule_save(self) -> None:
        """Schedule a debounced save to storage."""
        self._store.async_delay_save(self._data_to_save, delay=1.0)

    def _data_to_save(self) -> dict[str, Any]:
        """Return data dict for storage."""
        return {
            "runtime_state": self._runtime_state,
            "history": [r.to_dict() for r in self._history],
            "labels": {lid: label.to_dict() for lid, label in self._labels.items()},
            "assignment_state": self._assignment_state,
        }

    # --- Runtime State (per task, keyed by subentry_id) ---

    def get_runtime_state(self, task_id: str) -> dict[str, Any]:
        """Return runtime state for a task."""
        return dict(self._runtime_state.get(task_id, {}))

    def get_all_runtime_state(self) -> dict[str, dict[str, Any]]:
        """Return runtime state for all tasks."""
        return dict(self._runtime_state)

    async def async_update_runtime_state(
        self, task_id: str, updates: dict[str, Any]
    ) -> None:
        """Update runtime state for a task."""
        state = self._runtime_state.setdefault(task_id, {})
        state.update(updates)
        self._async_schedule_save()

    async def async_remove_runtime_state(self, task_id: str) -> None:
        """Remove runtime state for a deleted task."""
        self._runtime_state.pop(task_id, None)
        self._assignment_state.pop(task_id, None)
        self._async_schedule_save()

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
        records = sorted(records, key=lambda r: r.completed_at, reverse=True)
        return records[offset : offset + limit]

    async def async_add_history(self, record: CompletionRecord) -> None:
        """Add a completion record, pruning old records if over the limit."""
        self._history.append(record)
        if len(self._history) > MAX_HISTORY_RECORDS:
            self._history.sort(key=lambda r: r.completed_at, reverse=True)
            self._history = self._history[:MAX_HISTORY_RECORDS]
        self._async_schedule_save()

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
        self._async_schedule_save()
        return label

    async def async_update_label(self, label_id: str, updates: dict) -> Label | None:
        """Update a label."""
        label = self._labels.get(label_id)
        if label is None:
            return None
        for key, value in updates.items():
            if key in ("name", "color", "icon"):
                setattr(label, key, value)
        self._async_schedule_save()
        return label

    async def async_remove_label(self, label_id: str) -> bool:
        """Remove a label."""
        if label_id not in self._labels:
            return False
        del self._labels[label_id]
        self._async_schedule_save()
        return True

    # --- Assignment State ---

    def get_assignment_state(self, task_id: str) -> dict:
        """Return assignment state for a task."""
        return self._assignment_state.get(task_id, {})

    def get_all_assignment_state(self) -> dict[str, dict]:
        """Return assignment state for all tasks."""
        return dict(self._assignment_state)

    async def async_update_assignment_state(
        self, task_id: str, state: dict
    ) -> None:
        """Update assignment state for a task."""
        self._assignment_state[task_id] = state
        self._async_schedule_save()
