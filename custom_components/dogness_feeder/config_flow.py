"""Config flow for the Dogness feeder camera."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MajesticAuthError, MajesticError, async_fetch_snapshot
from .const import CONF_DEVICE_ID, DEFAULT_DEVICE_ID, DEFAULT_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID): str,
    }
)


class FeederConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the feeder's address and Majestic login."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            try:
                await async_fetch_snapshot(
                    async_get_clientsession(self.hass),
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except MajesticAuthError:
                errors["base"] = "invalid_auth"
            except MajesticError as err:
                _LOGGER.debug(
                    "Feeder at %s unreachable: %s", user_input[CONF_HOST], err
                )
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Cat Feeder", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )
