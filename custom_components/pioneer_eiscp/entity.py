"""Base entity for Pioneer eISCP."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PioneerEiscpCoordinator


class PioneerEiscpEntity(CoordinatorEntity[PioneerEiscpCoordinator]):
    """Base class for Pioneer eISCP entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        host = entry.data[CONF_HOST]
        port = entry.data.get(CONF_PORT, 60128)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{host}:{port}")},
            manufacturer="Pioneer",
            model=entry.data.get("model", "VSX-1131"),
            name=coordinator.device_name,
        )


class PioneerConnectedEntity(PioneerEiscpEntity):
    """Entity unavailable when the persistent receiver connection is down."""

    @property
    def available(self) -> bool:
        """Return True when the receiver TCP session is connected."""
        return self.coordinator.receiver.connected
