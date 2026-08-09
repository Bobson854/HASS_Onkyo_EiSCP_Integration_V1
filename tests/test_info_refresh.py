"""Tests for IFA/IFV information refresh scheduling."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"
PROTOCOL = BASE / "protocol"


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
        ("pioneer_eiscp.info_refresh", BASE / "info_refresh.py"),
        ("pioneer_eiscp.receiver", BASE / "receiver.py"),
    ]
    for name, path in files:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    return (
        sys.modules["pioneer_eiscp.info_refresh"],
        sys.modules["pioneer_eiscp.receiver"],
    )


info_refresh_mod, receiver_mod = _load_modules()
PioneerReceiver = receiver_mod.PioneerReceiver
REFRESH_REASON_POWER_ON = info_refresh_mod.REFRESH_REASON_POWER_ON
REFRESH_REASON_PERIODIC = info_refresh_mod.REFRESH_REASON_PERIODIC
REFRESH_REASON_SOURCE_CHANGE = info_refresh_mod.REFRESH_REASON_SOURCE_CHANGE


async def _instant_sleep(_delay: float) -> None:
    return None


@pytest.fixture
def receiver() -> PioneerReceiver:
    rec = PioneerReceiver("192.0.2.10", 60128)
    rec._connection = MagicMock(connected=True)
    rec.state.connected = True
    rec.state.main.power = True
    return rec


class TestInfoRefreshScheduler:
    """Information refresh scheduling behaviour."""

    @pytest.mark.asyncio
    async def test_power_on_schedules_delayed_ifa_ifv(self, receiver: PioneerReceiver) -> None:
        scheduler = receiver._info_refresh
        sent: list[str] = []

        async def _capture_send(body: str) -> None:
            sent.append(body)

        receiver.send_raw = _capture_send  # type: ignore[method-assign]

        with (
            patch.object(asyncio, "sleep", new=_instant_sleep),
            patch.object(scheduler, "_ensure_periodic", new=AsyncMock()),
        ):
            await scheduler.on_power_changed(False, True)
            if scheduler._delayed_task:
                await scheduler._delayed_task

        assert "IFAQSTN" in sent
        assert "IFVQSTN" in sent
        assert "LMDQSTN" in sent
        assert "NRIQSTN" not in sent

    @pytest.mark.asyncio
    async def test_repeated_power_on_does_not_duplicate_delayed_refresh(
        self, receiver: PioneerReceiver
    ) -> None:
        scheduler = receiver._info_refresh
        calls = 0

        async def _capture_send(body: str) -> None:
            nonlocal calls
            calls += 1

        receiver.send_raw = _capture_send  # type: ignore[method-assign]

        with (
            patch.object(asyncio, "sleep", new=_instant_sleep),
            patch.object(scheduler, "_ensure_periodic", new=AsyncMock()),
        ):
            await scheduler.on_power_changed(False, True)
            await scheduler.on_power_changed(False, True)
            if scheduler._delayed_task:
                await scheduler._delayed_task

        assert calls == 3

    @pytest.mark.asyncio
    async def test_powered_off_suppresses_periodic_refresh(
        self, receiver: PioneerReceiver
    ) -> None:
        scheduler = receiver._info_refresh
        receiver.send_raw = AsyncMock()  # type: ignore[method-assign]

        with patch.object(asyncio, "sleep", new=_instant_sleep):
            await scheduler.start()
            await scheduler.on_power_changed(True, False)

        diag = scheduler.get_diagnostics()
        assert diag["periodic_enabled"] is False
        receiver.send_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_periodic_refresh_queries_ifa_ifv_only(
        self, receiver: PioneerReceiver
    ) -> None:
        scheduler = receiver._info_refresh
        sent: list[str] = []

        async def _capture_send(body: str) -> None:
            sent.append(body)

        receiver.send_raw = _capture_send  # type: ignore[method-assign]

        periodic_iterations = 0

        async def _sleep_once_then_stop(delay: float) -> None:
            nonlocal periodic_iterations
            periodic_iterations += 1
            if periodic_iterations > 1:
                scheduler._closing = True

        with patch.object(asyncio, "sleep", new=_sleep_once_then_stop):
            await scheduler.start()
            if scheduler._periodic_task:
                await scheduler._periodic_task

        assert sent == ["IFAQSTN", "IFVQSTN"]

    @pytest.mark.asyncio
    async def test_source_change_schedules_delayed_refresh(
        self, receiver: PioneerReceiver
    ) -> None:
        scheduler = receiver._info_refresh
        sent: list[str] = []

        async def _capture_send(body: str) -> None:
            sent.append(body)

        receiver.send_raw = _capture_send  # type: ignore[method-assign]

        with patch.object(asyncio, "sleep", new=_instant_sleep):
            scheduler.on_source_changed()
            if scheduler._delayed_task:
                await scheduler._delayed_task

        assert sent == ["IFAQSTN", "IFVQSTN"]
        assert scheduler.get_diagnostics()["last_refresh_reason"] == REFRESH_REASON_SOURCE_CHANGE

    @pytest.mark.asyncio
    async def test_unload_cancels_periodic_task(self, receiver: PioneerReceiver) -> None:
        scheduler = receiver._info_refresh
        receiver.send_raw = AsyncMock()  # type: ignore[method-assign]

        async def _stop_after_start(_delay: float) -> None:
            scheduler._closing = True

        with patch.object(asyncio, "sleep", new=_stop_after_start):
            await scheduler.start()
            await scheduler.stop()

        diag = scheduler.get_diagnostics()
        assert diag["task_active"] is False
        assert diag["periodic_enabled"] is False

    @pytest.mark.asyncio
    async def test_reconnect_does_not_create_duplicate_periodic_tasks(
        self, receiver: PioneerReceiver
    ) -> None:
        scheduler = receiver._info_refresh
        receiver.send_raw = AsyncMock()  # type: ignore[method-assign]

        async def _stop_after_start(_delay: float) -> None:
            scheduler._closing = True

        with patch.object(asyncio, "sleep", new=_stop_after_start):
            await scheduler.start()
            first_task = scheduler._periodic_task
            await scheduler.on_connected()
            assert scheduler._periodic_task is first_task
            await scheduler.stop()


class TestReceiverInfoRefreshIntegration:
    """Receiver frame integration for information refresh."""

    @pytest.mark.asyncio
    async def test_ifa_na_while_off_is_accepted(self, receiver: PioneerReceiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        receiver.state.main.power = False
        await receiver._handle_frame(
            framing.EiscpFrame(command="IFA", parameter="N/A", raw_iscp="IFAN/A")
        )
        assert receiver.state.audio.raw == "N/A"
        assert receiver.state.audio.output_format is None

    @pytest.mark.asyncio
    async def test_power_on_frame_schedules_refresh(self, receiver: PioneerReceiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        receiver.state.main.power = False
        schedule_mock = MagicMock()
        receiver._info_refresh.schedule_delayed = schedule_mock

        await receiver._handle_frame(
            framing.EiscpFrame(command="PWR", parameter="01", raw_iscp="PWR01")
        )

        schedule_mock.assert_called_once()
        assert schedule_mock.call_args.args[1] == REFRESH_REASON_POWER_ON

    @pytest.mark.asyncio
    async def test_sli_change_schedules_refresh(self, receiver: PioneerReceiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        schedule_mock = MagicMock()
        receiver._info_refresh.on_source_changed = schedule_mock

        await receiver._handle_frame(
            framing.EiscpFrame(command="SLI", parameter="12", raw_iscp="SLI12")
        )

        schedule_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_ifa_recovers_after_power_on_refresh(self, receiver: PioneerReceiver) -> None:
        framing = sys.modules["pioneer_eiscp.protocol.framing"]
        await receiver._handle_frame(
            framing.EiscpFrame(command="IFA", parameter="N/A", raw_iscp="IFAN/A")
        )
        await receiver._handle_frame(
            framing.EiscpFrame(
                command="IFA",
                parameter="OPTICAL 2,Dolby D,48 kHz,5.1 ch,Dolby Digital,3.1 ch,48 kHz,",
                raw_iscp="IFAOPTICAL 2,Dolby D,48 kHz,5.1 ch,Dolby Digital,3.1 ch,48 kHz,",
            )
        )
        assert receiver.state.audio.output_format == "Dolby Digital"

    @pytest.mark.asyncio
    async def test_set_listening_mode_refreshes_ifa_after_settle(
        self, receiver: PioneerReceiver
    ) -> None:
        sent: list[str] = []

        async def _capture_send(body: str) -> None:
            sent.append(body)

        receiver.send_raw = _capture_send  # type: ignore[method-assign]

        with patch.object(asyncio, "sleep", new=_instant_sleep):
            await receiver.set_listening_mode("11")

        assert sent[0] == "LMD11"
        assert sent[1] == "LMDQSTN"
        assert sent[2] == "IFAQSTN"
        assert "IFVQSTN" not in sent
