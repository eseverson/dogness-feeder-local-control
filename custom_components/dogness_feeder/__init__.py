"""Camera with two-way audio for the OpenIPC-flashed Dogness feeder.

Feeding, schedules and sensors come from catd over MQTT discovery; this
integration only adds the camera entity, because MQTT cameras cannot stream or
declare two-way audio.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.CAMERA]

type FeederConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: FeederConfigEntry) -> bool:
    """Set up the feeder camera."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FeederConfigEntry) -> bool:
    """Unload the feeder camera."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
