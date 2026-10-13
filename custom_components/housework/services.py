"""Service handlers for the Housework integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any, NamedTuple

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import group
from homeassistant.helpers.service import async_extract_entity_ids

from .actions import async_apply_task_completion, prepare_task_completion
from .const import (
    ASSIGNMENT_STRATEGIES,
    DOMAIN,
    FREQUENCY_TYPES,
    SCHEDULING_FIELDS,
    SCHEDULING_MODES,
    CompletionAction,
    FrequencyType,
)
from .coordinator import SUBENTRY_TYPE_TASK, HouseworkCoordinator
from .models import CompletionRecord, Task
from .scheduling import calculate_initial_due, calculate_next_due_after_skip
from .store import HouseworkStore

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_TASK = "add_task"
SERVICE_COMPLETE_TASK = "complete_task"
SERVICE_SKIP_TASK = "skip_task"
SERVICE_SNOOZE_TASK = "snooze_task"
SERVICE_REASSIGN_TASK = "reassign_task"
SERVICE_UPDATE_TASK = "update_task"
SERVICE_REMOVE_TASK = "remove_task"
SERVICE_REOPEN_TASK = "reopen_task"


def _validate_iso_date(value: Any) -> str:
    """Validate and normalize a date value to an ISO date string."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        try:
            date.fromisoformat(value)
            return value
        except ValueError:
            pass
    raise vol.Invalid(f"Invalid date: {value}. Use YYYY-MM-DD format.")


def _validate_frequency_value(value: Any) -> int:
    """Accept whole-number intervals without truncating fractional values."""
    # Home Assistant's NumberSelector sends even whole numbers as floats.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise vol.Invalid("Frequency must be a whole number between 1 and 365")
    try:
        frequency = int(value)
    except ValueError as err:
        raise vol.Invalid("Frequency must be a whole number between 1 and 365") from err
    if not 1 <= frequency <= 365:
        raise vol.Invalid("Frequency must be a whole number between 1 and 365")
    return frequency


def _validate_title(value: Any) -> str:
    """Normalize a task title and reject names containing only whitespace."""
    title = cv.string(value).strip()
    if not title:
        raise vol.Invalid("Title must not be empty")
    return title


ADD_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("title"): _validate_title,
        vol.Required("frequency_type"): vol.In(FREQUENCY_TYPES),
        vol.Optional("frequency_value"): _validate_frequency_value,
        vol.Optional("frequency_days_of_week"): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))]
        ),
        vol.Optional("frequency_day_of_month"): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
        vol.Optional("scheduling_mode"): vol.In(SCHEDULING_MODES),
        vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
        vol.Optional("description", default=""): cv.string,
        vol.Optional("assignees"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("assignment_strategy"): vol.In(ASSIGNMENT_STRATEGIES),
        vol.Optional("icon", default="mdi:broom"): cv.string,
        vol.Optional("next_due"): _validate_iso_date,
    }
)

COMPLETE_TASK_SCHEMA = vol.Schema(
    {
        vol.Optional("completed_by"): cv.string,
        vol.Optional("completed_at"): cv.datetime,
    },
    extra=vol.ALLOW_EXTRA,
)

SNOOZE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("snooze_until"): _validate_iso_date,
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
        vol.Optional("title"): _validate_title,
        vol.Optional("description"): cv.string,
        vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
        vol.Optional("icon"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

REOPEN_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("next_due"): _validate_iso_date,
    },
    extra=vol.ALLOW_EXTRA,
)


def _get_entry_and_data(hass: HomeAssistant):
    """Get the config entry, store, and coordinator."""
    entries = hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        if hasattr(entry, "runtime_data") and entry.runtime_data:
            return entry, entry.runtime_data.store, entry.runtime_data.coordinator
    return None, None, None


