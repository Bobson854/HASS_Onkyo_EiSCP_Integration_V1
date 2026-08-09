"""Tests for eISCP framing and packet parsing."""

import struct

from framing import (
    build_packet,
    parse_iscp_message,
    parse_packets,
)


class TestBuildPacket:
    """eISCP packet encoding."""

    def test_build_pwr_query(self) -> None:
        packet = build_packet("PWRQSTN")
        magic, header_size, data_size, version, _reserved = struct.unpack(
            "!4sIIB3s", packet[:16]
        )
        assert magic == b"ISCP"
        assert header_size == 16
        assert version == 1
        body = packet[16:].decode("utf-8")
        assert body.startswith("!1PWRQSTN")
        assert "\x1a" in body


class TestParseIscpMessage:
    """ISCP message extraction."""

    def test_parse_with_eof_cr(self) -> None:
        raw = "!1MVL14\x1a\r"
        assert parse_iscp_message(raw) == "MVL14"

    def test_parse_with_eof_crlf(self) -> None:
        raw = "!1AMT00\x1a\r\n"
        assert parse_iscp_message(raw) == "AMT00"


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
