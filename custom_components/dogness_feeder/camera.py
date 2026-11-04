"""Feeder camera: Majestic RTSP stream with the ONVIF audio back-channel."""

from __future__ import annotations

import logging

from homeassistant.components.camera import (
    Camera,
    CameraEntityCapabilities,
    CameraEntityFeature,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FeederConfigEntry
from .api import MajesticError, async_fetch_snapshot, rtsp_url
from .const import CONF_DEVICE_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FeederConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the feeder camera."""
    async_add_entities([FeederCamera(entry)])


class FeederCamera(Camera):
    """The feeder's camera, microphone and speaker."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = CameraEntityFeature.STREAM
    # HA's go2rtc opens the RTSP stream with the ONVIF back-channel and forwards
    # browser mic audio to it, transcoded to the PCMU/8000 Majestic accepts.
    _attr_camera_entity_capabilities = CameraEntityCapabilities(two_way_audio=True)

    def __init__(self, entry: FeederConfigEntry) -> None:
        """Initialize from the config entry."""
        super().__init__()
        self._host: str = entry.data[CONF_HOST]
        self._username: str = entry.data[CONF_USERNAME]
        self._password: str = entry.data[CONF_PASSWORD]
        device_id: str = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_camera"
        # Its own device: since 2026.11 a config entry can't attach entities to
        # the device catd created over MQTT discovery.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name="Cat Feeder Camera",
            manufacturer="Dogness",
            model="PETS V200",
        )

    async def stream_source(self) -> str:
        """Return the RTSP URL go2rtc should pull."""
        return rtsp_url(self._host, self._username, self._password)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still from Majestic."""
        try:
            return await async_fetch_snapshot(
                async_get_clientsession(self.hass),
                self._host,
                self._username,
                self._password,
            )
        except MajesticError as err:
            _LOGGER.debug("Snapshot from %s failed: %s", self._host, err)
            return None
