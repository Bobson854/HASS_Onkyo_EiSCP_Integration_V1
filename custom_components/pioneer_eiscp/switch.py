"""Switch platform for Pioneer eISCP Zone 2 architecture."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PioneerEiscpCoordinator
from .entity import PioneerEiscpEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pioneer switch entities from a config entry."""
    coordinator: PioneerEiscpCoordinator = entry.runtime_data
    async_add_entities([PioneerZone2PowerSwitch(coordinator, entry)])


class PioneerZone2PowerSwitch(PioneerEiscpEntity, SwitchEntity):
    """Zone 2 power switch (ZPW) — architecture placeholder."""

    _attr_name = "Zone 2 Power"
    _attr_icon = "mdi:power"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_zone2_power"

    @property
    def is_on(self) -> bool | None:
        """Return true if Zone 2 is powered on."""
        return self.coordinator.data.zone2.power

    async def async_turn_on(self) -> None:
        """Turn Zone 2 on."""
        await self.coordinator.receiver.send_raw("ZPW01")

    async def async_turn_off(self) -> None:
        """Turn Zone 2 off."""
        await self.coordinator.receiver.send_raw("ZPW00")
