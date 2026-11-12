"""Use a real Home Assistant instance with isolated temporary storage."""

import pytest
from homeassistant import loader
from homeassistant.auth import auth_manager_from_config
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry, frame
from homeassistant.helpers.storage import get_internal_store_manager
from homeassistant.setup import async_setup_component


@pytest.fixture
async def hass(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    frame.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    device_registry.async_setup(hass)
    await get_internal_store_manager(hass).async_initialize()
    await device_registry.async_load(hass)
    await hass.config_entries.async_initialize()
    await entity_registry.async_load(hass)
    hass.auth = await auth_manager_from_config(hass, [], [])
    assert await async_setup_component(hass, "network", {})
    yield hass
    await hass.async_stop(force=True)
