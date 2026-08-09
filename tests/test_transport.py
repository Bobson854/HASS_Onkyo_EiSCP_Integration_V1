"""Tests for eISCP transport lifecycle, reconnect guards, and diagnostics."""

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


def _load_transport():
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
        ("pioneer_eiscp.protocol.framing", PROTOCOL / "framing.py"),
        ("pioneer_eiscp.protocol.transport", PROTOCOL / "transport.py"),
    ]:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    return sys.modules["pioneer_eiscp.protocol.transport"]


transport_mod = _load_transport()
EiscpConnection = transport_mod.EiscpConnection
DISCONNECT_LOCAL_CLOSE = transport_mod.DISCONNECT_LOCAL_CLOSE
DISCONNECT_RECEIVER_EOF = transport_mod.DISCONNECT_RECEIVER_EOF


class MockStreamWriter:
    """Minimal asyncio StreamWriter stand-in."""

    def __init__(self) -> None:
        self.closed = False
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class MockStreamReader:
    """StreamReader that yields configured chunks then EOF."""

    def __init__(
        self,
        chunks: list[bytes | None] | None = None,
        *,
        hang: bool = False,
        eof_after_delay: float | None = None,
    ) -> None:
        self._chunks = list(chunks or [])
        self._hang = hang
        self._eof_after_delay = eof_after_delay
        self.read_count = 0

    async def read(self, _size: int) -> bytes:
        self.read_count += 1
        if self._eof_after_delay is not None and self.read_count == 1:
            await asyncio.sleep(self._eof_after_delay)
            return b""
        if self._hang or (not self._chunks and self._eof_after_delay is None):
            await asyncio.sleep(3600)
            return b""
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if chunk is None:
            await asyncio.sleep(3600)
        return chunk or b""


def _make_open_connection_factory(
    readers: list[MockStreamReader],
) -> MagicMock:
    writers: list[MockStreamWriter] = []

    async def _open_connection(_host: str, _port: int) -> tuple[MockStreamReader, MockStreamWriter]:
        if not readers:
            raise ConnectionRefusedError("no more connections")
        writer = MockStreamWriter()
        writers.append(writer)
        return readers.pop(0), writer

    mock = MagicMock(side_effect=_open_connection)
    mock.writers = writers
    return mock


@pytest.fixture
def reconnect_interval() -> float:
    return 0.05


class TestTransportLifecycle:
    """Transport connect/disconnect/reconnect behaviour."""

    @pytest.mark.asyncio
    async def test_receiver_eof_triggers_single_reconnect(
        self, reconnect_interval: float
    ) -> None:
        reader1 = MockStreamReader(eof_after_delay=0.02)
        reader2 = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader1, reader2])

        connected_count = 0
        disconnected_count = 0

        async def on_connected() -> None:
            nonlocal connected_count
            connected_count += 1

        async def on_disconnected() -> None:
            nonlocal disconnected_count
            disconnected_count += 1

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                on_connected=on_connected,
                on_disconnected=on_disconnected,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()
            assert conn.session_id == 1
            assert connected_count == 1

            await asyncio.sleep(0.05 + reconnect_interval * 2)

        diag = conn.get_diagnostics()
        assert diag["receiver_closed_count"] == 1
        assert diag["reconnect_scheduled_count"] == 1
        assert diag["successful_connections"] == 2
        assert connected_count == 2
        assert disconnected_count == 1
        assert conn.session_id == 2

        await conn.stop()

    @pytest.mark.asyncio
    async def test_duplicate_reconnect_scheduling_is_prevented(
        self, reconnect_interval: float
    ) -> None:
        reader = MockStreamReader([b""])
        open_mock = _make_open_connection_factory([reader, MockStreamReader([None])])

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()
            await conn._schedule_reconnect(DISCONNECT_RECEIVER_EOF)
            await conn._schedule_reconnect(DISCONNECT_RECEIVER_EOF)

        diag = conn.get_diagnostics()
        assert diag["reconnect_scheduled_count"] == 1

        await conn.stop()

    @pytest.mark.asyncio
    async def test_connect_while_connecting_does_not_duplicate(
        self, reconnect_interval: float
    ) -> None:
        reader = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader])

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                reconnect_interval=reconnect_interval,
            )
            task1 = asyncio.create_task(conn.start())
            task2 = asyncio.create_task(conn._ensure_connected(wait=True))
            await asyncio.gather(task1, task2)

        assert open_mock.call_count == 1
        await conn.stop()

    @pytest.mark.asyncio
    async def test_connect_while_healthy_does_not_create_second_reader(
        self, reconnect_interval: float
    ) -> None:
        reader = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader])

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()
            first_read_task = conn._read_task
            await conn._ensure_connected(wait=False)

        assert open_mock.call_count == 1
        assert conn._read_task is first_read_task
        await conn.stop()

    @pytest.mark.asyncio
    async def test_unload_prevents_reconnect(self, reconnect_interval: float) -> None:
        reader = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader])

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()
            await conn.stop()
            await asyncio.sleep(reconnect_interval * 3)

        assert open_mock.call_count == 1
        diag = conn.get_diagnostics()
        assert diag["local_disconnect_count"] == 1
        assert diag["reconnect_scheduled_count"] == 0

    @pytest.mark.asyncio
    async def test_stale_reader_cannot_disconnect_newer_session(
        self, reconnect_interval: float
    ) -> None:
        reader = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader])

        disconnected_count = 0

        async def on_disconnected() -> None:
            nonlocal disconnected_count
            disconnected_count += 1

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                on_disconnected=on_disconnected,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()
            conn._session_id = 2
            conn._active_read_session_id = 2
            conn._connected = True
            await conn._close_transport(
                session_id=1,
                reason=DISCONNECT_RECEIVER_EOF,
            )

        assert conn.connected is True
        assert conn.session_id == 2
        assert disconnected_count == 0

        await conn.stop()

    @pytest.mark.asyncio
    async def test_reconnect_creates_new_session_id(
        self, reconnect_interval: float
    ) -> None:
        reader1 = MockStreamReader(eof_after_delay=0.02)
        reader2 = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader1, reader2])

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()
            assert conn.session_id == 1
            await asyncio.sleep(0.05 + reconnect_interval * 2)
            assert conn.session_id == 2

        await conn.stop()

    @pytest.mark.asyncio
    async def test_diagnostics_counters_and_timestamps_update(
        self, reconnect_interval: float
    ) -> None:
        reader = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader])

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()

        diag = conn.get_diagnostics()
        assert diag["connected"] is True
        assert diag["session_id"] == 1
        assert diag["connect_attempts"] >= 1
        assert diag["successful_connections"] == 1
        assert diag["last_connected_at"] is not None
        assert diag["reader_task_active"] is True
        assert diag["reconnect_task_active"] is False

        await conn.stop()

        diag = conn.get_diagnostics()
        assert diag["connected"] is False
        assert diag["local_disconnect_count"] == 1
        assert diag["last_disconnected_at"] is not None
        assert diag["last_disconnect_reason"] == DISCONNECT_LOCAL_CLOSE
        assert diag["reader_task_active"] is False

    @pytest.mark.asyncio
    async def test_read_error_logged_with_exception_category(
        self, reconnect_interval: float
    ) -> None:
        class BrokenReader(MockStreamReader):
            async def read(self, _size: int) -> bytes:
                raise OSError("socket reset")

        reader = BrokenReader([])
        open_mock = _make_open_connection_factory([reader, MockStreamReader([None])])

        with patch("asyncio.open_connection", open_mock):
            conn = EiscpConnection(
                "192.0.2.1",
                60128,
                reconnect_interval=reconnect_interval,
            )
            await conn.start()
            await asyncio.sleep(reconnect_interval * 2.5)

        diag = conn.get_diagnostics()
        assert diag["last_disconnect_reason"] == transport_mod.DISCONNECT_READ_ERROR

        await conn.stop()


