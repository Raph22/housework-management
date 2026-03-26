"""Shared entity helpers for the Housework integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .models import Task


def resolve_area_name(hass: HomeAssistant, area_id: str | None) -> str | None:
    """Resolve an area_id to its name, or return None."""
    if not area_id:
        return None
    area_reg = ar.async_get(hass)
    area = area_reg.async_get_area(area_id)
    return area.name if area else None


def task_device_info(task: Task, suggested_area: str | None = None) -> DeviceInfo:
    """Return DeviceInfo for a task (one SERVICE device per task)."""
    info = DeviceInfo(
        identifiers={(DOMAIN, task.id)},
        name=task.title,
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Housework",
    )
    if suggested_area:
        info["suggested_area"] = suggested_area
    return info


def hub_device_info() -> DeviceInfo:
    """Return DeviceInfo for the global Housework hub."""
    return DeviceInfo(
        identifiers={(DOMAIN, "housework_hub")},
        name="Housework",
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Housework",
    )
