"""Sensor platform for Pioneer eISCP audio/video information."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PioneerEiscpCoordinator
from .entity import PioneerEiscpEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pioneer sensors from a config entry."""
    coordinator: PioneerEiscpCoordinator = entry.runtime_data
    async_add_entities(
        [
            PioneerAudioInputSensor(coordinator, entry),
            PioneerAudioOutputSensor(coordinator, entry),
            PioneerConnectionSensor(coordinator, entry),
        ]
    )


class PioneerAudioInputSensor(PioneerEiscpEntity, SensorEntity):
    """Summarized audio input information from IFA."""

    _attr_name = "Audio Input"
    _attr_icon = "mdi:audio-input-rca"

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_audio_input"

    @property
    def native_value(self) -> str | None:
        """Return a concise summary of audio input."""
        audio = self.coordinator.data.audio
        if not audio.input_port and not audio.input_format:
            return None
        parts = [p for p in (audio.input_port, audio.input_format) if p]
        return " / ".join(parts) if parts else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return structured IFA input fields."""
        audio = self.coordinator.data.audio
        return {
            "input_port": audio.input_port,
            "input_format": audio.input_format,
            "input_sample_rate": audio.input_sample_rate,
            "input_channels": audio.input_channels,
        }


class PioneerAudioOutputSensor(PioneerEiscpEntity, SensorEntity):
    """Summarized audio output information from IFA."""

    _attr_name = "Audio Output"
    _attr_icon = "mdi:speaker"

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_audio_output"

    @property
    def native_value(self) -> str | None:
        """Return a concise summary of audio output."""
        audio = self.coordinator.data.audio
        if not audio.output_format and not audio.output_channels:
            return None
        parts = [p for p in (audio.output_format, audio.output_channels) if p]
        return " / ".join(parts) if parts else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return structured IFA output fields."""
        audio = self.coordinator.data.audio
        return {
            "output_format": audio.output_format,
            "output_channels": audio.output_channels,
            "output_sample_rate": audio.output_sample_rate,
            "raw": audio.raw or None,
        }


class PioneerConnectionSensor(PioneerEiscpEntity, SensorEntity):
    """Connection status sensor."""

    _attr_name = "Connection"
    _attr_icon = "mdi:lan-connect"

    def __init__(
        self,
        coordinator: PioneerEiscpCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_connection"

    @property
    def native_value(self) -> str:
        """Return connection status."""
        return "connected" if self.coordinator.receiver.connected else "disconnected"
