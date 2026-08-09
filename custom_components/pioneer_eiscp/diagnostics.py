"""Diagnostics support for Pioneer eISCP."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import PioneerEiscpCoordinator

TO_REDACT = {"host"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: PioneerEiscpCoordinator = entry.runtime_data
    data = coordinator.get_diagnostics()
    return async_redact_data(data, TO_REDACT)
