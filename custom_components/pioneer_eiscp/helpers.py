"""Helpers for resolving config entries and coordinators from service calls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import DEFAULT_PORT, DOMAIN, normalize_port

if TYPE_CHECKING:
    from .coordinator import PioneerEiscpCoordinator


def resolve_coordinator(hass: HomeAssistant, call: ServiceCall) -> PioneerEiscpCoordinator | None:
    """Resolve the coordinator targeted by a service call."""
    entries = hass.config_entries.async_entries(DOMAIN)

    if call.target:
        device_registry = dr.async_get(hass)
        for device_id in call.target.get("device_id") or []:
            device = device_registry.async_get(device_id)
            if not device:
                continue
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == DOMAIN and entry.runtime_data:
                    return entry.runtime_data

    entry_id = call.data.get("entry_id")
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and entry.runtime_data:
            return entry.runtime_data

    if len(entries) == 1 and entries[0].runtime_data:
        return entries[0].runtime_data

    for entry in entries:
        coordinator: PioneerEiscpCoordinator | None = entry.runtime_data
        if coordinator and coordinator.receiver.connected:
            return coordinator

    return entries[0].runtime_data if entries else None


def device_identifier(host: str, port: int) -> str:
    """Return the device registry identifier suffix for host:port."""
    return f"{host}:{port}"


def entry_matches_device(entry, host: str, port: int) -> bool:
    """Return True if a config entry matches host:port."""
    entry_port = normalize_port(entry.data.get(CONF_PORT, DEFAULT_PORT))
    return entry.data.get(CONF_HOST) == host and entry_port == port
