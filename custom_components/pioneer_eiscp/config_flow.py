"""Config flow for Pioneer eISCP."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers import selector

from .const import DEFAULT_MODEL, DEFAULT_NAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.HOST)
        ),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=65535,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)


class PioneerEiscpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pioneer eISCP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            name = user_input.get(CONF_NAME, DEFAULT_NAME)

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            # Validate TCP reachability without maintaining a session.
            try:
                await self._validate_connection(host, port)
            except OSError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "unknown"

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
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def _validate_connection(self, host: str, port: int) -> None:
        """Attempt a brief TCP connection to verify reachability."""
        import asyncio

        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=10,
        )
        writer.close()
        await writer.wait_closed()
