"""Tests for listening-mode current-state resolution."""

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

NRI_CODE_TO_OPTION = {
    "11": "Pure Direct",
    "AUTO": "Auto/Direct",
    "STEREO": "Stereo",
    "SURR": "Surround",
}


def _load_listening_mode():
    for mod in list(sys.modules):
        if mod.startswith("pioneer_eiscp"):
            del sys.modules[mod]

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    proto_pkg = types.ModuleType("pioneer_eiscp.protocol")
    proto_pkg.__path__ = [str(PROTOCOL)]
    sys.modules["pioneer_eiscp.protocol"] = proto_pkg

    for name, path in [
        ("pioneer_eiscp.const", BASE / "const.py"),
        ("pioneer_eiscp.protocol.listening_mode", PROTOCOL / "listening_mode.py"),
    ]:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    return sys.modules["pioneer_eiscp.protocol.listening_mode"]


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

    files = [
        ("pioneer_eiscp.const", BASE / "const.py"),
        ("pioneer_eiscp.capability_commands", BASE / "capability_commands.py"),
        ("pioneer_eiscp.protocol.framing", PROTOCOL / "framing.py"),
        ("pioneer_eiscp.protocol.parsers", PROTOCOL / "parsers.py"),
        ("pioneer_eiscp.protocol.volume", PROTOCOL / "volume.py"),
        ("pioneer_eiscp.protocol.listening_mode", PROTOCOL / "listening_mode.py"),
        ("pioneer_eiscp.protocol.nri_parser", PROTOCOL / "nri_parser.py"),
        ("pioneer_eiscp.protocol.nri_capabilities", PROTOCOL / "nri_capabilities.py"),
        ("pioneer_eiscp.protocol.transport", PROTOCOL / "transport.py"),
        ("pioneer_eiscp.protocol.capability_probe", PROTOCOL / "capability_probe.py"),
        ("pioneer_eiscp.receiver", BASE / "receiver.py"),
    ]
    for name, path in files:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    return sys.modules["pioneer_eiscp.receiver"]


lm = _load_listening_mode()


class TestListeningModeResolution:
    """Unit tests for listening-mode display resolution."""

    def test_known_lmd01_resolves_to_direct(self) -> None:
        display, source = lm.resolve_listening_mode_display("01")
        assert display == "Direct"
        assert source == lm.SOURCE_LMD_MAPPING

    def test_unknown_lmd_falls_back_to_raw(self) -> None:
        display, source = lm.resolve_listening_mode_display("FF")
        assert display == "FF"
        assert source == lm.SOURCE_RAW_FALLBACK

    def test_unknown_lmd40_falls_back_to_raw_not_ifa(self) -> None:
        display, source = lm.resolve_listening_mode_display(
            "40",
            nri_code_to_option=NRI_CODE_TO_OPTION,
        )
        assert display == "40"
        assert source == lm.SOURCE_RAW_FALLBACK

    def test_nri_code_match_11_is_pure_direct(self) -> None:
        display, source = lm.resolve_listening_mode_display(
            "11",
            nri_code_to_option=NRI_CODE_TO_OPTION,
        )
        assert display == "Pure Direct"
        assert source == lm.SOURCE_NRI_CODE_MATCH

    def test_static_mapping_precedes_nri_for_known_codes(self) -> None:
        display, source = lm.resolve_listening_mode_display(
            "01",
            nri_code_to_option=NRI_CODE_TO_OPTION,
        )
        assert display == "Direct"
        assert source == lm.SOURCE_LMD_MAPPING


class TestReceiverListeningModeState:
    """Receiver frame handling for LMD/IFA separation."""

    @pytest.fixture
    def receiver(self):
        receiver_mod = _load_receiver()
        rec = receiver_mod.PioneerReceiver("192.0.2.10", 60128)
        rec._connection = MagicMock(connected=True)
        return rec

    @pytest.mark.asyncio
    async def test_ifa_does_not_change_listening_mode(self, receiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="FF", raw_iscp="LMDFF")
        )
        await receiver._handle_frame(
            framing.EiscpFrame(
                command="IFA",
                parameter="OPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
                raw_iscp="IFAOPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
            )
        )
        assert receiver.state.listening_mode_code == "FF"
        assert receiver.state.listening_mode == "FF"
        assert receiver.state.listening_mode_source == lm.SOURCE_RAW_FALLBACK
        assert receiver.state.audio.output_format == "Auto Surround"

    @pytest.mark.asyncio
    async def test_ifa_dolby_digital_does_not_override_lmd11_with_nri(self, receiver) -> None:
        fixture_path = Path(__file__).resolve().parent / "nri_fixtures.py"
        spec = importlib.util.spec_from_file_location("nri_fixtures", fixture_path)
        assert spec and spec.loader
        fixture_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_mod)
        receiver.apply_nri_payload(fixture_mod.SYNTHETIC_NRI_XML)

        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="11", raw_iscp="LMD11")
        )
        await receiver._handle_frame(
            framing.EiscpFrame(
                command="IFA",
                parameter="OPTICAL 2,Dolby D,48 kHz,5.1 ch,Dolby Digital,3.1 ch,48 kHz,",
                raw_iscp="IFAOPTICAL 2,Dolby D,48 kHz,5.1 ch,Dolby Digital,3.1 ch,48 kHz,",
            )
        )
        assert receiver.state.listening_mode_code == "11"
        assert receiver.state.listening_mode == "Pure Direct"
        assert receiver.state.listening_mode_source == lm.SOURCE_NRI_CODE_MATCH
        assert receiver.state.audio.output_format == "Dolby Digital"
        assert receiver.state.listening_mode_select_option == "Pure Direct"

    @pytest.mark.asyncio
    async def test_known_lmd01_after_ff_state(self, receiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="FF", raw_iscp="LMDFF")
        )
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="01", raw_iscp="LMD01")
        )
        assert receiver.state.listening_mode_code == "01"
        assert receiver.state.listening_mode == "Direct"
        assert receiver.state.listening_mode_source == lm.SOURCE_LMD_MAPPING

    @pytest.mark.asyncio
    async def test_nri_selectable_modes_separate_from_current_state(self, receiver) -> None:
        fixture_path = Path(__file__).resolve().parent / "nri_fixtures.py"
        spec = importlib.util.spec_from_file_location("nri_fixtures", fixture_path)
        assert spec and spec.loader
        fixture_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_mod)

        receiver.apply_nri_payload(fixture_mod.SYNTHETIC_NRI_XML)
        selectable = receiver.get_listening_mode_map()
        assert "Auto/Direct" in selectable
        assert selectable["Auto/Direct"] == "AUTO"

        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="01", raw_iscp="LMD01")
        )
        assert receiver.state.listening_mode_code == "01"
        assert receiver.state.listening_mode == "Direct"
        assert receiver.state.listening_mode_select_option == "Auto/Direct"

        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="40", raw_iscp="LMD40")
        )
        assert receiver.state.listening_mode_code == "40"
        assert receiver.state.listening_mode == "40"
        assert receiver.state.listening_mode_select_option is None
