"""ISCP message and information-field parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .volume import parse_mvl_parameter

# Expected IFA field order (positional; missing fields tolerated).
_IFA_FIELD_NAMES: tuple[str, ...] = (
    "input_port",
    "input_format",
    "input_sample_rate",
    "input_channels",
    "output_format",
    "output_channels",
    "output_sample_rate",
)


@dataclass(slots=True)
class AudioInformation:
    """Structured IFA audio-information state."""

    input_port: str | None = None
    input_format: str | None = None
    input_sample_rate: str | None = None
    input_channels: str | None = None
    output_format: str | None = None
    output_channels: str | None = None
    output_sample_rate: str | None = None
    raw: str = ""
    fields: list[str] = field(default_factory=list)
    extra_fields: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "input_port": self.input_port,
            "input_format": self.input_format,
            "input_sample_rate": self.input_sample_rate,
            "input_channels": self.input_channels,
            "output_format": self.output_format,
            "output_channels": self.output_channels,
            "output_sample_rate": self.output_sample_rate,
            "raw": self.raw,
            "fields": self.fields,
            "extra_fields": self.extra_fields,
        }


@dataclass(slots=True)
class VideoInformation:
    """Structured IFV video-information state."""

    raw: str = ""
    fields: list[str] = field(default_factory=list)
    extra_fields: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "raw": self.raw,
            "fields": self.fields,
            "extra_fields": self.extra_fields,
        }


def parse_iscp_command(raw: str) -> tuple[str, str]:
    """Split a raw ISCP body into command code and parameter."""
    if len(raw) < 3:
        return raw, ""
    return raw[:3], raw[3:]


def _split_information_fields(parameter: str) -> list[str]:
    """Split comma-separated information fields, preserving empty trailing fields."""
    if not parameter:
        return []
    parts = [part.strip() for part in parameter.split(",")]
    if len(parts) > 1 and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _assign_named_fields(
    field_names: tuple[str, ...],
    parts: list[str],
    raw: str,
    cls: type,
) -> AudioInformation | VideoInformation:
    """Map positional fields onto a dataclass, storing extras separately."""
    assigned: dict[str, str | None] = {}
    for index, name in enumerate(field_names):
        assigned[name] = parts[index] if index < len(parts) else None

    extra = parts[len(field_names) :] if len(parts) > len(field_names) else []

    return cls(
        **assigned,
        raw=raw,
        fields=parts,
        extra_fields=extra,
    )


def parse_audio_information(parameter: str) -> AudioInformation:
    """Parse IFA parameter text into structured audio information."""
    parts = _split_information_fields(parameter)
    return _assign_named_fields(_IFA_FIELD_NAMES, parts, parameter, AudioInformation)  # type: ignore[return-value]


def parse_video_information(parameter: str) -> VideoInformation:
    """Parse IFV parameter text, preserving positional fields only."""
    parts = _split_information_fields(parameter)
    return VideoInformation(raw=parameter, fields=parts, extra_fields=[])


def parse_power(parameter: str) -> bool | None:
    """Parse PWR parameter (00=off, 01=on)."""
    if parameter in ("00", "0"):
        return False
    if parameter in ("01", "1"):
        return True
    return None


def parse_mute(parameter: str) -> bool | None:
    """Parse AMT parameter (00=off/unmuted, 01=on/muted)."""
    if parameter in ("00", "0"):
        return False
    if parameter in ("01", "1"):
        return True
    return None


def parse_volume_hex(parameter: str) -> int | None:
    """Deprecated alias; Pioneer MVL uses decimal absolute volume."""
    return parse_mvl_parameter(parameter)


def parse_input_code(parameter: str) -> str | None:
    """Parse SLI/SLZ input selector code."""
    parameter = parameter.strip().upper()
    if len(parameter) >= 2:
        return parameter[:2]
    return None
