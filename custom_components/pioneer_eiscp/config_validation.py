"""Setup-time eISCP receiver validation (no Home Assistant dependencies)."""

from __future__ import annotations

import logging
import socket
import time
from typing import Final

from .const import (
    CMD_POWER,
    QUERY_SUFFIX,
    VALIDATION_READ_TIMEOUT,
    VALIDATION_TIMEOUT,
    normalize_port,
)
from .protocol.framing import EiscpFrame, build_packet, parse_packets

_LOGGER = logging.getLogger(__name__)

VALIDATION_QUERY: Final[str] = f"{CMD_POWER}{QUERY_SUFFIX}"
_VALID_PWR_STATES: Final[frozenset[str]] = frozenset({"00", "01"})

# Validation failure stages (for logging/diagnostics).
STAGE_CONNECT: Final = "connect"
STAGE_SEND: Final = "send"
STAGE_RECV: Final = "recv"
STAGE_TIMEOUT: Final = "timeout"
STAGE_PARSE: Final = "parse"


class EiscpValidationError(Exception):
    """Base class for setup validation failures."""

    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


class EiscpConnectionError(EiscpValidationError):
    """TCP connect or send failure (includes reset during send)."""


class EiscpInvalidResponseError(EiscpValidationError):
    """Connected but no valid eISCP PWR response (closed, timeout, or unparseable)."""


def is_valid_pwr_response(frame: EiscpFrame) -> bool:
    """Return True if the frame is a plausible PWR query response."""
    return frame.command == CMD_POWER and frame.parameter in _VALID_PWR_STATES


def validate_pwr_response_buffer(buffer: bytes) -> EiscpFrame | None:
    """Return the first valid PWR frame found in a receive buffer."""
    frames, _remainder = parse_packets(buffer)
    for frame in frames:
        if is_valid_pwr_response(frame):
            return frame
    return None


def _log_tx_query(host: str, port: int) -> None:
    packet = build_packet(VALIDATION_QUERY)
    _LOGGER.debug(
        "Validation TX %s:%s query=%s packet_len=%d payload=%r",
        host,
        port,
        VALIDATION_QUERY,
        len(packet),
        packet[16:],
    )


def validate_eiscp_receiver(
    host: str,
    port: int | float | str,
    *,
    connect_timeout: float = VALIDATION_TIMEOUT,
    read_timeout: float = VALIDATION_READ_TIMEOUT,
) -> str:
    """Confirm the target responds to a read-only PWRQSTN with a valid eISCP frame.

    Opens a temporary connection, sends ``PWRQSTN``, waits for a framed ``PWR00``
    or ``PWR01`` response, then closes the connection. Does not send state-changing
    commands.

    Returns the raw ISCP body of the PWR response.

    Raises:
        EiscpConnectionError: TCP connect or send failure.
        EiscpInvalidResponseError: Peer closed, timeout, or unparseable response.
    """
    sock: socket.socket | None = None
    buffer = b""

    try:
        try:
            port = normalize_port(port)
        except ValueError as err:
            msg = f"Invalid port: {err}"
            raise EiscpConnectionError(msg, stage=STAGE_CONNECT) from err

        try:
            sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as err:
            msg = f"TCP connect failed: {err}"
            raise EiscpConnectionError(msg, stage=STAGE_CONNECT) from err

        sock.settimeout(0.5)
        _log_tx_query(host, port)

        try:
            sock.sendall(build_packet(VALIDATION_QUERY))
        except OSError as err:
            msg = f"Send failed after TCP connect: {err}"
            raise EiscpConnectionError(msg, stage=STAGE_SEND) from err

        deadline = time.monotonic() + read_timeout

        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                frame = validate_pwr_response_buffer(buffer)
                if frame is not None:
                    _LOGGER.debug(
                        "Validation RX %s:%s response=%s bytes=%d",
                        host,
                        port,
                        frame.raw_iscp,
                        len(buffer),
                    )
                    return frame.raw_iscp
                continue

            if not chunk:
                msg = "Peer closed connection before eISCP PWR response"
                raise EiscpInvalidResponseError(msg, stage=STAGE_RECV)

            buffer += chunk
            _LOGGER.debug(
                "Validation RX chunk %s:%s bytes=%d total=%d",
                host,
                port,
                len(chunk),
                len(buffer),
            )
            frame = validate_pwr_response_buffer(buffer)
            if frame is not None:
                _LOGGER.debug(
                    "Validation RX %s:%s response=%s bytes=%d",
                    host,
                    port,
                    frame.raw_iscp,
                    len(buffer),
                )
                return frame.raw_iscp

        if buffer:
            msg = "Received data but no valid eISCP PWR response"
            raise EiscpInvalidResponseError(msg, stage=STAGE_PARSE)

        msg = "Timed out waiting for eISCP PWR response"
        raise EiscpInvalidResponseError(msg, stage=STAGE_TIMEOUT)

    except EiscpValidationError:
        raise
    finally:
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
