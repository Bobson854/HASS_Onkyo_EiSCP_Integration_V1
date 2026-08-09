"""Listening-mode current-state resolution (LMD + IFA fallback)."""

from __future__ import annotations

from ..const import LISTENING_MODES

SOURCE_IFA_OUTPUT_FORMAT = "ifa_output_format"
SOURCE_LMD_MAPPING = "lmd_mapping"
SOURCE_RAW_FALLBACK = "raw_fallback"

_UNHELPFUL_IFA_OUTPUTS = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "not available",
        "unknown",
        "unavailable",
    }
)


def normalize_lmd_code(code: str | None) -> str | None:
    """Normalize a raw LMD response code."""
    if code is None:
        return None
    normalized = code.strip().upper()
    return normalized or None


def format_static_listening_mode(name: str) -> str:
    """Format a static protocol listening-mode label for display."""
    return name.replace("_", " ").title()


def lookup_static_lmd_mapping(code: str | None) -> str | None:
    """Return a human-readable label from the static protocol table."""
    normalized = normalize_lmd_code(code)
    if not normalized:
        return None

    static_key = normalized if normalized in LISTENING_MODES else normalized[:2]
    static_name = LISTENING_MODES.get(static_key)
    if static_name is None:
        return None
    return format_static_listening_mode(static_name)


def is_meaningful_ifa_output_format(value: str | None) -> bool:
    """Return True when IFA output format can label an unknown LMD code."""
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return stripped.lower() not in _UNHELPFUL_IFA_OUTPUTS


def resolve_listening_mode_display(
    code: str | None,
    *,
    ifa_output_format: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve the human-readable current listening mode and its source."""
    normalized = normalize_lmd_code(code)
    if not normalized:
        return None, None

    static_name = lookup_static_lmd_mapping(normalized)
    if static_name is not None:
        return static_name, SOURCE_LMD_MAPPING

    if is_meaningful_ifa_output_format(ifa_output_format):
        assert ifa_output_format is not None
        return ifa_output_format.strip(), SOURCE_IFA_OUTPUT_FORMAT

    return normalized, SOURCE_RAW_FALLBACK
