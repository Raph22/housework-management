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

            # Initialize runtime state for new subentries (added via UI).
            # Skip if this is a completed once-task (has last_completed but no next_due).
            is_completed_once = (
                not runtime.get("next_due")
                and runtime.get("last_completed")
                and data.get("frequency_type") == "once"
            )
            if not runtime.get("next_due") and not is_completed_once:
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
                    task = Task.from_subentry(sid, data, runtime)
                    if task.last_completed:
                        new_due = calculate_next_due(task)
                        if new_due:
                            updates["next_due"] = new_due.isoformat()
                    else:
                        fresh_task = Task.from_subentry(sid, data)
                        updates["next_due"] = calculate_initial_due(fresh_task).isoformat()
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
