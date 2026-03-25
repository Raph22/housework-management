"""Service handlers for the Housework integration."""

from __future__ import annotations

from datetime import date, datetime, timezone
import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv

from .assignment import determine_next_assignee, update_assignment_state
from .const import (
    ASSIGNMENT_STRATEGIES,
    DOMAIN,
    FREQUENCY_TYPES,
    SCHEDULING_MODES,
    CompletionAction,
    FrequencyType,
)
from .models import CompletionRecord, Label, Task
from .scheduling import calculate_initial_due, calculate_next_due, calculate_next_due_after_skip

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_TASK = "add_task"
SERVICE_COMPLETE_TASK = "complete_task"
SERVICE_SKIP_TASK = "skip_task"
SERVICE_SNOOZE_TASK = "snooze_task"
SERVICE_REASSIGN_TASK = "reassign_task"
SERVICE_UPDATE_TASK = "update_task"
SERVICE_REMOVE_TASK = "remove_task"
SERVICE_ADD_LABEL = "add_label"
SERVICE_UPDATE_LABEL = "update_label"
SERVICE_REMOVE_LABEL = "remove_label"

ADD_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("title"): cv.string,
        vol.Required("frequency_type"): vol.In(FREQUENCY_TYPES),
        vol.Optional("frequency_value", default=1): vol.Coerce(int),
        vol.Optional("frequency_days_of_week"): vol.All(
            cv.ensure_list, [vol.Coerce(int)]
        ),
        vol.Optional("frequency_day_of_month"): vol.Coerce(int),
        vol.Optional("scheduling_mode", default="rolling"): vol.In(SCHEDULING_MODES),
        vol.Optional("priority", default=3): vol.Coerce(int),
        vol.Optional("description", default=""): cv.string,
        vol.Optional("assignees"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("assignment_strategy", default="round_robin"): vol.In(
            ASSIGNMENT_STRATEGIES
        ),
        vol.Optional("icon", default="mdi:broom"): cv.string,
        vol.Optional("next_due"): cv.string,
    }
)

ADD_LABEL_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("color", default=""): cv.string,
        vol.Optional("icon", default=""): cv.string,
    }
)