class TestReceiverReconnectState:
    """Receiver-level reconnect state refresh without repeating NRI."""

    @pytest.mark.asyncio
    async def test_successful_reconnect_restores_connected_state(
        self, reconnect_interval: float
    ) -> None:
        receiver_mod = _load_receiver()
        PioneerReceiver = receiver_mod.PioneerReceiver
        STARTUP_QUERIES = sys.modules["pioneer_eiscp.const"].STARTUP_QUERIES

        reader1 = MockStreamReader(eof_after_delay=2.0)
        reader2 = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader1, reader2])

        with patch("asyncio.open_connection", open_mock):
            receiver = PioneerReceiver("192.0.2.1", 60128)
            receiver._connection._reconnect_interval = reconnect_interval
            await receiver.start()
            assert receiver.state.connected is True

            await asyncio.sleep(2.1 + reconnect_interval * 2)

            assert receiver.state.connected is True
            assert receiver.get_transport_diagnostics()["successful_connections"] == 2

            await receiver.stop()

    @pytest.mark.asyncio
    async def test_state_refresh_queries_sent_once_on_connect(
        self, reconnect_interval: float
    ) -> None:
        receiver_mod = _load_receiver()
        PioneerReceiver = receiver_mod.PioneerReceiver
        STARTUP_QUERIES = sys.modules["pioneer_eiscp.const"].STARTUP_QUERIES

        reader = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader])

        with patch("asyncio.open_connection", open_mock):
            receiver = PioneerReceiver("192.0.2.1", 60128)
            await receiver.start()

        writer = open_mock.writers[0]
        sent_bodies = [payload.decode("ascii", errors="ignore") for payload in writer.written]
        for query in STARTUP_QUERIES:
            assert any(query in body for body in sent_bodies)

        await receiver.stop()

    @pytest.mark.asyncio
    async def test_nri_not_cleared_on_reconnect(self, reconnect_interval: float) -> None:
        receiver_mod = _load_receiver()
        PioneerReceiver = receiver_mod.PioneerReceiver
        build_receiver_capabilities = sys.modules[
            "pioneer_eiscp.protocol.nri_capabilities"
        ].build_receiver_capabilities

        fixture_path = Path(__file__).resolve().parent / "nri_fixtures.py"
        spec = importlib.util.spec_from_file_location("nri_fixtures", fixture_path)
        assert spec and spec.loader
        fixture_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_mod)

        reader1 = MockStreamReader(eof_after_delay=2.0)
        reader2 = MockStreamReader(hang=True)
        open_mock = _make_open_connection_factory([reader1, reader2])

        with patch("asyncio.open_connection", open_mock):
            receiver = PioneerReceiver("192.0.2.1", 60128)
            receiver._connection._reconnect_interval = reconnect_interval
            receiver.apply_nri_payload(fixture_mod.SYNTHETIC_NRI_XML)
            assert receiver.receiver_capabilities_model.identity.brand == "Pioneer"

            await receiver.start()
            await asyncio.sleep(2.1 + reconnect_interval * 2)

            assert receiver.receiver_capabilities_model.identity.brand == "Pioneer"
            assert receiver.receiver_capabilities_model.identity.model == "VSX-1131"

            await receiver.stop()


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
