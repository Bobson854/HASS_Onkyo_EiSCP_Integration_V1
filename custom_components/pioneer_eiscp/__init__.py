"""The Pioneer eISCP integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_ISCP_COMMAND,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
    SERVICE_SEND_RAW,
)
from .coordinator import PioneerEiscpCoordinator
from .receiver import PioneerReceiver

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    PioneerEiscpConfigEntry = ConfigEntry[PioneerEiscpCoordinator]
else:
    PioneerEiscpConfigEntry = ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register domain-level services."""

    async def handle_send_raw(call: ServiceCall) -> None:
        command = call.data[ATTR_ISCP_COMMAND]
        _LOGGER.debug("Service send_raw: %s", command)
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator: PioneerEiscpCoordinator | None = entry.runtime_data
            if coordinator and coordinator.receiver.connected:
                await coordinator.async_send_raw(command)
                return
        # Fall back to first entry even if disconnected (will raise/queue).
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = entry.runtime_data
            if coordinator:
                await coordinator.async_send_raw(command)
                return
        _LOGGER.warning("No pioneer_eiscp config entries loaded")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RAW,
        handle_send_raw,
        schema=vol.Schema({vol.Required(ATTR_ISCP_COMMAND): str}),
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: PioneerEiscpConfigEntry) -> bool:
    """Set up Pioneer eISCP from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    name = entry.data.get(CONF_NAME, entry.title)

    receiver = PioneerReceiver(host, port)
    coordinator = PioneerEiscpCoordinator(hass, receiver, entry.entry_id, name)
    coordinator.async_set_updated_data(receiver.state)
    entry.runtime_data = coordinator

    await receiver.start()

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{host}:{port}")},
        manufacturer="Pioneer",
        model=entry.data.get("model", "VSX-1131"),
        name=name,
        configuration_url=f"http://{host}/",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    listen_task = asyncio.create_task(
        coordinator.async_listen(),
        name=f"pioneer_eiscp_listen_{entry.entry_id}",
    )

    async def _cancel_listen() -> None:
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

    entry.async_on_unload(_cancel_listen)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: PioneerEiscpConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    coordinator = entry.runtime_data
    if coordinator:
        await coordinator.receiver.stop()

    return unload_ok
