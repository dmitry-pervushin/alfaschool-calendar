"""Alfa School calendar integration."""

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import AlfaSchoolClient
from .coordinator import AlfaSchoolCoordinator

PLATFORMS = [Platform.CALENDAR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Validate the first snapshot before adding the calendar."""
    session = async_create_clientsession(
        hass, auto_cleanup=False, cookie_jar=CookieJar()
    )
    client = AlfaSchoolClient(
        session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    coordinator = AlfaSchoolCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        session.detach()
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop polling and release the account's HTTP session."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.client.session.detach()
        return True
    return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed polling options."""
    await hass.config_entries.async_reload(entry.entry_id)
