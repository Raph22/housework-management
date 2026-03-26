"""Calendar platform for the Housework integration."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import FrequencyType
from .coordinator import HouseworkCoordinator
from .entity import hub_device_info
from .models import Task
from .scheduling import advance_one_period, fast_forward_to


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Housework calendar from a config entry."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities([HouseworkCalendar(coordinator)])


class HouseworkCalendar(CoordinatorEntity[HouseworkCoordinator], CalendarEntity):
    """Calendar entity showing all housework tasks."""

    _attr_has_entity_name = True
    _attr_translation_key = "housework"
    _attr_icon = "mdi:broom"

    def __init__(self, coordinator: HouseworkCoordinator) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._attr_unique_id = "housework_calendar"
        self._attr_device_info = hub_device_info()

    @property
    def event(self) -> CalendarEvent | None:
        """Return the active event or the next upcoming event."""
        if not self.coordinator.data:
            return None

        event = _find_current_or_next_event(
            self.coordinator.data.values(),
            dt_util.now().date(),
        )
        if event is None:
            return None

        task, due = event
        return _task_to_event(task, due, self.hass)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events within the given date range."""
        if not self.coordinator.data:
            return []

        range_start = start_date.date()
        range_end = end_date.date()
        events: list[CalendarEvent] = []
        max_projections = 52

        for task in self.coordinator.data.values():
            if not task.next_due:
                continue

            try:
                due = date.fromisoformat(task.next_due)
            except (ValueError, TypeError):
                continue

            # Fast-forward past dates far before the range
            if due < range_start and task.frequency_type != FrequencyType.ONCE:
                due = fast_forward_to(due, task, range_start)

            current_due = due
            count = 0
            while current_due <= range_end and count < max_projections:
                if current_due >= range_start:
                    events.append(_task_to_event(task, current_due, hass))

                if task.frequency_type == FrequencyType.ONCE:
                    break
                current_due = advance_one_period(current_due, task)
                count += 1

        events.sort(key=lambda e: e.start)
        return events


def _task_to_event(
    task: Task, due_date: date, hass: HomeAssistant
) -> CalendarEvent:
    """Convert a task + due date to a CalendarEvent."""
    summary = task.title
    if task.current_assignee:
        state = hass.states.get(task.current_assignee)
        if state:
            name = state.attributes.get("friendly_name", task.current_assignee)
            summary = f"{task.title} ({name})"

    parts = []
    if task.priority <= 2:
        parts.append(f"Priority: P{task.priority}")
    if task.description:
        parts.append(task.description)
    description = "\n".join(parts) if parts else None

    return CalendarEvent(
        start=due_date,
        end=due_date + timedelta(days=1),
        summary=summary,
        description=description,
        uid=f"{task.id}_{due_date.isoformat()}",
    )


def _find_current_or_next_event(
    tasks: Iterable[Task],
    today: date,
) -> tuple[Task, date] | None:
    """Find the current all-day event or the next upcoming event."""
    current_event: tuple[Task, date] | None = None
    next_event: tuple[Task, date] | None = None

    for task in tasks:
        if not task.next_due:
            continue
        try:
            due = date.fromisoformat(task.next_due)
        except (ValueError, TypeError):
            continue

        if due == today:
            if current_event is None or due < current_event[1]:
                current_event = (task, due)
            continue

        if due > today and (next_event is None or due < next_event[1]):
            next_event = (task, due)

    return current_event or next_event
