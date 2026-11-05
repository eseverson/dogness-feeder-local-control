"""Config flow tests."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.dogness_feeder.const import DOMAIN

from .conftest import (
    DYN_ENTRY_DATA,
    DYN_HOST,
    DYN_SNAPSHOT_URL,
    ENTRY_DATA,
    SNAPSHOT_URL,
    STREAM_SENSOR,
)


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(SNAPSHOT_URL, content=b"\xff\xd8jpeg")

    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ENTRY_DATA
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cat Feeder"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == "feeder-1"


async def test_user_flow_with_a_host_entity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass.states.async_set(STREAM_SENSOR, f"rtsp://{DYN_HOST}:554/stream=0")
    aioclient_mock.get(DYN_SNAPSHOT_URL, content=b"\xff\xd8jpeg")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], DYN_ENTRY_DATA
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == DYN_ENTRY_DATA


async def test_user_flow_needs_a_host(hass: HomeAssistant) -> None:
    hass.states.async_set(STREAM_SENSOR, "unavailable")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], DYN_ENTRY_DATA
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_host"}


async def test_user_flow_invalid_auth_then_recovers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(SNAPSHOT_URL, status=401)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ENTRY_DATA
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(SNAPSHOT_URL, content=b"\xff\xd8jpeg")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ENTRY_DATA
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(SNAPSHOT_URL, exc=aiohttp.ClientError)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ENTRY_DATA
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_aborts_on_duplicate(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    aioclient_mock.get(SNAPSHOT_URL, content=b"\xff\xd8jpeg")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ENTRY_DATA
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
