"""Helpers for resolving config entries and coordinators from service calls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import service

from .const import ATTR_CONFIG_ENTRY, ATTR_ENTRY_ID, DEFAULT_PORT, DOMAIN, normalize_port

if TYPE_CHECKING:
    from .coordinator import PioneerEiscpCoordinator

_LOGGER = logging.getLogger(__name__)

_MSG_NO_RECEIVER = "No Pioneer eISCP receiver is configured"
_MSG_MULTIPLE = "Multiple Pioneer eISCP receivers are configured; select a receiver"
_MSG_NOT_LOADED = "Selected Pioneer eISCP receiver is not loaded"
_MSG_NOT_CONNECTED = "Selected Pioneer eISCP receiver is not connected"
_MSG_NOT_FOUND = "Selected Pioneer eISCP receiver was not found"


def _service_validation_to_home_assistant_error(err: ServiceValidationError) -> HomeAssistantError:
    """Map Home Assistant service validation errors to integration messages."""
    translation_key = getattr(err, "translation_key", None)
    if translation_key == "service_found_no_config_entry_for_domain":
        return HomeAssistantError(_MSG_NO_RECEIVER)
    if translation_key == "service_found_multiple_config_entry_for_domain":
        return HomeAssistantError(_MSG_MULTIPLE)
    if translation_key == "service_config_entry_not_loaded":
        return HomeAssistantError(_MSG_NOT_LOADED)
    if translation_key == "service_config_entry_not_found":
        return HomeAssistantError(_MSG_NOT_FOUND)
    return HomeAssistantError(str(err))


async def async_resolve_coordinator(
    hass: HomeAssistant,
    call: ServiceCall,
    *,
    require_connected: bool = True,
) -> PioneerEiscpCoordinator:
    """Resolve the coordinator for a config-entry-level service call."""
    entry_ids: set[str] = set()

    if config_entry_id := call.data.get(ATTR_CONFIG_ENTRY):
        entry_ids.add(config_entry_id)
    if legacy_entry_id := call.data.get(ATTR_ENTRY_ID):
        entry_ids.add(legacy_entry_id)

    entry_ids.update(await service.async_extract_config_entry_ids(call))

    if len(entry_ids) > 1:
        raise HomeAssistantError(_MSG_MULTIPLE)

    entry_id = next(iter(entry_ids)) if entry_ids else None

    try:
        config_entry = service.async_get_config_entry(hass, DOMAIN, entry_id)
    except ServiceValidationError as err:
        raise _service_validation_to_home_assistant_error(err) from err

    coordinator: PioneerEiscpCoordinator | None = config_entry.runtime_data
    if coordinator is None:
        raise HomeAssistantError(_MSG_NOT_LOADED)

    _LOGGER.debug(
        "Resolved Pioneer eISCP service call to config entry %s",
        config_entry.entry_id,
    )

    if require_connected and not coordinator.receiver.connected:
        raise HomeAssistantError(_MSG_NOT_CONNECTED)

    return coordinator


def device_identifier(host: str, port: int) -> str:
    """Return the device registry identifier suffix for host:port."""
    return f"{host}:{port}"


def entry_matches_device(entry, host: str, port: int) -> bool:
    """Return True if a config entry matches host:port."""
    entry_port = normalize_port(entry.data.get(CONF_PORT, DEFAULT_PORT))
    return entry.data.get(CONF_HOST) == host and entry_port == port
