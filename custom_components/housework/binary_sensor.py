"""Binary sensor platform for the Housework integration."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HouseworkCoordinator
from .models import Task
from .scheduling import format_frequency

_LOGGER = logging.getLogger(__name__)


def _load_frequency_translations(hass: HomeAssistant) -> dict:
    """Load frequency translations for the current HA language."""
    lang = hass.config.language or "en"
    translations_dir = Path(__file__).parent / "translations"

    for candidate in (lang, "en"):
        path = translations_dir / f"{candidate}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("frequency", {})
            except (json.JSONDecodeError, OSError):
                continue
    return {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Housework binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HouseworkCoordinator = data["coordinator"]
    freq_translations = await hass.async_add_executor_job(
        _load_frequency_translations, hass
    )

    known_task_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        """Add entities for any new tasks."""
        new_entities = []
        if coordinator.data:
            for task_id, task in coordinator.data.items():
                if task_id not in known_task_ids and task.enabled:
                    known_task_ids.add(task_id)
                    new_entities.append(
                        HouseworkTaskSensor(
                            coordinator, task, entry, freq_translations
                        )
                    )

        if new_entities:
            async_add_entities(new_entities)

    # Add entities for existing tasks
    entities = []
    if coordinator.data:
        for task in coordinator.data.values():
            if task.enabled:
                known_task_ids.add(task.id)
                entities.append(
                    HouseworkTaskSensor(
                        coordinator, task, entry, freq_translations
                    )
                )

    async_add_entities(entities)

    # Listen for coordinator updates to add new task entities
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class HouseworkTaskSensor(CoordinatorEntity[HouseworkCoordinator], BinarySensorEntity):
    """Binary sensor for a housework task. On when due or overdue."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HouseworkCoordinator,
        task: Task,
        entry: ConfigEntry,
        freq_translations: dict,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, context=task.id)
        self._task_id = task.id
        self._freq_translations = freq_translations
        self._attr_unique_id = f"housework_{task.id}"
        self._attr_translation_key = "housework_task"
        self._attr_icon = task.icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "housework_hub")},
            "name": "Housework",
            "manufacturer": "Housework Integration",
            "model": "Task Tracker",
        }

    @property
    def task_id(self) -> str:
        """Return the task ID."""
        return self._task_id

    @property
    def _task(self) -> Task | None:
        """Return the current task from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._task_id)
        return None

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        task = self._task
        return task.title if task else "Unknown Task"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._task is not None

    @property
    def is_on(self) -> bool | None:
        """Return True if the task is due or overdue."""
        task = self._task
        if task is None or task.next_due is None:
            return None

        try:
            due_date = date.fromisoformat(task.next_due)
        except (ValueError, TypeError):
            return None

        return date.today() >= due_date

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra state attributes."""
        task = self._task
        if task is None:
            return None

        days_overdue = 0
        if task.next_due:
            try:
                due_date = date.fromisoformat(task.next_due)
                days_overdue = (date.today() - due_date).days
            except (ValueError, TypeError):
                pass

        # Resolve assignee friendly name
        assignee_name = None
        if task.current_assignee:
            state = self.hass.states.get(task.current_assignee)
            if state:
                assignee_name = state.attributes.get(
                    "friendly_name", task.current_assignee
                )

        # Resolve label names
        store = None
        for entry_data in self.hass.data.get(DOMAIN, {}).values():
            if "store" in entry_data:
                store = entry_data["store"]
                break

        label_names = []
        if store:
            all_labels = store.get_all_labels()
            for label_id in task.labels:
                label = all_labels.get(label_id)
                if label:
                    label_names.append(label.name)

        return {
            "task_id": task.id,
            "title": task.title,
            "priority": task.priority,
            "next_due": task.next_due,
            "last_completed": task.last_completed,
            "current_assignee": task.current_assignee,
            "assignee_name": assignee_name,
            "frequency": format_frequency(task, self._freq_translations),
            "labels": label_names,
            "days_overdue": max(days_overdue, 0),
            "scheduling_mode": task.scheduling_mode,
            "assignment_strategy": task.assignment_strategy,
        }

    @property
    def icon(self) -> str:
        """Return the icon."""
        task = self._task
        return task.icon if task else "mdi:broom"
