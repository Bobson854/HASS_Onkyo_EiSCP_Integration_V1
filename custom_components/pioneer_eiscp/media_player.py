"""Media player platform for Pioneer eISCP main zone."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PioneerEiscpCoordinator
from .entity import PioneerConnectedEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pioneer media player from a config entry."""
    coordinator: PioneerEiscpCoordinator = entry.runtime_data
    async_add_entities([PioneerMainZoneMediaPlayer(coordinator, entry)])


class PioneerMainZoneMediaPlayer(PioneerConnectedEntity, MediaPlayerEntity):
    """Main zone media player entity."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_name = "Main Zone"
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the media player."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_main_media_player"

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        power = self.coordinator.data.main.power
        if power is True:
            return MediaPlayerState.ON
        if power is False:
            return MediaPlayerState.OFF
        return MediaPlayerState.UNKNOWN

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        return self.coordinator.data.main.volume_state.normalized_level()

    @property
    def is_volume_muted(self) -> bool | None:
        """Boolean if volume is currently muted."""
        return self.coordinator.data.main.mute

    @property
    def source_list(self) -> list[str]:
        """List of available input sources."""
        return sorted(set(self.coordinator.receiver.get_input_source_map().values()))

    @property
    def source(self) -> str | None:
        """Current input source."""
        code = self.coordinator.data.main.input_code
        if code is None:
            return None
        source_map = self.coordinator.receiver.get_input_source_map()
        return source_map.get(code, f"0x{code}")

    async def async_turn_on(self) -> None:
        """Turn the receiver on."""
        await self.coordinator.receiver.set_power(True)

    async def async_turn_off(self) -> None:
        """Turn the receiver off."""
        await self.coordinator.receiver.set_power(False)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self.coordinator.receiver.set_volume_level(volume)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self.coordinator.receiver.set_mute(mute)

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        code = self.coordinator.receiver.get_input_source_reverse_map().get(source)
        if code is None:
            _LOGGER.warning("Unknown source: %s", source)
            return
        await self.coordinator.receiver.set_input(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic-friendly attributes (not full protocol dump)."""
        audio = self.coordinator.data.audio
        volume_state = self.coordinator.data.main.volume_state
        return {
            "listening_mode": self.coordinator.data.listening_mode,
            "listening_mode_code": self.coordinator.data.listening_mode_code,
            "listening_mode_source": self.coordinator.data.listening_mode_source,
            "audio_input_port": audio.input_port,
            "audio_output_format": audio.output_format,
            "connected": self.coordinator.receiver.connected,
            "volume_raw": volume_state.raw_parameter,
            "volume_reference": volume_state.volume_reference,
            "volume_db": volume_state.volume_db,
            "absolute_volume": volume_state.absolute_volume,
        }
