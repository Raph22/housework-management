"""Service handlers for the Housework integration."""

from __future__ import annotations

from datetime import date, datetime, timezone
import logging
from types import MappingProxyType

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.service import async_extract_entity_ids

from homeassistant.config_entries import ConfigSubentry

from .assignment import determine_next_assignee, update_assignment_state
from .const import (
    ASSIGNMENT_STRATEGIES,
    DOMAIN,
    FREQUENCY_TYPES,
    SCHEDULING_FIELDS,
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
SERVICE_REOPEN_TASK = "reopen_task"
SERVICE_ADD_LABEL = "add_label"
SERVICE_UPDATE_LABEL = "update_label"
SERVICE_REMOVE_LABEL = "remove_label"

ADD_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("title"): cv.string,
        vol.Required("frequency_type"): vol.In(FREQUENCY_TYPES),
        vol.Optional("frequency_value", default=1): vol.Coerce(int),
        vol.Optional("frequency_days_of_week"): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))]
        ),
        vol.Optional("frequency_day_of_month"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=31)
        ),
        vol.Optional("scheduling_mode", default="rolling"): vol.In(SCHEDULING_MODES),
        vol.Optional("priority"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=4)
        ),
        vol.Optional("description", default=""): cv.string,
        vol.Optional("assignees"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("assignment_strategy"): vol.In(
            ASSIGNMENT_STRATEGIES
        ),
        vol.Optional("icon", default="mdi:broom"): cv.string,
        vol.Optional("labels"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("next_due"): cv.string,
    }
)

