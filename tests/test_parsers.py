"""Tests for IFA/IFV and ISCP response parsers."""

from parsers import (
    parse_audio_information,
    parse_mute,
    parse_power,
    parse_video_information,
    parse_volume_hex,
)


class TestParseAudioInformation:
    """IFA audio-information parsing."""

    def test_full_example(self) -> None:
        """Parse the documented VSX-1131 style IFA response."""
        param = "OPTICAL 2,Dolby D,48 kHz,5.1 ch,Dolby Digital,3.1 ch,48 kHz,"
        audio = parse_audio_information(param)

        assert audio.input_port == "OPTICAL 2"
        assert audio.input_format == "Dolby D"
        assert audio.input_sample_rate == "48 kHz"
        assert audio.input_channels == "5.1 ch"
        assert audio.output_format == "Dolby Digital"
        assert audio.output_channels == "3.1 ch"
        assert audio.output_sample_rate == "48 kHz"
        assert audio.raw == param
        assert audio.extra_fields == []

    def test_truncated_ifa(self) -> None:
        """Missing trailing fields should not raise."""
        param = "HDMI 1,PCM"
        audio = parse_audio_information(param)

        assert audio.input_port == "HDMI 1"
        assert audio.input_format == "PCM"
        assert audio.input_sample_rate is None
        assert audio.output_format is None
        assert audio.fields == ["HDMI 1", "PCM"]

    def test_extra_ifa_fields(self) -> None:
        """Extra fields are preserved in extra_fields."""
        param = "A,B,C,D,E,F,G,H,I,J"
        audio = parse_audio_information(param)

        assert audio.input_port == "A"
        assert audio.output_sample_rate == "G"
        assert audio.extra_fields == ["H", "I", "J"]

    def test_empty_ifa(self) -> None:
        """Empty parameter returns empty structured state."""
        audio = parse_audio_information("")
        assert audio.input_port is None
        assert audio.fields == []
        assert audio.raw == ""


class TestParseVideoInformation:
    """IFV video-information parsing."""

    def test_preserves_positional_fields_only(self) -> None:
        param = "No Video,Unknown,,24bit,MAIN,1920 x 1080p,RGB,24bit,,"
        video = parse_video_information(param)

        assert video.raw == param
        assert video.fields[0] == "No Video"
        assert video.fields[4] == "MAIN"
        assert video.fields[5] == "1920 x 1080p"
        assert not hasattr(video, "color_depth")

    def test_no_semantic_field_mapping(self) -> None:
        video = parse_video_information("HDMI 1,HDMI OUT,1080p")
        payload = video.as_dict()
        assert "video_input" not in payload
        assert payload["fields"] == ["HDMI 1", "HDMI OUT", "1080p"]


class TestBasicResponseParsers:
    """PWR/MVL/AMT helpers."""

    def test_power(self) -> None:
        assert parse_power("00") is False
        assert parse_power("01") is True

    def test_mute(self) -> None:
        assert parse_mute("00") is False
        assert parse_mute("01") is True

    def test_volume_decimal_absolute(self) -> None:
        assert parse_volume_hex("52") == 52
        assert parse_volume_hex("14") == 14
        assert parse_volume_hex("ZZ") is None
