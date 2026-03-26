"""Shared entity helpers for the Housework integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .models import Task


def task_device_info(task: Task) -> DeviceInfo:
    """Return DeviceInfo for a task (one SERVICE device per task)."""
    return DeviceInfo(
        identifiers={(DOMAIN, task.id)},
        name=task.title,
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Housework",
    )


def hub_device_info() -> DeviceInfo:
    """Return DeviceInfo for the global Housework hub."""
    return DeviceInfo(
        identifiers={(DOMAIN, "housework_hub")},
        name="Housework",
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Housework",
    )