UPDATE_LABEL_SCHEMA = vol.Schema(
    {
        vol.Required("label_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("color"): cv.string,
        vol.Optional("icon"): cv.string,
    }
)

REMOVE_LABEL_SCHEMA = vol.Schema(
    {
        vol.Required("label_id"): cv.string,
    }
)


def _get_store_and_coordinator(hass: HomeAssistant):
    """Get the store and coordinator from hass.data."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if "store" in entry_data:
            return entry_data["store"], entry_data["coordinator"]
    return None, None


def _get_task_from_entity_id(hass: HomeAssistant, entity_id: str):
    """Resolve an entity_id to a task via the entity registry."""
    store, coordinator = _get_store_and_coordinator(hass)
    if store is None:
        return None, None, None

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None:
        return None, None, None

    task = store.get_task_by_entity_unique_id(entry.unique_id)
    return task, store, coordinator


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up Housework services."""
    # Guard against re-registration on reload
    if hass.services.has_service(DOMAIN, SERVICE_ADD_TASK):
        return

    async def handle_add_task(call: ServiceCall) -> None:
        """Handle the add_task service call."""
        store, coordinator = _get_store_and_coordinator(hass)
        if store is None:
            _LOGGER.error("Housework store not found")
            return

        data = call.data

        task = Task(
            title=data["title"],
            description=data.get("description", ""),
            priority=data.get("priority", 3),
            frequency_type=data["frequency_type"],
            frequency_value=data.get("frequency_value", 1),
            frequency_days_of_week=data.get("frequency_days_of_week", []),
            frequency_day_of_month=data.get("frequency_day_of_month"),
            scheduling_mode=data.get("scheduling_mode", "rolling"),
            assignees=data.get("assignees", []),
            assignment_strategy=data.get("assignment_strategy", "round_robin"),
            icon=data.get("icon", "mdi:broom"),
        )

        # Set initial due date
        if data.get("next_due"):
            task.next_due = data["next_due"]
        else:
            initial_due = calculate_initial_due(task)
            task.next_due = initial_due.isoformat()

        # Set initial assignee
        if task.assignees:
            task.current_assignee = task.assignees[0]

        await store.async_add_task(task)
        await coordinator.async_request_refresh()
        _LOGGER.info("Added task: %s", task.title)

    async def handle_complete_task(call: ServiceCall) -> None:
        """Handle the complete_task service call."""
        entity_ids = _resolve_entity_ids(call)
        for entity_id in entity_ids:
            await _complete_single_task(hass, call, entity_id)

    async def _complete_single_task(
        hass: HomeAssistant, call: ServiceCall, entity_id: str
    ) -> None:
        task, store, coordinator = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            _LOGGER.error("Task not found for entity: %s", entity_id)
            return

        completed_by = call.data.get("completed_by", task.current_assignee or "")
        completed_at = call.data.get("completed_at")
        if completed_at:
            if isinstance(completed_at, str):
                completed_at_str = completed_at
            else:
                completed_at_str = completed_at.isoformat()
        else:
            completed_at_str = datetime.now(timezone.utc).isoformat()

        # Record history
        record = CompletionRecord(
            task_id=task.id,
            completed_by=completed_by,
            completed_at=completed_at_str,
            action=CompletionAction.COMPLETED,
        )
        await store.async_add_history(record)

        # Build updates dict — don't mutate task directly
        updates: dict = {"last_completed": completed_at_str}

        # Calculate next due
        task.last_completed = completed_at_str  # needed for calculate_next_due
        if task.frequency_type != FrequencyType.ONCE:
            next_due = calculate_next_due(task)
            updates["next_due"] = next_due.isoformat() if next_due else None
        else:
            updates["next_due"] = None

        # Update assignment
        current_assignee = task.current_assignee
        if completed_by and task.assignees:
            state = store.get_assignment_state(task.id)
            state = update_assignment_state(state, completed_by)
            current_assignee = determine_next_assignee(task, state)
            await store.async_update_assignment_state(task.id, state)
        updates["current_assignee"] = current_assignee

        await store.async_update_task(task.id, updates)
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            "housework_task_completed",
            {
                "task_id": task.id,
                "title": task.title,
                "completed_by": completed_by,
                "next_due": updates["next_due"],
            },
        )

        _LOGGER.info("Completed task: %s by %s", task.title, completed_by)

    async def handle_skip_task(call: ServiceCall) -> None:
        """Handle the skip_task service call."""
        entity_ids = _resolve_entity_ids(call)
        for entity_id in entity_ids:
            await _skip_single_task(hass, entity_id)

    async def _skip_single_task(
        hass: HomeAssistant, entity_id: str
    ) -> None:
        task, store, coordinator = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            _LOGGER.error("Task not found for entity: %s", entity_id)
            return

        # Record history
        record = CompletionRecord(
            task_id=task.id,
            completed_at=datetime.now(timezone.utc).isoformat(),
            action=CompletionAction.SKIPPED,
        )
        await store.async_add_history(record)

        # Advance from current next_due (not from last_completed)
        next_due = calculate_next_due_after_skip(task)
        next_due_str = next_due.isoformat() if next_due else None

        await store.async_update_task(task.id, {"next_due": next_due_str})
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            "housework_task_skipped",
            {
                "task_id": task.id,
                "title": task.title,
                "next_due": next_due_str,
            },
        )

        _LOGGER.info("Skipped task: %s", task.title)

    async def handle_snooze_task(call: ServiceCall) -> None:
        """Handle the snooze_task service call."""
        entity_ids = _resolve_entity_ids(call)
        snooze_until = call.data["snooze_until"]
        for entity_id in entity_ids:
            await _snooze_single_task(hass, entity_id, snooze_until)

    async def _snooze_single_task(
        hass: HomeAssistant, entity_id: str, snooze_until: str
    ) -> None:
        task, store, coordinator = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            _LOGGER.error("Task not found for entity: %s", entity_id)
            return

        if isinstance(snooze_until, date):
            snooze_until = snooze_until.isoformat()

        # Record history
        record = CompletionRecord(
            task_id=task.id,
            completed_at=datetime.now(timezone.utc).isoformat(),
            action=CompletionAction.SNOOZED,
            snooze_until=snooze_until,
        )
        await store.async_add_history(record)

        await store.async_update_task(task.id, {"next_due": snooze_until})
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            "housework_task_snoozed",
            {
                "task_id": task.id,
                "title": task.title,
                "snooze_until": snooze_until,
            },
        )

        _LOGGER.info("Snoozed task: %s until %s", task.title, snooze_until)

    async def handle_reassign_task(call: ServiceCall) -> None:
        """Handle the reassign_task service call."""
        entity_ids = _resolve_entity_ids(call)
        assignee = call.data["assignee"]
        for entity_id in entity_ids:
            await _reassign_single_task(hass, entity_id, assignee)

    async def _reassign_single_task(
        hass: HomeAssistant, entity_id: str, assignee: str
    ) -> None:
        task, store, coordinator = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            _LOGGER.error("Task not found for entity: %s", entity_id)
            return

        await store.async_update_task(task.id, {"current_assignee": assignee})
        await coordinator.async_request_refresh()
        _LOGGER.info("Reassigned task: %s to %s", task.title, assignee)

    async def handle_update_task(call: ServiceCall) -> None:
        """Handle the update_task service call."""
        entity_ids = _resolve_entity_ids(call)
        for entity_id in entity_ids:
            await _update_single_task(hass, call, entity_id)

    async def _update_single_task(
        hass: HomeAssistant, call: ServiceCall, entity_id: str
    ) -> None:
        task, store, coordinator = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            _LOGGER.error("Task not found for entity: %s", entity_id)
            return

        updates = {}
        for key in ("title", "description", "icon", "enabled"):
            if key in call.data:
                updates[key] = call.data[key]
        if "priority" in call.data:
            updates["priority"] = int(call.data["priority"])

        if updates:
            await store.async_update_task(task.id, updates)
            await coordinator.async_request_refresh()
            _LOGGER.info("Updated task: %s", task.title)

    async def handle_remove_task(call: ServiceCall) -> None:
        """Handle the remove_task service call."""
        entity_ids = _resolve_entity_ids(call)
        for entity_id in entity_ids:
            await _remove_single_task(hass, entity_id)

    async def _remove_single_task(hass: HomeAssistant, entity_id: str) -> None:
        task, store, coordinator = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            _LOGGER.error("Task not found for entity: %s", entity_id)
            return

        title = task.title
        await store.async_remove_task(task.id)
        await coordinator.async_request_refresh()
        _LOGGER.info("Removed task: %s", title)

    async def handle_add_label(call: ServiceCall) -> None:
        """Handle the add_label service call."""
        store, coordinator = _get_store_and_coordinator(hass)
        if store is None:
            _LOGGER.error("Housework store not found")
            return

        label = Label(
            name=call.data["name"],
            color=call.data.get("color", ""),
            icon=call.data.get("icon", ""),
        )
        await store.async_add_label(label)
        _LOGGER.info("Added label: %s", label.name)

    async def handle_update_label(call: ServiceCall) -> None:
        """Handle the update_label service call."""
        store, coordinator = _get_store_and_coordinator(hass)
        if store is None:
            _LOGGER.error("Housework store not found")
            return

        label_id = call.data["label_id"]
        updates = {}
        for key in ("name", "color", "icon"):
            if key in call.data:
                updates[key] = call.data[key]

        if updates:
            result = await store.async_update_label(label_id, updates)
            if result is None:
                _LOGGER.error("Label not found: %s", label_id)
            else:
                _LOGGER.info("Updated label: %s", result.name)

    async def handle_remove_label(call: ServiceCall) -> None:
        """Handle the remove_label service call."""
        store, coordinator = _get_store_and_coordinator(hass)
        if store is None:
            _LOGGER.error("Housework store not found")
            return

        label_id = call.data["label_id"]
        removed = await store.async_remove_label(label_id)
        if not removed:
            _LOGGER.error("Label not found: %s", label_id)
        else:
            _LOGGER.info("Removed label: %s", label_id)

    # Register services
    hass.services.async_register(DOMAIN, SERVICE_ADD_TASK, handle_add_task, ADD_TASK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_COMPLETE_TASK, handle_complete_task)
    hass.services.async_register(DOMAIN, SERVICE_SKIP_TASK, handle_skip_task)
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE_TASK, handle_snooze_task)
    hass.services.async_register(DOMAIN, SERVICE_REASSIGN_TASK, handle_reassign_task)
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_TASK, handle_update_task)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_TASK, handle_remove_task)
    hass.services.async_register(DOMAIN, SERVICE_ADD_LABEL, handle_add_label, ADD_LABEL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_LABEL, handle_update_label, UPDATE_LABEL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_LABEL, handle_remove_label, REMOVE_LABEL_SCHEMA)


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Housework services."""
    for service in (
        SERVICE_ADD_TASK,
        SERVICE_COMPLETE_TASK,
        SERVICE_SKIP_TASK,
        SERVICE_SNOOZE_TASK,
        SERVICE_REASSIGN_TASK,
        SERVICE_UPDATE_TASK,
        SERVICE_REMOVE_TASK,
        SERVICE_ADD_LABEL,
        SERVICE_UPDATE_LABEL,
        SERVICE_REMOVE_LABEL,
    ):
        hass.services.async_remove(DOMAIN, service)


def _resolve_entity_ids(call: ServiceCall) -> list[str]:
    """Resolve entity IDs from a service call with target support."""
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    return entity_ids
