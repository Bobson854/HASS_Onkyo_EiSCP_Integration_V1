"""eISCP packet framing and ISCP message extraction."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator

_HEADER_SIZE = 16
_MAGIC = b"ISCP"
_UNIT_TYPE = "1"
_START_CHAR = "!"
_EOF = "\x1a"
_TERMINATORS = ("\r", "\n")


@dataclass(frozen=True, slots=True)
class EiscpFrame:
    """A decoded eISCP frame."""

    command: str
    parameter: str
    raw_iscp: str

    @property
    def full_command(self) -> str:
        """Return the 3-letter ISCP command code."""
        return self.command

    @property
    def payload(self) -> str:
        """Return parameter bytes as a string."""
        return self.parameter


def build_packet(iscp_body: str) -> bytes:
    """Wrap an ISCP body (e.g. ``PWRQSTN``) in an eISCP TCP packet."""
    message = f"{_START_CHAR}{_UNIT_TYPE}{iscp_body}{_EOF}\r"
    message_bytes = message.encode("utf-8")
    header = struct.pack(
        "!4sIIB3s",
        _MAGIC,
        _HEADER_SIZE,
        len(message_bytes),
        0x01,
        b"\x00\x00\x00",
    )
    return header + message_bytes


def parse_iscp_message(data: str) -> str:
    """Extract the ISCP body from a decoded eISCP data section."""
    if len(data) < 4 or not data.startswith(f"{_START_CHAR}{_UNIT_TYPE}"):
        msg = f"Invalid ISCP message prefix: {data!r}"
        raise ValueError(msg)

    end = len(data)
    while end > 2 and data[end - 1] in _TERMINATORS:
        end -= 1
    if end > 2 and data[end - 1] == _EOF:
        end -= 1

    return data[2:end]


def _frame_from_iscp(iscp_body: str) -> EiscpFrame:
    if len(iscp_body) < 3:
        return EiscpFrame(command=iscp_body, parameter="", raw_iscp=iscp_body)
    return EiscpFrame(
        command=iscp_body[:3],
        parameter=iscp_body[3:],
        raw_iscp=iscp_body,
    )


def parse_packets(buffer: bytes) -> tuple[list[EiscpFrame], bytes]:
    """Parse complete eISCP packets from a byte buffer.

    Returns a list of decoded frames and any remaining partial data.
    """
    frames: list[EiscpFrame] = []
    offset = 0
    length = len(buffer)

    while offset + _HEADER_SIZE <= length:
        magic, header_size, data_size, _version, _reserved = struct.unpack_from(
            "!4sIIB3s",
            buffer,
            offset,
        )
        if magic != _MAGIC or header_size < _HEADER_SIZE:
            # Resync: skip one byte and retry.
            offset += 1
            continue

        total = header_size + data_size
        if offset + total > length:
            break

        data_start = offset + header_size
        data_end = data_start + data_size
        raw_data = buffer[data_start:data_end].decode("utf-8", errors="replace")

        try:
            iscp_body = parse_iscp_message(raw_data)
        except ValueError:
            offset += 1
            continue

        frames.append(_frame_from_iscp(iscp_body))
        offset += total

    return frames, buffer[offset:]


def iter_frames_from_stream(chunks: Iterator[bytes]) -> Iterator[EiscpFrame]:
    """Incrementally parse frames from a stream of byte chunks."""
    buffer = b""
    for chunk in chunks:
        buffer += chunk
        frames, buffer = parse_packets(buffer)
        yield from frames
