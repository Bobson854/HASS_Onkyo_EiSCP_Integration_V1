"""Tests for listening-mode select option reconciliation."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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

NRI_OPTIONS = ["Auto/Direct", "Pure Direct", "Stereo", "Surround"]


def _load_modules():
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

    return (
        sys.modules["pioneer_eiscp.protocol.listening_mode"],
        sys.modules["pioneer_eiscp.receiver"],
    )


lm, receiver_mod = _load_modules()
PioneerReceiver = receiver_mod.PioneerReceiver


def _assert_option_in_options(option: str | None, options: list[str]) -> None:
    if option is not None:
        assert option in options


class TestResolveSelectOption:
    """Unit tests for select option reconciliation."""

    def test_auto_surround_maps_to_auto_direct(self) -> None:
        option, source = lm.resolve_select_option("Auto Surround", "40", NRI_OPTIONS)
        assert option == "Auto/Direct"
        assert source == lm.SELECT_MATCH_SEMANTIC

    def test_auto_surround_with_ff_code_not_hardcoded(self) -> None:
        option, source = lm.resolve_select_option("Auto Surround", "FF", NRI_OPTIONS)
        assert option == "Auto/Direct"
        assert source == lm.SELECT_MATCH_SEMANTIC

    def test_pure_direct_maps_to_pure_direct(self) -> None:
        option, source = lm.resolve_select_option("Pure Direct", "0D", NRI_OPTIONS)
        assert option == "Pure Direct"
        assert source in {lm.SELECT_MATCH_EXACT, lm.SELECT_MATCH_SEMANTIC}

    def test_stereo_maps_to_stereo_option(self) -> None:
        option, _source = lm.resolve_select_option("Stereo", None, NRI_OPTIONS)
        assert option == "Stereo"

    def test_surround_maps_to_surround(self) -> None:
        option, _source = lm.resolve_select_option("Surround", None, NRI_OPTIONS)
        assert option == "Surround"

    def test_direct_maps_to_auto_direct(self) -> None:
        option, source = lm.resolve_select_option("Direct", "01", NRI_OPTIONS)
        assert option == "Auto/Direct"
        assert source == lm.SELECT_MATCH_SEMANTIC

    def test_unknown_state_returns_none(self) -> None:
        option, source = lm.resolve_select_option("Dolby Atmos", "99", NRI_OPTIONS)
        assert option is None
        assert source is None

    def test_empty_options_returns_none(self) -> None:
        option, source = lm.resolve_select_option("Auto Surround", "40", [])
        assert option is None
        assert source is None

    def test_current_option_always_in_options(self) -> None:
        cases = [
            ("Auto Surround", "40"),
            ("Direct", "01"),
            ("Pure Direct", "0D"),
            ("Stereo", None),
            ("Surround", None),
            ("Unknown Mode", "AB"),
        ]
        for state, code in cases:
            option, _source = lm.resolve_select_option(state, code, NRI_OPTIONS)
            _assert_option_in_options(option, NRI_OPTIONS)


class TestReceiverListeningModeSelect:
    """Receiver and command mapping integration."""

    @pytest.fixture
    def receiver(self) -> PioneerReceiver:
        rec = PioneerReceiver("192.0.2.10", 60128)
        rec._connection = MagicMock(connected=True)
        rec.apply_nri_payload(SYNTHETIC_NRI_XML)
        return rec

    def test_nri_options_are_user_facing_labels(self, receiver: PioneerReceiver) -> None:
        mode_map = receiver.get_listening_mode_map()
        assert set(mode_map) == set(NRI_OPTIONS)
        assert mode_map["Auto/Direct"] == "AUTO"
        assert mode_map["Pure Direct"] == "11"
        assert mode_map["Stereo"] == "STEREO"
        assert mode_map["Surround"] == "SURR"

    @pytest.mark.asyncio
    async def test_live_like_auto_surround_state(self, receiver: PioneerReceiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="LMD", parameter="40", raw_iscp="LMD40")
        )
        await receiver._handle_frame(
            framing.EiscpFrame(
                command="IFA",
                parameter="OPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
                raw_iscp="IFAOPTICAL 2,Dolby D,48 kHz,5.1 ch,Auto Surround,3.1 ch,48 kHz,",
            )
        )
        assert receiver.state.listening_mode == "Auto Surround"
        assert receiver.state.listening_mode_code == "40"
        assert receiver.state.listening_mode_source == lm.SOURCE_IFA_OUTPUT_FORMAT
        assert receiver.state.listening_mode_select_option == "Auto/Direct"
        assert receiver.state.listening_mode_select_match_source == lm.SELECT_MATCH_SEMANTIC
        _assert_option_in_options(
            receiver.state.listening_mode_select_option,
            receiver.get_listening_mode_options(),
        )

    @pytest.mark.asyncio
    async def test_exact_state_unaffected_by_select_mapping(self, receiver: PioneerReceiver) -> None:
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
        assert receiver.state.listening_mode == "Auto Surround"
        assert receiver.state.listening_mode_select_option == "Auto/Direct"

    @pytest.mark.asyncio
    async def test_select_auto_direct_sends_auto_command(self, receiver: PioneerReceiver) -> None:
        receiver._connection.send = AsyncMock()
        await receiver.set_listening_mode(
            receiver.get_listening_mode_map()["Auto/Direct"]
        )
        receiver._connection.send.assert_awaited_once_with("LMDAUTO")

    @pytest.mark.asyncio
    async def test_select_pure_direct_sends_11(self, receiver: PioneerReceiver) -> None:
        receiver._connection.send = AsyncMock()
        await receiver.set_listening_mode(
            receiver.get_listening_mode_map()["Pure Direct"]
        )
        receiver._connection.send.assert_awaited_once_with("LMD11")

    def test_no_nri_capabilities_static_fallback(self) -> None:
        receiver = PioneerReceiver("192.0.2.10", 60128)
        receiver._connection = MagicMock(connected=True)
        options = receiver.get_listening_mode_options()
        assert options
        option, _source = lm.resolve_select_option("Direct", "01", options)
        _assert_option_in_options(option, options)
