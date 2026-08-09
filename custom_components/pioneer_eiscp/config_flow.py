"""Config flow for Pioneer eISCP."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers import selector

from .config_validation import (
    EiscpConnectionError,
    EiscpInvalidResponseError,
    EiscpValidationError,
    validate_eiscp_receiver,
)
from .const import DEFAULT_MODEL, DEFAULT_NAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the host/port/name schema with optional defaults for reconfigure."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_HOST,
                default=defaults.get(CONF_HOST),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.HOST)
            ),
            vol.Required(
                CONF_PORT,
                default=defaults.get(CONF_PORT, DEFAULT_PORT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=65535,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_NAME,
                default=defaults.get(CONF_NAME, DEFAULT_NAME),
            ): str,
        }
    )


class PioneerEiscpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pioneer eISCP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            name = user_input.get(CONF_NAME, DEFAULT_NAME)

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            errors = await self._async_validate_receiver(host, port)
            if not errors:
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: name,
                        "model": DEFAULT_MODEL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing host, port, or name after initial setup."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            name = user_input.get(CONF_NAME, DEFAULT_NAME)
            new_unique_id = f"{host}:{port}"

            duplicate = _find_duplicate_entry(self.hass, DOMAIN, new_unique_id, reconfigure_entry.entry_id)
            if duplicate is not None:
                errors["base"] = "already_configured"
            else:
                errors = await self._async_validate_receiver(host, port)

            if not errors:
                await self.async_set_unique_id(new_unique_id)
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=name,
                    data_updates={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: name,
                    },
                )

        defaults = {
            CONF_HOST: reconfigure_entry.data[CONF_HOST],
            CONF_PORT: reconfigure_entry.data.get(CONF_PORT, DEFAULT_PORT),
            CONF_NAME: reconfigure_entry.data.get(CONF_NAME, reconfigure_entry.title),
        }

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(defaults),
            errors=errors,
        )

    async def _async_validate_receiver(self, host: str, port: int) -> dict[str, str]:
        """Run eISCP validation in executor; return config-flow error keys."""
        try:
            await self.hass.async_add_executor_job(validate_eiscp_receiver, host, port)
        except EiscpConnectionError as err:
            _LOGGER.debug("Setup validation connection failed for %s:%s: %s", host, port, err)
            return {"base": "cannot_connect"}
        except EiscpInvalidResponseError as err:
            _LOGGER.debug("Setup validation invalid response from %s:%s: %s", host, port, err)
            return {"base": "invalid_response"}
        except EiscpValidationError as err:
            _LOGGER.warning("Setup validation failed for %s:%s: %s", host, port, err)
            return {"base": "unknown"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during eISCP validation for %s:%s", host, port)
            return {"base": "unknown"}
        return {}


def _find_duplicate_entry(hass, domain: str, unique_id: str, exclude_entry_id: str):
    """Return a config entry with the same unique_id, excluding the given entry."""
    for entry in hass.config_entries.async_entries(domain):
        if entry.entry_id != exclude_entry_id and entry.unique_id == unique_id:
            return entry
    return None
