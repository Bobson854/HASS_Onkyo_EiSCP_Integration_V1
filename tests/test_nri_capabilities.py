"""Tests for structured NRI capability parsing."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "custom_components" / "pioneer_eiscp" / "protocol"

_fixture_spec = importlib.util.spec_from_file_location(
    "nri_fixtures", Path(__file__).resolve().parent / "nri_fixtures.py"
)
assert _fixture_spec and _fixture_spec.loader
_fixture_mod = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_mod)
SYNTHETIC_NRI_XML = _fixture_mod.SYNTHETIC_NRI_XML


def _load_modules():
    for mod in list(sys.modules):
        if mod.startswith("pioneer_eiscp.protocol"):
            del sys.modules[mod]
    for name, rel in [
        ("pioneer_eiscp.protocol.nri_parser", "nri_parser.py"),
        ("pioneer_eiscp.protocol.nri_capabilities", "nri_capabilities.py"),
    ]:
        spec = importlib.util.spec_from_file_location(name, PROTOCOL / rel)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["pioneer_eiscp.protocol.nri_capabilities"]


nc = _load_modules()


class TestNriCapabilities:
    """Structured receiver capabilities from synthetic NRI."""

    def test_parses_identity(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        assert caps.identity.serial == "SYNTH00000001"
        assert caps.identity.model == "AVR-9000"
        assert caps.identity.brand == "SynthBrand"
        assert caps.identity.mac_address == "00:AA:BB:CC:DD:EE"
        assert caps.identity.firmware_version == "9.9.9"

    def test_main_zone_volume_reference(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        main = caps.main_zone()
        assert main is not None
        assert main.volume_max == 82
        assert caps.volume_reference == 82

    def test_enabled_selectors_only(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        enabled = caps.enabled_selectors()
        assert len(enabled) == 2
        assert {item.name for item in enabled} == {"HDMI 1", "Tuner"}
        assert caps.input_source_map()["01"] == "HDMI 1"

    def test_disabled_selector_ignored(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        assert "02" not in caps.input_source_map()

    def test_listening_mode_capabilities_filter_disabled(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        modes = caps.listening_mode_map()
        assert "LMD Pure Direct" in modes
        assert modes["LMD Pure Direct"] == "11"
        assert "LMD Disabled Mode" not in modes

    def test_tone_control_ranges(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        bass = next(c for c in caps.controls if c.control_id == "Bass")
        assert bass.min_value == "-10"
        assert bass.max_value == "10"
        assert bass.step == "1"

    def test_feature_flags(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        assert caps.functions["DolbyAtmos"] is True
        assert caps.functions["MCACC"] is True

    def test_zone2_supported(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        assert caps.zone2_supported is True

    def test_raw_retained(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        assert caps.raw == SYNTHETIC_NRI_XML

    def test_malformed_nri_fallback(self) -> None:
        caps = nc.build_receiver_capabilities("<broken")
        assert caps.parse_error is not None
        assert caps.selectors == []

    def test_json_serializable(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        json.dumps(caps.as_dict())

    def test_resolve_listening_mode_name(self) -> None:
        caps = nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)
        assert caps.resolve_listening_mode_name("AUTO") == "LMD Auto/Direct"
