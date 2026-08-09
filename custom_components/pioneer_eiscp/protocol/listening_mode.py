"""Listening-mode current-state resolution (LMD + IFA fallback)."""

from __future__ import annotations

from ..const import LISTENING_MODES

SOURCE_IFA_OUTPUT_FORMAT = "ifa_output_format"
SOURCE_LMD_MAPPING = "lmd_mapping"
SOURCE_RAW_FALLBACK = "raw_fallback"

SELECT_MATCH_EXACT = "exact_label"
SELECT_MATCH_SEMANTIC = "semantic_family"

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


def normalize_select_label(value: str) -> str:
    """Normalize a select option or listening-mode label for comparison."""
    label = value.strip().lower()
    if label.startswith("lmd "):
        label = label[4:].strip()
    return " ".join(label.split())


def format_listening_mode_option_label(control_id: str) -> str:
    """Convert an NRI listening-mode control id to a user-facing option label."""
    label = control_id.strip()
    if label.upper().startswith("LMD "):
        label = label[4:].strip()
    if normalize_select_label(label) == "stereo g":
        return "Stereo"
    return label


def build_user_listening_mode_map(nri_control_map: dict[str, str]) -> dict[str, str]:
    """Map user-facing listening-mode option labels to command codes."""
    options: dict[str, str] = {}
    for control_id, code in nri_control_map.items():
        label = format_listening_mode_option_label(control_id)
        options[label] = code
    return options


# Normalized exact receiver state -> normalized selectable option label.
_SEMANTIC_STATE_TO_OPTION: tuple[tuple[str, str], ...] = (
    ("auto surround", "auto/direct"),
    ("direct", "auto/direct"),
    ("pure direct", "pure direct"),
    ("pure audio", "pure direct"),
    ("stereo", "stereo"),
    ("surround", "surround"),
)


def resolve_select_option(
    listening_mode: str | None,
    listening_mode_code: str | None,
    options: list[str],
) -> tuple[str | None, str | None]:
    """Map exact receiver listening state to a selectable NRI command option."""
    del listening_mode_code  # never hardcode state codes such as FF or 40

    if not options:
        return None, None

    normalized_options = {normalize_select_label(option): option for option in options}

    if not listening_mode:
        return None, None

    normalized_state = normalize_select_label(listening_mode)

    if normalized_state in normalized_options:
        return normalized_options[normalized_state], SELECT_MATCH_EXACT

    for state_key, option_key in _SEMANTIC_STATE_TO_OPTION:
        if normalized_state == state_key and option_key in normalized_options:
            return normalized_options[option_key], SELECT_MATCH_SEMANTIC

    return None, None