def _get_task_from_entity_id(hass: HomeAssistant, entity_id: str):
    """Resolve a task through its entity registry links."""
    registry = er.async_get(hass)
    entity_entry = registry.async_get(entity_id)
    if (
        entity_entry is None
        or entity_entry.platform != DOMAIN
        or not entity_entry.config_entry_id
        or not entity_entry.config_subentry_id
    ):
        return None, None, None, None
    entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
    if entry is None or entry.domain != DOMAIN or not getattr(entry, "runtime_data", None):
        return None, None, None, None
    task_id = entity_entry.config_subentry_id
    subentry = entry.subentries.get(task_id)
    coordinator = entry.runtime_data.coordinator
    if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_TASK or not coordinator.data:
        return None, None, None, None
    if task_id not in coordinator.data:
        return None, None, None, None
    store = entry.runtime_data.store
    # Coordinator refreshes can be debounced. Services must read the latest
    # runtime state and configuration when called again during that cooldown.
    task = Task.from_subentry(task_id, dict(subentry.data), store.get_runtime_state(task_id))
    return task, store, coordinator, entry


class _TaskTarget(NamedTuple):
    """A validated task and the integration instance that owns it."""

    task: Task
    store: HouseworkStore
    coordinator: HouseworkCoordinator
    entry: ConfigEntry


async def _async_resolve_tasks(hass: HomeAssistant, call: ServiceCall) -> list[_TaskTarget]:
    """Validate all targets before mutation and deduplicate linked task entities."""
    entity_ids = await async_extract_entity_ids(call)
    if not entity_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_target",
        )
    explicit_ids = set(
        group.expand_entity_ids(hass, cv.ensure_list(call.data.get("entity_id", [])))
    )
    registry = er.async_get(hass)
    targets: dict[tuple[str, str], _TaskTarget] = {}
    for entity_id in sorted(entity_ids):
        task, store, coordinator, entry = _get_task_from_entity_id(hass, entity_id)
        if task is None:
            entity = registry.async_get(entity_id)
            if entity_id in explicit_ids or (
                entity and entity.platform == DOMAIN and entity.config_subentry_id
            ):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="task_not_found",
                )
            # Rooms, devices and labels can also contain unrelated integrations
            # or global Housework entities (calendar and counters).
            continue
        targets[(entry.entry_id, task.id)] = _TaskTarget(task, store, coordinator, entry)
    if not targets:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="task_not_found",
        )
    return list(targets.values())


