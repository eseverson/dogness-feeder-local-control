"""Camera entity tests."""

from __future__ import annotations

from homeassistant.components.camera import (
    CameraEntityFeature,
    async_get_image,
)
from homeassistant.components.camera.const import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.dogness_feeder.const import DOMAIN

from .conftest import HOST, SNAPSHOT_URL

ENTITY_ID = "camera.cat_feeder_camera"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_camera_declares_stream_and_two_way_audio(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    camera = hass.data[DATA_COMPONENT].get_entity(ENTITY_ID)
    assert camera is not None
    assert CameraEntityFeature.STREAM in camera.supported_features
    assert camera.camera_entity_capabilities.two_way_audio is True


async def test_stream_source_is_majestic_rtsp_with_quoted_credentials(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    camera = hass.data[DATA_COMPONENT].get_entity(ENTITY_ID)
    # go2rtc parses this as a URL, so ':' '/' '@' in the password must be escaped.
    assert (
        await camera.stream_source()
        == f"rtsp://root:p%40ss%3Aw%2Frd@{HOST}:554/stream=0"
    )


async def test_still_image_uses_basic_auth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(SNAPSHOT_URL, content=b"\xff\xd8still")
    await _setup(hass, config_entry)

    image = await async_get_image(hass, ENTITY_ID)
    assert image.content == b"\xff\xd8still"
    _, _, _, headers = aioclient_mock.mock_calls[-1]
    assert headers["Authorization"].startswith("Basic ")


async def test_camera_has_its_own_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await _setup(hass, config_entry)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, "feeder-1"), config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Cat Feeder Camera"


async def test_unload(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    await _setup(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
