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
    """Unit tests for layered listening-mode display resolution."""

    def test_known_lmd01_resolves_to_direct(self) -> None:
        display, source = lm.resolve_listening_mode_display("01")
        assert display == "Direct"
        assert source == lm.SOURCE_LMD_MAPPING

    def test_unknown_lmd_without_ifa_falls_back_to_raw(self) -> None:
        display, source = lm.resolve_listening_mode_display("FF")
        assert display == "FF"
        assert source == lm.SOURCE_RAW_FALLBACK

    def test_unknown_lmd_with_ifa_uses_output_format(self) -> None:
        display, source = lm.resolve_listening_mode_display(
            "FF",
            ifa_output_format="Auto Surround",
        )
        assert display == "Auto Surround"
        assert source == lm.SOURCE_IFA_OUTPUT_FORMAT

    def test_unhelpful_ifa_does_not_override_unknown_lmd(self) -> None:
        display, source = lm.resolve_listening_mode_display(
            "FF",
            ifa_output_format="Unknown",
        )
        assert display == "FF"
        assert source == lm.SOURCE_RAW_FALLBACK

    def test_known_lmd_overrides_stale_ifa(self) -> None:
        display, source = lm.resolve_listening_mode_display(
            "01",
            ifa_output_format="Auto Surround",
        )
        assert display == "Direct"
        assert source == lm.SOURCE_LMD_MAPPING


class TestReceiverListeningModeState:
    """Receiver frame handling for LMD/IFA ordering."""

    @pytest.fixture
    def receiver(self):
        receiver_mod = _load_receiver()
        rec = receiver_mod.PioneerReceiver("192.0.2.10", 60128)
        rec._connection = MagicMock(connected=True)
        return rec

    @pytest.mark.asyncio
    async def test_lmd_ff_then_ifa_auto_surround(self, receiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="FF", raw_iscp="LMDFF")
        )
        assert receiver.state.listening_mode_code == "FF"
        assert receiver.state.listening_mode == "FF"
        assert receiver.state.listening_mode_source == lm.SOURCE_RAW_FALLBACK

        await receiver._handle_frame(
            framing.EiscpFrame(
                command="IFA",
                parameter="OPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
                raw_iscp="IFAOPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
            )
        )
        assert receiver.state.listening_mode_code == "FF"
        assert receiver.state.listening_mode == "Auto Surround"
        assert receiver.state.listening_mode_source == lm.SOURCE_IFA_OUTPUT_FORMAT

    @pytest.mark.asyncio
    async def test_ifa_first_then_lmd_ff(self, receiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(
                command="IFA",
                parameter="OPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
                raw_iscp="IFAOPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
            )
        )
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="FF", raw_iscp="LMDFF")
        )
        assert receiver.state.listening_mode == "Auto Surround"
        assert receiver.state.listening_mode_source == lm.SOURCE_IFA_OUTPUT_FORMAT

    @pytest.mark.asyncio
    async def test_known_lmd01_after_ff_ifa_state(self, receiver) -> None:
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
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="01", raw_iscp="LMD01")
        )
        assert receiver.state.listening_mode_code == "01"
        assert receiver.state.listening_mode == "Direct"
        assert receiver.state.listening_mode_source == lm.SOURCE_LMD_MAPPING

    @pytest.mark.asyncio
    async def test_ifa_change_refreshes_unknown_lmd_fallback(self, receiver) -> None:
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
        await receiver._handle_frame(
            framing.EiscpFrame(
                command="IFA",
                parameter="OPTICAL 2,Dolby D,48 kHz,5.1 ch,Stereo,2.0 ch,48 kHz,",
                raw_iscp="IFAOPTICAL 2,Dolby D,48 kHz,5.1 ch,Stereo,2.0 ch,48 kHz,",
            )
        )
        assert receiver.state.listening_mode_code == "FF"
        assert receiver.state.listening_mode == "Stereo"
        assert receiver.state.listening_mode_source == lm.SOURCE_IFA_OUTPUT_FORMAT

    @pytest.mark.asyncio
    async def test_nri_selectable_modes_separate_from_current_state(self, receiver) -> None:
        fixture_path = Path(__file__).resolve().parent / "nri_fixtures.py"
        spec = importlib.util.spec_from_file_location("nri_fixtures", fixture_path)
        assert spec and spec.loader
        fixture_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_mod)

        receiver.apply_nri_payload(fixture_mod.SYNTHETIC_NRI_XML)
        selectable = receiver.get_listening_mode_map()
        assert "LMD Auto/Direct" in selectable
        assert selectable["LMD Auto/Direct"] == "AUTO"

        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="01", raw_iscp="LMD01")
        )
        assert receiver.state.listening_mode_code == "01"
        assert receiver.state.listening_mode == "Direct"
        assert receiver.state.listening_mode not in selectable

        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="FF", raw_iscp="LMDFF")
        )
        assert receiver.state.listening_mode_code == "FF"
        assert receiver.state.listening_mode == "FF"