def _validate_day_of_week_frequency(data: dict) -> None:
    """Reject day-of-week tasks without any selected weekdays."""
    if data.get("frequency_type") == FrequencyType.DAY_OF_WEEK and not data.get(
        "frequency_days_of_week"
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="days_of_week_required",
        )


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

        # Apply defaults for fields not provided by the caller
        data.setdefault("frequency_value", 1)
        data.setdefault("scheduling_mode", "rolling")
        data.setdefault("priority", options.get("default_priority", 3))
        data.setdefault(
            "assignment_strategy",
            options.get("default_assignment_strategy", "round_robin"),
        )
        _validate_day_of_week_frequency(data)

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
        targets = await _async_resolve_tasks(hass, call)
        completed_at = call.data.get("completed_at") or datetime.now(timezone.utc)
        completions = [
            (
                target,
                prepare_task_completion(
                    target.task,
                    target.store,
                    completed_by=call.data.get("completed_by"),
                    completed_at=completed_at,
                ),
            )
            for target in targets
        ]
        for target, completion in completions:
            if completion is not None:
                await async_apply_task_completion(
                    hass,
                    completion,
                    target.store,
                    target.coordinator,
                )

    async def handle_skip_task(call: ServiceCall) -> None:
        """Handle the skip_task service call."""
        targets = await _async_resolve_tasks(hass, call)
        due_dates = []
        for target in targets:
            try:
                next_due = calculate_next_due_after_skip(target.task)
            except (ValueError, OverflowError) as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_task_configuration",
                    translation_placeholders={"title": target.task.title},
                ) from err
            due_dates.append(next_due.isoformat() if next_due else None)
        for (task, store, coordinator, _entry), next_due_str in zip(
            targets, due_dates, strict=True
        ):
            await store.async_add_history(
                CompletionRecord(
                    task_id=task.id,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    action=CompletionAction.SKIPPED,
                )
            )
            await store.async_update_runtime_state(task.id, {"next_due": next_due_str})
            await coordinator.async_request_refresh()
            hass.bus.async_fire(
                "housework_task_skipped",
                {"task_id": task.id, "title": task.title, "next_due": next_due_str},
            )
            _LOGGER.info("Skipped task: %s", task.title)

    async def handle_snooze_task(call: ServiceCall) -> None:
        """Handle the snooze_task service call."""
        targets = await _async_resolve_tasks(hass, call)
        snooze_until = call.data["snooze_until"]
        for task, store, coordinator, _entry in targets:
            await store.async_add_history(
                CompletionRecord(
                    task_id=task.id,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    action=CompletionAction.SNOOZED,
                    snooze_until=snooze_until,
                )
            )
            await store.async_update_runtime_state(task.id, {"next_due": snooze_until})
            await coordinator.async_request_refresh()
            hass.bus.async_fire(
                "housework_task_snoozed",
                {"task_id": task.id, "title": task.title, "snooze_until": snooze_until},
            )
            _LOGGER.info("Snoozed task: %s until %s", task.title, snooze_until)

    async def handle_reassign_task(call: ServiceCall) -> None:
        """Handle the reassign_task service call."""
        targets = await _async_resolve_tasks(hass, call)
        assignee = call.data["assignee"]
        if any(assignee not in target.task.assignees for target in targets):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="assignee_not_allowed",
            )

        for task, store, coordinator, _entry in targets:
            await store.async_update_runtime_state(task.id, {"current_assignee": assignee})
            await coordinator.async_request_refresh()
            _LOGGER.info("Reassigned task: %s to %s", task.title, assignee)

    async def handle_update_task(call: ServiceCall) -> None:
        """Handle the update_task service call."""
        targets = await _async_resolve_tasks(hass, call)
        for task, _store, coordinator, entry in targets:
            subentry = entry.subentries[task.id]
            new_data = dict(subentry.data)
            new_title = subentry.title
            for key in ("title", "description", "icon", "priority"):
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
        targets = await _async_resolve_tasks(hass, call)
        for task, store, coordinator, entry in targets:
            await store.async_remove_runtime_state(task.id)
            hass.config_entries.async_remove_subentry(entry, task.id)
            await coordinator.async_request_refresh()
            _LOGGER.info("Removed task: %s", task.title)

    async def handle_reopen_task(call: ServiceCall) -> None:
        """Handle the reopen_task service call — set a new due date on a completed task."""
        targets = await _async_resolve_tasks(hass, call)
        next_due = call.data["next_due"]
        for task, store, coordinator, _entry in targets:
            await store.async_update_runtime_state(task.id, {"next_due": next_due})
            await coordinator.async_request_refresh()
            _LOGGER.info("Reopened task: %s, due %s", task.title, next_due)

    # Register services
    hass.services.async_register(DOMAIN, SERVICE_ADD_TASK, handle_add_task, ADD_TASK_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE_TASK, handle_complete_task, COMPLETE_TASK_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_SKIP_TASK, handle_skip_task)
    hass.services.async_register(
        DOMAIN, SERVICE_SNOOZE_TASK, handle_snooze_task, SNOOZE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REASSIGN_TASK, handle_reassign_task, REASSIGN_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_TASK, handle_update_task, UPDATE_TASK_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_TASK, handle_remove_task)
    hass.services.async_register(
        DOMAIN, SERVICE_REOPEN_TASK, handle_reopen_task, REOPEN_TASK_SCHEMA
    )


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
    ):
        hass.services.async_remove(DOMAIN, service)
