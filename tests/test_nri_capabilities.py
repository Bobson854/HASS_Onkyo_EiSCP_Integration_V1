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


class TestNriHelperFunctions:
    """Low-level parser helpers."""

    def test_extract_text_from_scalar_node(self) -> None:
        assert nc.extract_text({"@text": "Pioneer"}) == "Pioneer"

    def test_extract_text_from_plain_string(self) -> None:
        assert nc.extract_text("VSX-1131") == "VSX-1131"

    def test_normalize_list_singleton(self) -> None:
        node = {"@attributes": {"id": "1"}}
        assert nc.normalize_list(node) == [node]


class TestNriCapabilities:
    """Structured receiver capabilities from live-shaped synthetic NRI."""

    @pytest.fixture
    def caps(self):
        return nc.build_receiver_capabilities(SYNTHETIC_NRI_XML)

    def test_parses_identity(self, caps) -> None:
        assert caps.identity.serial == "SYNTH00000001"
        assert caps.identity.model == "VSX-1131"
        assert caps.identity.brand == "Pioneer"
        assert caps.identity.mac_address == "00:AA:BB:CC:DD:EE"
        assert caps.identity.firmware_version == "9.9.9"
        assert caps.identity.year == "2016"
        assert caps.identity.category == "AV Receiver"

    def test_zones_non_empty(self, caps) -> None:
        assert len(caps.zones) == 2

    def test_main_zone_volume_reference(self, caps) -> None:
        main = caps.main_zone()
        assert main is not None
        assert main.zone_id == "1"
        assert main.name == "Main"
        assert main.volume_max == 82
        assert caps.volume_reference == 82

    def test_enabled_selector_count(self, caps) -> None:
        assert len(caps.enabled_selectors()) == 15

    def test_selector_code_12_is_tv(self, caps) -> None:
        assert caps.input_source_map()["12"] == "TV"

    def test_disabled_selector_ignored(self, caps) -> None:
        assert "99" not in caps.input_source_map()

    def test_listening_mode_capabilities_filter_disabled(self, caps) -> None:
        modes = caps.listening_mode_map()
        assert "LMD Pure Direct" in modes
        assert modes["LMD Pure Direct"] == "11"
        assert "LMD Disabled Mode" not in modes

    def test_control_position_and_zone(self, caps) -> None:
        control = next(c for c in caps.controls if c.control_id == "LMD Pure Direct")
        assert control.zone == "1"
        assert control.position == "0"

    def test_tone_control_ranges(self, caps) -> None:
        bass = next(c for c in caps.controls if c.control_id == "Bass")
        assert bass.min_value == "-10"
        assert bass.max_value == "10"
        assert bass.step == "1"

    def test_feature_flags(self, caps) -> None:
        assert caps.functions["DolbyAtmos"] is True
        assert caps.functions["MCACC"] is True

    def test_network_services_parse(self, caps) -> None:
        assert len(caps.network_services) == 2
        assert caps.network_services[0]["name"] == "Spotify"

    def test_tuners_parse(self, caps) -> None:
        assert len(caps.tuners) == 2
        bands = {item["band"] for item in caps.tuners}
        assert bands == {"FM", "AM"}

    def test_zone2_supported(self, caps) -> None:
        assert caps.zone2_supported is True

    def test_raw_retained(self, caps) -> None:
        assert caps.raw == SYNTHETIC_NRI_XML

    def test_malformed_nri_fallback(self) -> None:
        caps = nc.build_receiver_capabilities("<broken")
        assert caps.parse_error is not None
        assert caps.selectors == []

    def test_json_serializable(self, caps) -> None:
        json.dumps(caps.as_dict())

    def test_resolve_listening_mode_name(self, caps) -> None:
        assert caps.resolve_listening_mode_name("AUTO") == "LMD Auto/Direct"
