"""DataUpdateCoordinator for the Housework integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, SCHEDULING_FIELDS
from .models import Task
from .scheduling import calculate_initial_due, calculate_next_due
from .store import HouseworkStore

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=15)

SUBENTRY_TYPE_TASK = "task"


def _scheduling_signature(data: dict) -> dict:
    """Extract scheduling-relevant fields for change detection."""
    return {k: data.get(k) for k in SCHEDULING_FIELDS}


def _resolve_reconfigured_next_due(
    subentry_data: dict,
    runtime_state: dict,
    previous_signature: dict | None = None,
) -> str | None:
    """Resolve runtime next_due after a task reconfigure."""
    previous_next_due = (previous_signature or {}).get("next_due")
    explicit_next_due = subentry_data.get("next_due")

    if explicit_next_due is not None and explicit_next_due != previous_next_due:
        return explicit_next_due

    task = Task.from_subentry("reconfigured", subentry_data, runtime_state)
    if task.last_completed:
        next_due = calculate_next_due(task)
    else:
        next_due = calculate_initial_due(
            Task.from_subentry("reconfigured", subentry_data)
        )

    return next_due.isoformat() if next_due else None


class HouseworkCoordinator(DataUpdateCoordinator[dict[str, Task]]):
    """Coordinator that merges subentry config + runtime state into Task objects."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        store: HouseworkStore,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=config_entry,
        )
        self.store = store

    async def _async_update_data(self) -> dict[str, Task]:
        """Build Task objects from subentries + runtime state.

        Also reconciles runtime state when subentry config changes
        (scheduling fields or assignees).
        """
        tasks: dict[str, Task] = {}
        all_runtime = self.store.get_all_runtime_state()

        # Track which subentry IDs exist to clean up orphaned runtime state
        active_ids: set[str] = set()

        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_TASK:
                continue

            sid = subentry.subentry_id
            active_ids.add(sid)
            data = dict(subentry.data)
            runtime = all_runtime.get(sid, {})

            # Initialize runtime state only when no runtime record exists yet.
            # Completed or skipped one-shot tasks intentionally persist next_due=None.
            if sid not in all_runtime:
                task = Task.from_subentry(sid, data)
                # Use explicit next_due from subentry data if provided
                if data.get("next_due"):
                    initial_due_str = data["next_due"]
                else:
                    initial_due_str = calculate_initial_due(task).isoformat()
                runtime_updates = {
                    "next_due": initial_due_str,
                    "created_at": task.created_at,
                    "scheduling_signature": _scheduling_signature(data),
                }
                if task.assignees:
                    runtime_updates["current_assignee"] = task.assignees[0]
                await self.store.async_update_runtime_state(sid, runtime_updates)
                runtime = self.store.get_runtime_state(sid)

            else:
                # Reconcile: check if scheduling fields changed since last update
                old_sig = runtime.get("scheduling_signature", {})
                new_sig = _scheduling_signature(data)
                updates = {}

                if old_sig != new_sig:
                    updates["next_due"] = _resolve_reconfigured_next_due(
                        subentry_data=data,
                        runtime_state=runtime,
                        previous_signature=old_sig,
                    )
                    updates["scheduling_signature"] = new_sig

                # Reconcile assignee
                new_assignees = data.get("assignees", [])
                current = runtime.get("current_assignee")
                if new_assignees and (not current or current not in new_assignees):
                    updates["current_assignee"] = new_assignees[0]
                elif not new_assignees and current:
                    updates["current_assignee"] = None

                if updates:
                    await self.store.async_update_runtime_state(sid, updates)
                    runtime = self.store.get_runtime_state(sid)

            tasks[sid] = Task.from_subentry(sid, data, runtime)

        # Clean up runtime state for deleted subentries
        for orphan_id in set(all_runtime.keys()) - active_ids:
            await self.store.async_remove_runtime_state(orphan_id)

        return tasks
