"""Fixtures for the dogness_feeder custom integration tests."""

from __future__ import annotations

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant.common import MockConfigEntry

from custom_components.dogness_feeder.const import CONF_DEVICE_ID, DOMAIN

HOST = "192.0.2.10"
SNAPSHOT_URL = f"http://{HOST}/image.jpg"
ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "p@ss:w/rd",
    CONF_DEVICE_ID: "feeder-1",
}


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry for one feeder."""
    return MockConfigEntry(
        domain=DOMAIN, title="Cat Feeder", data=ENTRY_DATA, unique_id="feeder-1"
    )
