"""Integration tests for NRI-driven receiver state refresh."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"
PROTOCOL = BASE / "protocol"

_fixture_spec = importlib.util.spec_from_file_location(
    "nri_fixtures", Path(__file__).resolve().parent / "nri_fixtures.py"
)
assert _fixture_spec and _fixture_spec.loader
_fixture_mod = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_mod)
SYNTHETIC_NRI_XML = _fixture_mod.SYNTHETIC_NRI_XML


def _load_receiver():
    for mod in list(sys.modules):
        if mod.startswith("pioneer_eiscp"):
            del sys.modules[mod]

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    proto_pkg = types.ModuleType("pioneer_eiscp.protocol")
    proto_pkg.__path__ = [str(PROTOCOL)]
    sys.modules["pioneer_eiscp.protocol"] = proto_pkg

    for name, rel in [
        ("pioneer_eiscp.const", "const.py"),
        ("pioneer_eiscp.capability_commands", "capability_commands.py"),
        ("pioneer_eiscp.protocol.framing", "protocol/framing.py"),
        ("pioneer_eiscp.protocol.parsers", "protocol/parsers.py"),
        ("pioneer_eiscp.protocol.volume", "protocol/volume.py"),
        ("pioneer_eiscp.protocol.nri_parser", "protocol/nri_parser.py"),
        ("pioneer_eiscp.protocol.nri_capabilities", "protocol/nri_capabilities.py"),
        ("pioneer_eiscp.protocol.transport", "protocol/transport.py"),
        ("pioneer_eiscp.protocol.capability_probe", "protocol/capability_probe.py"),
    ]:
        path = BASE / rel
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    name = "pioneer_eiscp.receiver"
    spec = importlib.util.spec_from_file_location(name, BASE / "receiver.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


receiver_mod = _load_receiver()
PioneerReceiver = receiver_mod.PioneerReceiver


@pytest.fixture
def receiver() -> PioneerReceiver:
    rec = PioneerReceiver("192.0.2.10", 60128)
    rec._connection = MagicMock(connected=True)
    return rec


class TestReceiverNriStateRefresh:
    """MVL/NRI ordering and dynamic source mapping."""

    def test_mvl_before_nri_then_refresh(self, receiver: PioneerReceiver) -> None:
        receiver._update_main_volume("52")
        assert receiver.state.main.volume_state.volume_reference is None
        assert receiver.state.main.volume_state.volume_db is None

        receiver.apply_nri_payload(SYNTHETIC_NRI_XML)

        volume = receiver.state.main.volume_state
        assert volume.absolute_volume == 52
        assert volume.volume_reference == 82
        assert volume.volume_db == pytest.approx(-30.0)
        assert volume.normalized_level() == pytest.approx(52 / 82, rel=1e-6)

    def test_nri_before_mvl(self, receiver: PioneerReceiver) -> None:
        receiver.apply_nri_payload(SYNTHETIC_NRI_XML)
        receiver._update_main_volume("52")

        volume = receiver.state.main.volume_state
        assert volume.absolute_volume == 52
        assert volume.volume_reference == 82
        assert volume.volume_db == pytest.approx(-30.0)

    def test_sli12_maps_to_tv_after_capabilities(self, receiver: PioneerReceiver) -> None:
        receiver.apply_nri_payload(SYNTHETIC_NRI_XML)
        receiver.state.main.input_code = "12"

        assert receiver.resolve_input_name("12") == "TV"
        assert receiver.get_state_dict()["main"]["input_name"] == "TV"

    def test_sli12_before_capabilities_corrected_after_nri(self, receiver: PioneerReceiver) -> None:
        receiver.state.main.input_code = "12"
        assert receiver.resolve_input_name("12") == "game"

        receiver.apply_nri_payload(SYNTHETIC_NRI_XML)

        assert receiver.resolve_input_name("12") == "TV"
        assert receiver.get_state_dict()["main"]["input_name"] == "TV"

    def test_static_fallback_without_nri(self, receiver: PioneerReceiver) -> None:
        receiver.state.main.input_code = "12"
        assert receiver.resolve_input_name("12") == "game"
