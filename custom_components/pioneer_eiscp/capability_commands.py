"""Read-only eISCP capability probe command reference.

Only commands listed in SAFE_TO_PROBE may be sent by the capability probe.
See miracle2k/onkyo-eiscp command YAML for full protocol reference.
"""

from __future__ import annotations

from typing import Final

from .const import (
    CMD_AUDIO_INFO,
    CMD_INPUT,
    CMD_LISTENING_MODE,
    CMD_MUTE,
    CMD_POWER,
    CMD_VIDEO_INFO,
    CMD_VOLUME,
    QUERY_SUFFIX,
)

# --- Enabled for capability probe (read-only QSTN queries) ---

SAFE_TO_PROBE: Final[tuple[str, ...]] = (
    f"{CMD_POWER}{QUERY_SUFFIX}",
    f"{CMD_VOLUME}{QUERY_SUFFIX}",
    f"{CMD_MUTE}{QUERY_SUFFIX}",
    f"{CMD_INPUT}{QUERY_SUFFIX}",
    f"{CMD_LISTENING_MODE}{QUERY_SUFFIX}",
    f"{CMD_AUDIO_INFO}{QUERY_SUFFIX}",
    f"{CMD_VIDEO_INFO}{QUERY_SUFFIX}",
    "NRIQSTN",
)

# --- Candidate queries found in onkyo-eiscp; NOT enabled until verified ---

NEEDS_REVIEW: Final[tuple[str, ...]] = (
    "ECNQSTN",
    "MVOQSTN",
    "HOAQSTN",
    "TFRQSTN",
    "HDOQSTN",
    "ZPWQSTN",
    "SLZQSTN",
    "ZVLQSTN",
    "SPIQSTN",
    "sCFQSTN",
    "NTCQSTN",
    "NFNQSTN",
)

# --- Must never be sent by probe ---

STATE_CHANGING_DO_NOT_PROBE: Final[tuple[str, ...]] = (
    "PWR00",
    "PWR01",
    "MVLUP",
    "MVLDOWN",
    "AMT00",
    "AMT01",
    "SLI00",
    "LMD00",
    "MVOUP",
    "MVODOWN",
    "ZPW00",
    "ZPW01",
)

PROBE_COMMAND_DELAY: Final[float] = 0.25
PROBE_RESPONSE_TIMEOUT: Final[float] = 3.0
