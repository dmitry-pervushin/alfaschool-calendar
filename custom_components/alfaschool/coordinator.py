"""Poll schedules atomically and retain months requested by the calendar UI."""

import logging
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import AlfaSchoolClient
from .const import (
    CONF_INTERVAL_HOURS,
    DEFAULT_INTERVAL_HOURS,
    DOMAIN,
    MAX_INTERVAL_HOURS,
)
from .exceptions import AuthenticationError, ScheduleError
from .parser import MOSCOW

_LOGGER = logging.getLogger(__name__)


def months_between(start: date, end: date) -> set[date]:
    """Return month starts, inclusive of both dates."""
    result = set()
    month = start.replace(day=1)
    while month <= end:
        result.add(month)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


class AlfaSchoolCoordinator(DataUpdateCoordinator[list[dict]]):
    """One shared snapshot, replaced only after all pages succeed."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: AlfaSchoolClient
    ):
        hours = min(
            entry.options.get(CONF_INTERVAL_HOURS, DEFAULT_INTERVAL_HOURS),
            MAX_INTERVAL_HOURS,
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=hours) if hours else None,
        )
        self.client = client
        self.manual_updates = hours == 0
        self._requested_months: set[date] = set()
        self._loaded_months: set[date] = set()

    async def _async_update_data(self) -> list[dict]:
        today = dt_util.now().astimezone(MOSCOW).date()
        months = self._requested_months | months_between(
            today - timedelta(days=30), today + timedelta(days=180)
        )
        try:
            events = await self.client.async_fetch_months(months)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Alfa School credentials rejected") from err
        except ScheduleError as err:
            raise UpdateFailed("Unable to parse Alfa School schedule") from err
        self._loaded_months = months
        return events

    async def async_get_events(self, start: datetime, end: datetime) -> list[dict]:
        """Read the snapshot; manual mode queues missing months for the next refresh."""
        if end <= start:
            return []
        # Include the preceding day for lessons crossing midnight/month boundaries.
        months = months_between(
            start.astimezone(MOSCOW).date() - timedelta(days=1),
            end.astimezone(MOSCOW).date(),
        )
        self._requested_months.update(months)
        if not self.manual_updates and not months <= self._loaded_months:
            await self.async_refresh()
        if not self.last_update_success:
            raise HomeAssistantError("Alfa School schedule is unavailable")
        return [
            event
            for event in self.data
            if not event["cancelled"] and event["end"] > start and event["start"] < end
        ]