COMPLETE_TASK_SCHEMA = vol.Schema(
    {
        vol.Optional("completed_by"): cv.string,
        vol.Optional("completed_at"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

SNOOZE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("snooze_until"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

REASSIGN_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("assignee"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

UPDATE_TASK_SCHEMA = vol.Schema(
    {
        vol.Optional("title"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
        vol.Optional("icon"): cv.string,
        vol.Optional("labels"): vol.All(cv.ensure_list, [cv.string]),
    },
    extra=vol.ALLOW_EXTRA,
)

REOPEN_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("next_due"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
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


def _get_entry_and_data(hass: HomeAssistant):
    """Get the config entry, store, and coordinator."""
    entries = hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        if hasattr(entry, "runtime_data") and entry.runtime_data:
            return entry, entry.runtime_data.store, entry.runtime_data.coordinator
    return None, None, None


def _get_task_from_entity_id(hass: HomeAssistant, entity_id: str):
    """Resolve an entity_id to a task via the coordinator."""
    entry, store, coordinator = _get_entry_and_data(hass)
    if coordinator is None or not coordinator.data:
        return None, None, None, None

    # Find the task ID from the entity's unique_id
    registry = er.async_get(hass)
    entity_entry = registry.async_get(entity_id)
    if entity_entry is None:
        return None, None, None, None

    # unique_id is "housework_{subentry_id}_{suffix}" (e.g., _due, _mark_done)
    unique_id = entity_entry.unique_id
    prefix = "housework_"
    if not unique_id or not unique_id.startswith(prefix):
        return None, None, None, None

    remainder = unique_id[len(prefix):]
    # Try stripping known suffixes, fall back to using remainder as-is
    for suffix in ("_due", "_mark_done", "_priority", "_next_due"):
        if remainder.endswith(suffix):
            task_id = remainder[: -len(suffix)]
            break
    else:
        task_id = remainder

    task = coordinator.data.get(task_id)
    if task:
        return task, store, coordinator, entry

    return None, None, None, None


async def _async_resolve_entity_ids(
    hass: HomeAssistant, call: ServiceCall
) -> list[str]:
    """Resolve entity IDs from a service call, supporting area/device/label targeting."""
    entity_ids = await async_extract_entity_ids(hass, call)
    if not entity_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_target",
        )
    return list(entity_ids)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up Housework services."""
    if hass.services.has_service(DOMAIN, SERVICE_ADD_TASK):
        return

    async def handle_add_task(call: ServiceCall) -> None:
        """Handle the add_task service call — creates a config subentry."""
        entry, store, coordinator = _get_entry_and_data(hass)
        if entry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="integration_not_found",
            )

        data = dict(call.data)
        options = dict(entry.options)

        # Apply option defaults only when the user didn't provide a value
        data.setdefault("priority", options.get("default_priority", 3))
        data.setdefault(
            "assignment_strategy",
            options.get("default_assignment_strategy", "round_robin"),
        )

        title = data["title"]

        # Calculate initial due date
        task = Task.from_subentry("temp", data)
        if data.get("next_due"):
            initial_due = data["next_due"]
        else:
            initial_due = calculate_initial_due(task).isoformat()

        # Create the subentry
        subentry = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type="task",
            title=title,
            unique_id=None,
        )
        hass.config_entries.async_add_subentry(entry, subentry)

        # The subentry now has a subentry_id assigned by HA.
        # Initialize runtime state. The subentry change listener in __init__.py
        # also handles this, but we do it here to ensure it's ready before refresh.
        runtime = {
            "next_due": initial_due,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scheduling_signature": {k: data.get(k) for k in SCHEDULING_FIELDS},
        }
        if data.get("assignees"):
            runtime["current_assignee"] = data["assignees"][0]
        await store.async_update_runtime_state(subentry.subentry_id, runtime)
        await coordinator.async_request_refresh()
        _LOGGER.info("Added task: %s", title)

    async def handle_complete_task(call: ServiceCall) -> None:
        """Handle the complete_task service call."""
        entity_ids = await _async_resolve_entity_ids(hass, call)
        for entity_id in entity_ids:
            await _complete_single_task(hass, call, entity_id)

    async def _complete_single_task(
        hass: HomeAssistant, call: ServiceCall, entity_id: str
    ) -> None:
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        completed_by = call.data.get("completed_by", task.current_assignee or "")
        completed_at = call.data.get("completed_at")
        if completed_at:
            completed_at_str = completed_at if isinstance(completed_at, str) else completed_at.isoformat()
        else:
            completed_at_str = datetime.now(timezone.utc).isoformat()

        record = CompletionRecord(
            task_id=task.id,
            completed_by=completed_by,
            completed_at=completed_at_str,
            action=CompletionAction.COMPLETED,
        )
        await store.async_add_history(record)

        # Calculate next due using override (don't mutate task)
        runtime_updates: dict = {"last_completed": completed_at_str}
        if task.frequency_type != FrequencyType.ONCE:
            next_due = calculate_next_due(
                task, last_completed_override=completed_at_str
            )
            runtime_updates["next_due"] = next_due.isoformat() if next_due else None
        else:
            runtime_updates["next_due"] = None

        # Update assignment
        current_assignee = task.current_assignee
        if completed_by and task.assignees:
            state = store.get_assignment_state(task.id)
            state = update_assignment_state(state, completed_by)
            current_assignee = determine_next_assignee(task, state)
            await store.async_update_assignment_state(task.id, state)
        runtime_updates["current_assignee"] = current_assignee

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

    async def handle_skip_task(call: ServiceCall) -> None:
        """Handle the skip_task service call."""
        entity_ids = await _async_resolve_entity_ids(hass, call)
        for entity_id in entity_ids:
            await _skip_single_task(hass, entity_id)

    async def _skip_single_task(hass: HomeAssistant, entity_id: str) -> None:
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        record = CompletionRecord(
            task_id=task.id,
            completed_at=datetime.now(timezone.utc).isoformat(),
            action=CompletionAction.SKIPPED,
        )
        await store.async_add_history(record)

        next_due = calculate_next_due_after_skip(task)
        next_due_str = next_due.isoformat() if next_due else None

        await store.async_update_runtime_state(task.id, {"next_due": next_due_str})
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            "housework_task_skipped",
            {"task_id": task.id, "title": task.title, "next_due": next_due_str},
        )
        _LOGGER.info("Skipped task: %s", task.title)

    async def handle_snooze_task(call: ServiceCall) -> None:
        """Handle the snooze_task service call."""
        entity_ids = await _async_resolve_entity_ids(hass, call)
        snooze_until = call.data["snooze_until"]
        for entity_id in entity_ids:
            await _snooze_single_task(hass, entity_id, snooze_until)

    async def _snooze_single_task(
        hass: HomeAssistant, entity_id: str, snooze_until: str
    ) -> None:
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        if isinstance(snooze_until, date):
            snooze_until = snooze_until.isoformat()

        record = CompletionRecord(
            task_id=task.id,
            completed_at=datetime.now(timezone.utc).isoformat(),
            action=CompletionAction.SNOOZED,
            snooze_until=snooze_until,
        )
        await store.async_add_history(record)

        await store.async_update_runtime_state(task.id, {"next_due": snooze_until})
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            "housework_task_snoozed",
            {"task_id": task.id, "title": task.title, "snooze_until": snooze_until},
        )
        _LOGGER.info("Snoozed task: %s until %s", task.title, snooze_until)

    async def handle_reassign_task(call: ServiceCall) -> None:
        """Handle the reassign_task service call."""
        entity_ids = await _async_resolve_entity_ids(hass, call)
        assignee = call.data["assignee"]
        for entity_id in entity_ids:
            await _reassign_single_task(hass, entity_id, assignee)

    async def _reassign_single_task(
        hass: HomeAssistant, entity_id: str, assignee: str
    ) -> None:
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        await store.async_update_runtime_state(task.id, {"current_assignee": assignee})
        await coordinator.async_request_refresh()
        _LOGGER.info("Reassigned task: %s to %s", task.title, assignee)

    async def handle_update_task(call: ServiceCall) -> None:
        """Handle the update_task service call."""
        entity_ids = await _async_resolve_entity_ids(hass, call)
        for entity_id in entity_ids:
            await _update_single_task(hass, call, entity_id)

    async def _update_single_task(
        hass: HomeAssistant, call: ServiceCall, entity_id: str
    ) -> None:
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None or entry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        subentry = entry.subentries.get(task.id)
        if subentry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        new_data = dict(subentry.data)
        new_title = subentry.title
        for key in ("title", "description", "icon", "priority", "labels"):
            if key in call.data:
                new_data[key] = call.data[key]
                if key == "title":
                    new_title = call.data[key]

        hass.config_entries.async_update_subentry(
            entry, subentry, data=new_data, title=new_title
        )
        await coordinator.async_request_refresh()
        _LOGGER.info("Updated task: %s", new_title)

    async def handle_remove_task(call: ServiceCall) -> None:
        """Handle the remove_task service call."""
        entity_ids = await _async_resolve_entity_ids(hass, call)
        for entity_id in entity_ids:
            await _remove_single_task(hass, entity_id)

    async def _remove_single_task(hass: HomeAssistant, entity_id: str) -> None:
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None or entry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        title = task.title
        # Remove runtime state
        await store.async_remove_runtime_state(task.id)
        # Remove subentry (cascades entity cleanup)
        hass.config_entries.async_remove_subentry(entry, task.id)
        await coordinator.async_request_refresh()
        _LOGGER.info("Removed task: %s", title)

    async def handle_reopen_task(call: ServiceCall) -> None:
        """Handle the reopen_task service call — set a new due date on a completed task."""
        entity_ids = await _async_resolve_entity_ids(hass, call)
        next_due = call.data["next_due"]
        if isinstance(next_due, date):
            next_due = next_due.isoformat()
        for entity_id in entity_ids:
            await _reopen_single_task(hass, entity_id, next_due)

    async def _reopen_single_task(
        hass: HomeAssistant, entity_id: str, next_due: str
    ) -> None:
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
            )

        await store.async_update_runtime_state(task.id, {"next_due": next_due})
        await coordinator.async_request_refresh()
        _LOGGER.info("Reopened task: %s, due %s", task.title, next_due)

    async def handle_add_label(call: ServiceCall) -> None:
        """Handle the add_label service call."""
        entry, store, coordinator = _get_entry_and_data(hass)
        if store is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="integration_not_found",
            )

        label = Label(
            name=call.data["name"],
            color=call.data.get("color", ""),
            icon=call.data.get("icon", ""),
        )
        await store.async_add_label(label)
        _LOGGER.info("Added label: %s", label.name)

    async def handle_update_label(call: ServiceCall) -> None:
        """Handle the update_label service call."""
        entry, store, coordinator = _get_entry_and_data(hass)
        if store is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="integration_not_found",
            )

        label_id = call.data["label_id"]
        updates = {}
        for key in ("name", "color", "icon"):
            if key in call.data:
                updates[key] = call.data[key]

        if updates:
            result = await store.async_update_label(label_id, updates)
            if result is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="label_not_found",
                )
            else:
                _LOGGER.info("Updated label: %s", result.name)

    async def handle_remove_label(call: ServiceCall) -> None:
        """Handle the remove_label service call."""
        entry, store, coordinator = _get_entry_and_data(hass)
        if store is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="integration_not_found",
            )

        label_id = call.data["label_id"]
        removed = await store.async_remove_label(label_id)
        if not removed:
            raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="label_not_found",
                )
        else:
            _LOGGER.info("Removed label: %s", label_id)

    # Register services
    hass.services.async_register(DOMAIN, SERVICE_ADD_TASK, handle_add_task, ADD_TASK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_COMPLETE_TASK, handle_complete_task, COMPLETE_TASK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SKIP_TASK, handle_skip_task)
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE_TASK, handle_snooze_task, SNOOZE_TASK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REASSIGN_TASK, handle_reassign_task, REASSIGN_TASK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_TASK, handle_update_task, UPDATE_TASK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_TASK, handle_remove_task)
    hass.services.async_register(DOMAIN, SERVICE_REOPEN_TASK, handle_reopen_task, REOPEN_TASK_SCHEMA)
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
        SERVICE_REOPEN_TASK,
        SERVICE_ADD_LABEL,
        SERVICE_UPDATE_LABEL,
        SERVICE_REMOVE_LABEL,
    ):
        hass.services.async_remove(DOMAIN, service)
