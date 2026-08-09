"""Select platform for Pioneer eISCP (listening mode, HDMI output architecture)."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LISTENING_MODE_TO_CODE, LISTENING_MODES
from .coordinator import PioneerEiscpCoordinator
from .entity import PioneerConnectedEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pioneer select entities from a config entry."""
    coordinator: PioneerEiscpCoordinator = entry.runtime_data
    async_add_entities(
        [
            PioneerListeningModeSelect(coordinator, entry),
            PioneerHdmiOutputSelect(coordinator, entry),
        ]
    )


class PioneerListeningModeSelect(PioneerConnectedEntity, SelectEntity):
    """Listening mode select entity (LMD)."""

    _attr_name = "Listening Mode"
    _attr_icon = "mdi:surround-sound"

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_listening_mode"
        self._attr_options = sorted(set(LISTENING_MODES.values()))

    @property
    def current_option(self) -> str | None:
        """Return current listening mode."""
        mode = self.coordinator.data.listening_mode
        if mode and mode in self._attr_options:
            return mode
        return mode

    async def async_select_option(self, option: str) -> None:
        """Change listening mode."""
        code = LISTENING_MODE_TO_CODE.get(option)
        if code is None:
            _LOGGER.warning("Unknown listening mode: %s", option)
            return
        await self.coordinator.receiver.set_listening_mode(code)


class PioneerHdmiOutputSelect(PioneerConnectedEntity, SelectEntity):
    """HDMI output selection (HDO) — architecture placeholder.

    Options will be populated from receiver responses in a future pass.
    """

    _attr_name = "HDMI Output"
    _attr_icon = "mdi:hdmi-port"
    _attr_options = ["main", "sub", "main_sub"]
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_hdmi_output"

    @property
    def current_option(self) -> str | None:
        """Return current HDMI output setting."""
        value = self.coordinator.data.hdmi_output
        if value is None:
            return None
        # Map raw codes when known; otherwise expose raw value if in options.
        return value if value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        """Change HDMI output (raw command mapping TBD per model)."""
        _LOGGER.debug("HDMI output change requested: %s (not yet mapped)", option)
