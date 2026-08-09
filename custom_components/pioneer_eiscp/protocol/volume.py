"""Main-zone absolute volume model for Pioneer/Onkyo-class eISCP receivers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class VolumeState:
    """Structured main-zone volume derived from MVL and NRI volmax."""

    raw_parameter: str = ""
    absolute_volume: int | None = None
    volume_reference: int | None = None

    @property
    def volume_db(self) -> float | None:
        """Return display dB relative to the receiver volume reference."""
        if self.absolute_volume is None or self.volume_reference is None:
            return None
        return float(self.absolute_volume - self.volume_reference)

    def normalized_level(self, fallback_reference: int = 100) -> float | None:
        """Return Home Assistant volume_level (0..1) using the usable range."""
        if self.absolute_volume is None:
            return None
        reference = self.volume_reference or fallback_reference
        if reference <= 0:
            return None
        return max(0.0, min(1.0, self.absolute_volume / reference))

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_parameter": self.raw_parameter,
            "absolute_volume": self.absolute_volume,
            "volume_reference": self.volume_reference,
            "volume_db": self.volume_db,
        }


def parse_mvl_parameter(parameter: str) -> int | None:
    """Parse MVL parameter as absolute volume (decimal), not hexadecimal.

    Live Pioneer VSX-1131 example: ``MVL52`` -> absolute volume 52, not 0x52 (=82).
    """
    parameter = parameter.strip()
    if not parameter:
        return None
    if len(parameter) >= 2 and all(c in "0123456789ABCDEFabcdef" for c in parameter[:2]):
        # Prefer decimal interpretation for two-digit numeric payloads.
        if parameter[:2].isdigit():
            return int(parameter[:2], 10)
        # Legacy hex fallback for non-decimal hex payloads.
        try:
            return int(parameter[:2], 16)
        except ValueError:
            return None
    try:
        return int(parameter, 10)
    except ValueError:
        return None


def format_mvl_parameter(absolute_volume: int) -> str:
    """Format an absolute volume value for outbound MVL commands."""
    level = max(0, min(99, absolute_volume))
    return f"{level:02d}"


def build_volume_state(
    parameter: str,
    *,
    volume_reference: int | None = None,
) -> VolumeState:
    """Build structured volume state from a raw MVL parameter."""
    return VolumeState(
        raw_parameter=parameter.strip(),
        absolute_volume=parse_mvl_parameter(parameter),
        volume_reference=volume_reference,
    )
