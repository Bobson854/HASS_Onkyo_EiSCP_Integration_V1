"""ISCP message and information-field parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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

# Expected IFV field order (defensive; firmware may vary).
_IFV_FIELD_NAMES: tuple[str, ...] = (
    "video_input",
    "video_output",
    "resolution",
    "color_format",
    "color_depth",
    "hdcp",
    "hdr",
    "aspect",
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

    video_input: str | None = None
    video_output: str | None = None
    resolution: str | None = None
    color_format: str | None = None
    color_depth: str | None = None
    hdcp: str | None = None
    hdr: str | None = None
    aspect: str | None = None
    raw: str = ""
    fields: list[str] = field(default_factory=list)
    extra_fields: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "video_input": self.video_input,
            "video_output": self.video_output,
            "resolution": self.resolution,
            "color_format": self.color_format,
            "color_depth": self.color_depth,
            "hdcp": self.hdcp,
            "hdr": self.hdr,
            "aspect": self.aspect,
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
    # Split on comma; strip whitespace from each segment.
    parts = [part.strip() for part in parameter.split(",")]
    # Drop a single trailing empty field from a trailing comma.
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
    """Parse IFA parameter text into structured audio information.

    Example parameter::

        OPTICAL 2,Dolby D,48 kHz,5.1 ch,Dolby Digital,3.1 ch,48 kHz,

    The parser is positional and tolerant of missing or extra fields.
    """
    parts = _split_information_fields(parameter)
    return _assign_named_fields(_IFA_FIELD_NAMES, parts, parameter, AudioInformation)  # type: ignore[return-value]


def parse_video_information(parameter: str) -> VideoInformation:
    """Parse IFV parameter text into structured video information.

    Field order may vary by firmware; this parser uses a best-effort
    positional mapping and preserves raw/extra fields.
    """
    parts = _split_information_fields(parameter)
    return _assign_named_fields(_IFV_FIELD_NAMES, parts, parameter, VideoInformation)  # type: ignore[return-value]


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
    """Parse MVL hex parameter to 0-100 integer."""
    parameter = parameter.strip()
    if not parameter:
        return None
    try:
        value = int(parameter, 16)
    except ValueError:
        return None
    return max(0, min(100, value))


def parse_input_code(parameter: str) -> str | None:
    """Parse SLI/SLZ input selector code."""
    parameter = parameter.strip().upper()
    if len(parameter) >= 2:
        return parameter[:2]
    return None
