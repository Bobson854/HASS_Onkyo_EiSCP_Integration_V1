"""Capability probe sequencing, correlation, and snapshot assembly."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..capability_commands import (
    PROBE_COMMAND_DELAY,
    PROBE_RESPONSE_TIMEOUT,
    SAFE_TO_PROBE,
    STATE_CHANGING_DO_NOT_PROBE,
)
from ..const import (
    CMD_AUDIO_INFO,
    CMD_INPUT,
    CMD_LISTENING_MODE,
    CMD_MUTE,
    CMD_POWER,
    CMD_VIDEO_INFO,
    CMD_VOLUME,
)
from .framing import EiscpFrame
from .nri_parser import parse_nri_response
from .parsers import (
    parse_audio_information,
    parse_input_code,
    parse_mute,
    parse_power,
    parse_video_information,
    parse_volume_hex,
)

_LOGGER = logging.getLogger(__name__)

SendFn = Callable[[str], Awaitable[None]]
WaitFn = Callable[[str, float], Awaitable[EiscpFrame | None]]


@dataclass
class ProbeResponseRecord:
    """Single command response captured during a probe."""

    query: str
    command: str
    raw: str | None = None
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    received_at: str | None = None
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "command": self.command,
            "raw": self.raw,
            "parsed": self.parsed,
            "parse_error": self.parse_error,
            "received_at": self.received_at,
            "timed_out": self.timed_out,
        }


@dataclass
class CapabilitySnapshot:
    """JSON-serializable capability probe results."""

    last_probe: str | None = None
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)
    timeouts: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    unknown: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_probe": self.last_probe,
            "responses": self.responses,
            "unsupported": self.unsupported,
            "timeouts": self.timeouts,
            "parse_errors": self.parse_errors,
            "unknown": self.unknown,
        }

    def to_json(self) -> str:
        """Return JSON representation (validates serializability)."""
        return json.dumps(self.as_dict(), default=str)


def command_prefix(query: str) -> str:
    """Return the expected 3-letter response command for a QSTN query."""
    return query[:3]


def parse_probe_response(command: str, frame: EiscpFrame) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a probe response frame into a diagnostic dict."""
    param = frame.parameter

    try:
        if command == CMD_POWER:
            return {"power": parse_power(param), "parameter": param}, None
        if command == CMD_VOLUME:
            return {"volume": parse_volume_hex(param), "parameter": param}, None
        if command == CMD_MUTE:
            return {"mute": parse_mute(param), "parameter": param}, None
        if command == CMD_INPUT:
            return {"input_code": parse_input_code(param), "parameter": param}, None
        if command == CMD_LISTENING_MODE:
            code = param.strip().upper()[:2] if param else None
            return {"listening_mode_code": code, "parameter": param}, None
        if command == CMD_AUDIO_INFO:
            audio = parse_audio_information(param)
            return {"audio": audio.as_dict(), "parameter": param}, None
        if command == CMD_VIDEO_INFO:
            video = parse_video_information(param)
            return {"video": video.as_dict(), "parameter": param}, None
        if command == "NRI":
            nri = parse_nri_response(param if param else frame.raw_iscp[3:])
            return {
                "raw": nri["raw"],
                "parsed": nri["parsed"],
                "parse_error": nri["parse_error"],
            }, nri["parse_error"]
        return {"parameter": param}, None
    except Exception as err:  # noqa: BLE001
        return None, str(err)


def _validate_probe_queries(queries: tuple[str, ...]) -> None:
    """Ensure probe only uses approved read-only queries."""
    blocked = set(STATE_CHANGING_DO_NOT_PROBE)
    for query in queries:
        if query in blocked:
            msg = f"Refusing state-changing probe command: {query}"
            raise ValueError(msg)
        if not query.endswith("QSTN"):
            msg = f"Probe query must be read-only (QSTN): {query}"
            raise ValueError(msg)


async def run_capability_probe(
    send: SendFn,
    wait: WaitFn,
    *,
    queries: tuple[str, ...] = SAFE_TO_PROBE,
    delay: float = PROBE_COMMAND_DELAY,
    timeout: float = PROBE_RESPONSE_TIMEOUT,
) -> CapabilitySnapshot:
    """Run a sequential read-only capability probe."""
    _validate_probe_queries(queries)

    snapshot = CapabilitySnapshot(last_probe=datetime.now(UTC).isoformat())
    response_count = 0

    for query in queries:
        expected = command_prefix(query)
        _LOGGER.debug("Capability probe TX %s", query)

        await send(query)
        frame = await wait(expected, timeout)

        if frame is None:
            _LOGGER.debug("Capability probe timeout waiting for %s", expected)
            snapshot.timeouts.append(query)
            snapshot.unsupported.append(query)
            snapshot.responses[expected] = ProbeResponseRecord(
                query=query,
                command=expected,
                timed_out=True,
            ).as_dict()
            await asyncio.sleep(delay)
            continue

        preview = frame.raw_iscp[:80]
        if len(frame.raw_iscp) > 80:
            preview += "..."
        _LOGGER.debug("Capability probe RX %s", preview)

        parsed, parse_error = parse_probe_response(expected, frame)
        record = ProbeResponseRecord(
            query=query,
            command=expected,
            raw=frame.raw_iscp,
            parsed=parsed,
            parse_error=parse_error,
            received_at=datetime.now(UTC).isoformat(),
        )
        snapshot.responses[expected] = record.as_dict()
        response_count += 1

        if parse_error:
            snapshot.parse_errors.append(f"{expected}: {parse_error}")

        await asyncio.sleep(delay)

    _LOGGER.info(
        "Capability probe completed: %d responses, %d timeouts, %d parse errors",
        response_count,
        len(snapshot.timeouts),
        len(snapshot.parse_errors),
    )
    return snapshot
