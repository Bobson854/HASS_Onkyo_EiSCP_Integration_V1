"""Setup-time eISCP receiver validation (no Home Assistant dependencies)."""

from __future__ import annotations

import socket
import time
from typing import Final

from .const import CMD_POWER, QUERY_SUFFIX, VALIDATION_READ_TIMEOUT, VALIDATION_TIMEOUT
from .protocol.framing import EiscpFrame, build_packet, parse_packets

VALIDATION_QUERY: Final[str] = f"{CMD_POWER}{QUERY_SUFFIX}"
_VALID_PWR_STATES: Final[frozenset[str]] = frozenset({"00", "01"})


class EiscpValidationError(Exception):
    """Base class for setup validation failures."""


class EiscpConnectionError(EiscpValidationError):
    """TCP connection could not be established."""


class EiscpInvalidResponseError(EiscpValidationError):
    """Connected endpoint did not return a valid eISCP PWR response."""


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


def validate_eiscp_receiver(
    host: str,
    port: int,
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
        EiscpConnectionError: TCP connect/send failure or connection dropped.
        EiscpInvalidResponseError: No valid eISCP PWR response within timeout.
    """
    sock: socket.socket | None = None
    try:
        sock = socket.create_connection((host, port), timeout=connect_timeout)
        sock.settimeout(0.5)
        sock.sendall(build_packet(VALIDATION_QUERY))

        buffer = b""
        deadline = time.monotonic() + read_timeout

        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                frame = validate_pwr_response_buffer(buffer)
                if frame is not None:
                    return frame.raw_iscp
                continue

            if not chunk:
                msg = "Connection closed before eISCP response"
                raise EiscpInvalidResponseError(msg)

            buffer += chunk
            frame = validate_pwr_response_buffer(buffer)
            if frame is not None:
                return frame.raw_iscp

        msg = "Timed out waiting for eISCP PWR response"
        raise EiscpInvalidResponseError(msg)

    except EiscpValidationError:
        raise
    except OSError as err:
        raise EiscpConnectionError(str(err)) from err
    finally:
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
