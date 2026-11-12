"""Native, read-only Home Assistant calendar for Alfa School lessons."""

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import AlfaSchoolCoordinator

PARALLEL_UPDATES = 0


def to_calendar_event(event: dict) -> CalendarEvent:
    """Keep stable lesson IDs across reschedules and refreshes."""
    return CalendarEvent(
        start=event["start"],
        end=event["end"],
        summary=event["summary"],
        description=event["description"],
        uid=f"lesson-{event['id']}@my.alfaschool.ru",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one calendar per school account."""
    async_add_entities([AlfaSchoolCalendar(entry.runtime_data, entry)])


class AlfaSchoolCalendar(CoordinatorEntity[AlfaSchoolCoordinator], CalendarEntity):
    """Expose lessons to calendar UI, cards, and automation triggers."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:school"
    _attr_supported_features = 0

    def __init__(self, coordinator: AlfaSchoolCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = entry.entry_id
        student = entry.options.get(CONF_NAME, "").strip() or entry.data[CONF_USERNAME]
        self._attr_name = f"Alfa School — {student}"

    @property
    def event(self) -> CalendarEvent | None:
        """Return an ongoing lesson, otherwise the next one, using local time only."""
        now = dt_util.now()
        for event in self.coordinator.data or []:
            if not event["cancelled"] and event["end"] > now:
                return to_calendar_event(event)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return lessons overlapping the requested range, end exclusive."""
        return [
            to_calendar_event(event)
            for event in await self.coordinator.async_get_events(start_date, end_date)
        ]
