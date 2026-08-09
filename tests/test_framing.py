"""Tests for eISCP framing and packet parsing."""

import struct

from framing import (
    build_packet,
    parse_iscp_message,
    parse_packets,
)


def _packet_payload(packet: bytes) -> bytes:
    """Return the eISCP data portion (after the 16-byte header)."""
    _magic, header_size, data_size, _version, _reserved = struct.unpack(
        "!4sIIB3s", packet[:16]
    )
    assert header_size == 16
    assert data_size == len(packet) - header_size
    return packet[header_size:]


class TestBuildPacket:
    """eISCP packet encoding — exact outbound byte layout."""

    def test_build_pwr_query_exact_bytes(self) -> None:
        packet = build_packet("PWRQSTN")
        magic, header_size, data_size, version, _reserved = struct.unpack(
            "!4sIIB3s", packet[:16]
        )
        payload = _packet_payload(packet)

        assert magic == b"ISCP"
        assert header_size == 16
        assert version == 1
        assert payload == b"!1PWRQSTN\r"
        assert b"\x1a" not in payload
        assert data_size == len(payload)
        assert data_size == 10

    def test_build_mvl_command_exact_bytes(self) -> None:
        packet = build_packet("MVL1E")
        payload = _packet_payload(packet)
        _magic, _header_size, data_size, _version, _reserved = struct.unpack(
            "!4sIIB3s", packet[:16]
        )

        assert payload == b"!1MVL1E\r"
        assert b"\x1a" not in payload
        assert data_size == len(payload)

    def test_header_data_size_excludes_header(self) -> None:
        packet = build_packet("SLI23")
        assert len(packet) == 16 + 8  # "!1SLI23\r"
        _magic, header_size, data_size, _version, _reserved = struct.unpack(
            "!4sIIB3s", packet[:16]
        )
        assert header_size == 16
        assert data_size == 8
        assert packet[16:] == b"!1SLI23\r"


class TestParseIscpMessage:
    """ISCP message extraction from received data (multiple terminators)."""

    def test_parse_with_cr_only(self) -> None:
        raw = "!1PWR01\r"
        assert parse_iscp_message(raw) == "PWR01"

    def test_parse_with_eof_cr(self) -> None:
        raw = "!1MVL14\x1a\r"
        assert parse_iscp_message(raw) == "MVL14"

    def test_parse_with_eof_crlf(self) -> None:
        raw = "!1AMT00\x1a\r\n"
        assert parse_iscp_message(raw) == "AMT00"

    def test_parse_with_lf_only(self) -> None:
        raw = "!1PWR00\n"
        assert parse_iscp_message(raw) == "PWR00"


class TestParsePackets:
    """Streaming packet parser."""

    def test_single_packet(self) -> None:
        packet = build_packet("SLI23")
        frames, remainder = parse_packets(packet)
        assert remainder == b""
        assert len(frames) == 1
        assert frames[0].command == "SLI"
        assert frames[0].parameter == "23"
        assert frames[0].raw_iscp == "SLI23"

    def test_partial_buffer(self) -> None:
        packet = build_packet("PWR01")
        frames, remainder = parse_packets(packet[:20])
        assert frames == []
        assert len(remainder) == 20

        frames, remainder = parse_packets(remainder + packet[20:])
        assert len(frames) == 1
        assert frames[0].raw_iscp == "PWR01"
        assert remainder == b""

    def test_back_to_back_packets(self) -> None:
        combined = build_packet("PWR01") + build_packet("MVL0A")
        frames, remainder = parse_packets(combined)
        assert remainder == b""
        assert [f.raw_iscp for f in frames] == ["PWR01", "MVL0A"]

    def test_ifa_frame(self) -> None:
        param = "OPTICAL 2,Dolby D,48 kHz,5.1 ch,Dolby Digital,3.1 ch,48 kHz,"
        iscp = f"IFA{param}"
        packet = build_packet(iscp)
        frames, _ = parse_packets(packet)
        assert frames[0].command == "IFA"
        assert frames[0].parameter == param

    def test_parse_received_packet_with_sub_terminator(self) -> None:
        """Inbound frames may use SUB+CR; outbound build_packet does not."""
        body = b"!1PWR01\x1a\r"
        header = struct.pack("!4sIIB3s", b"ISCP", 16, len(body), 1, b"\x00\x00\x00")
        frames, remainder = parse_packets(header + body)
        assert remainder == b""
        assert len(frames) == 1
        assert frames[0].raw_iscp == "PWR01"
