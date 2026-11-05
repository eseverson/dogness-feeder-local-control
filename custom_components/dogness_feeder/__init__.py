"""Camera with two-way audio for the OpenIPC-flashed Dogness feeder.

Feeding, schedules and sensors come from catd over MQTT discovery; this
integration only adds the camera entity, because MQTT cameras cannot stream or
declare two-way audio.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant

from .api import host_from_url
from .const import CONF_HOST_ENTITY

PLATFORMS = [Platform.CAMERA]

type FeederConfigEntry = ConfigEntry


def resolve_host(hass: HomeAssistant, data: Mapping[str, Any]) -> str | None:
    """The fixed host if there is one, else the host the host entity names now."""
    if host := data.get(CONF_HOST):
        return host
    if not (entity_id := data.get(CONF_HOST_ENTITY)):
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    return host_from_url(state.state)


async def async_setup_entry(hass: HomeAssistant, entry: FeederConfigEntry) -> bool:
    """Set up the feeder camera."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FeederConfigEntry) -> bool:
    """Unload the feeder camera."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
