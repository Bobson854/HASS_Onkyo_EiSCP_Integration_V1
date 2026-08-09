"""Async eISCP TCP transport with reconnect support."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..const import CONNECT_TIMEOUT, READ_TIMEOUT, RECONNECT_INTERVAL
from .framing import EiscpFrame, build_packet, parse_packets

_LOGGER = logging.getLogger(__name__)

MessageCallback = Callable[[EiscpFrame], Awaitable[None] | None]
ConnectionCallback = Callable[[], Awaitable[None] | None]

# Disconnect reason constants (also used in diagnostics).
DISCONNECT_RECEIVER_EOF = "receiver_eof"
DISCONNECT_READ_ERROR = "read_error"
DISCONNECT_LOCAL_CLOSE = "local_close"
DISCONNECT_CONNECT_FAILED = "connect_failed"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TransportDiagnostics:
    """Lifecycle counters and timestamps for transport observability."""

    connected: bool = False
    session_id: int = 0
    connect_attempts: int = 0
    successful_connections: int = 0
    receiver_closed_count: int = 0
    local_disconnect_count: int = 0
    connect_failures: int = 0
    reconnect_scheduled_count: int = 0
    last_connected_at: str | None = None
    last_disconnected_at: str | None = None
    last_disconnect_reason: str | None = None
    reconnect_backoff_pending: bool = False
    reader_task_active: bool = False
    reconnect_task_active: bool = False
    _active_read_session_id: int = field(default=0, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "session_id": self.session_id,
            "connect_attempts": self.connect_attempts,
            "successful_connections": self.successful_connections,
            "receiver_closed_count": self.receiver_closed_count,
            "local_disconnect_count": self.local_disconnect_count,
            "connect_failures": self.connect_failures,
            "reconnect_scheduled_count": self.reconnect_scheduled_count,
            "last_connected_at": self.last_connected_at,
            "last_disconnected_at": self.last_disconnected_at,
            "last_disconnect_reason": self.last_disconnect_reason,
            "reconnect_backoff_pending": self.reconnect_backoff_pending,
            "reader_task_active": self.reader_task_active,
            "reconnect_task_active": self.reconnect_task_active,
        }


class EiscpConnection:
    """Maintain a persistent async TCP connection to an eISCP receiver."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        on_message: MessageCallback | None = None,
        on_connected: ConnectionCallback | None = None,
        on_disconnected: ConnectionCallback | None = None,
        connect_timeout: float = CONNECT_TIMEOUT,
        read_timeout: float = READ_TIMEOUT,
        reconnect_interval: float = RECONNECT_INTERVAL,
    ) -> None:
        self.host = host
        self.port = port
        self._on_message = on_message
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._reconnect_interval = reconnect_interval

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._connection_task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._buffer = b""
        self._connected = False
        self._closing = False
        self._session_id = 0
        self._active_read_session_id = 0
        self._diagnostics = TransportDiagnostics()

    @property
    def connected(self) -> bool:
        """Return True when the TCP session is active."""
        return self._connected

    @property
    def session_id(self) -> int:
        """Return the current session identifier (0 when never connected)."""
        return self._session_id

    def get_diagnostics(self) -> dict[str, Any]:
        """Return transport lifecycle diagnostics."""
        self._refresh_task_flags()
        return self._diagnostics.as_dict()

    def _refresh_task_flags(self) -> None:
        self._diagnostics.connected = self._connected
        self._diagnostics.session_id = self._session_id
        self._diagnostics.reader_task_active = (
            self._read_task is not None and not self._read_task.done()
        )
        self._diagnostics.reconnect_task_active = (
            self._connection_task is not None
            and not self._connection_task.done()
            and not self._connected
        )

    async def start(self) -> None:
        """Connect and begin the read loop."""
        self._closing = False
        await self._ensure_connected(wait=True)

    async def stop(self) -> None:
        """Close the connection and cancel background tasks."""
        self._closing = True
        connection_task = self._connection_task
        if connection_task and not connection_task.done():
            connection_task.cancel()
            try:
                await connection_task
            except asyncio.CancelledError:
                pass
        self._connection_task = None

        await self._cancel_read_task()
        await self._close_transport(
            session_id=self._active_read_session_id,
            reason=DISCONNECT_LOCAL_CLOSE,
            intentional=True,
        )
        self._refresh_task_flags()

    async def send(self, iscp_body: str) -> None:
        """Send a raw ISCP body (e.g. ``MVLQSTN``)."""
        if not self._writer or not self._connected:
            raise ConnectionError("Not connected to receiver")

        packet = build_packet(iscp_body)
        _LOGGER.debug("TX session %s %s", self._session_id, iscp_body)

        async with self._send_lock:
            self._writer.write(packet)
            await self._writer.drain()

    async def _ensure_connected(self, *, wait: bool) -> None:
        """Ensure a single connection attempt task is running."""
        async with self._lifecycle_lock:
            if self._closing:
                return
            if self._connected:
                return
            if self._connection_task and not self._connection_task.done():
                task = self._connection_task
            else:
                self._connection_task = asyncio.create_task(
                    self._connection_loop(),
                    name=f"pioneer_eiscp_connect_{self.host}",
                )
                task = self._connection_task
        if wait:
            try:
                await task
            except asyncio.CancelledError:
                if not self._closing:
                    raise

    async def _schedule_reconnect(self, reason: str) -> None:
        """Schedule a reconnect when no healthy session exists."""
        if self._closing:
            return
        if self._connected:
            return

        async with self._lifecycle_lock:
            if self._closing or self._connected:
                return
            if self._connection_task and not self._connection_task.done():
                return
            self._diagnostics.reconnect_scheduled_count += 1
            _LOGGER.info(
                "Pioneer eISCP scheduling reconnect after %s",
                reason,
            )
            self._connection_task = asyncio.create_task(
                self._connection_loop(),
                name=f"pioneer_eiscp_reconnect_{self.host}",
            )

    async def _connection_loop(self) -> None:
        """Connect with retry/backoff until success or closing."""
        while not self._closing and not self._connected:
            self._diagnostics.connect_attempts += 1
            self._diagnostics.reconnect_backoff_pending = False
            try:
                _LOGGER.debug(
                    "Pioneer eISCP connect attempt %d (session next=%d)",
                    self._diagnostics.connect_attempts,
                    self._session_id + 1,
                )
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self._connect_timeout,
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect loop
                self._diagnostics.connect_failures += 1
                _LOGGER.warning(
                    "Pioneer eISCP connect attempt failed (%s): %s; retrying in %ss",
                    type(err).__name__,
                    err,
                    self._reconnect_interval,
                )
                if self._closing:
                    return
                self._diagnostics.reconnect_backoff_pending = True
                await asyncio.sleep(self._reconnect_interval)
                continue

            await self._cancel_read_task()
            self._session_id += 1
            session_id = self._session_id
            self._reader = reader
            self._writer = writer
            self._buffer = b""
            self._connected = True
            self._active_read_session_id = session_id
            self._diagnostics.successful_connections += 1
            self._diagnostics.last_connected_at = _utc_now_iso()
            self._refresh_task_flags()

            _LOGGER.info("Pioneer eISCP session %d connected", session_id)

            self._read_task = asyncio.create_task(
                self._read_loop(session_id),
                name=f"pioneer_eiscp_read_{session_id}",
            )
            self._refresh_task_flags()

            if self._on_connected:
                result = self._on_connected()
                if asyncio.iscoroutine(result):
                    await result

            self._refresh_task_flags()
            return

    async def _cancel_read_task(self) -> None:
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        self._read_task = None
        self._refresh_task_flags()

    async def _close_transport(
        self,
        *,
        session_id: int | None,
        reason: str,
        intentional: bool = False,
    ) -> None:
        """Close sockets for the given session; ignore stale session callbacks."""
        if session_id is not None and session_id != self._active_read_session_id:
            _LOGGER.debug(
                "Pioneer eISCP ignoring close for stale session %d (active=%d)",
                session_id,
                self._active_read_session_id,
            )
            return

        was_connected = self._connected
        self._connected = False
        self._diagnostics.connected = False
        self._refresh_task_flags()

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001 - best effort close
                pass
        self._reader = None
        self._writer = None

        if reason == DISCONNECT_RECEIVER_EOF:
            self._diagnostics.receiver_closed_count += 1
        elif reason == DISCONNECT_LOCAL_CLOSE:
            self._diagnostics.local_disconnect_count += 1
            if session_id:
                _LOGGER.info("Pioneer eISCP session %d closed locally", session_id)

        if was_connected or intentional:
            self._diagnostics.last_disconnected_at = _utc_now_iso()
            self._diagnostics.last_disconnect_reason = reason

        if was_connected and self._on_disconnected and not self._closing:
            result = self._on_disconnected()
            if asyncio.iscoroutine(result):
                await result
        elif was_connected and intentional and self._on_disconnected:
            result = self._on_disconnected()
            if asyncio.iscoroutine(result):
                await result

        self._refresh_task_flags()

    async def _read_loop(self, session_id: int) -> None:
        assert self._reader is not None
        disconnect_reason = DISCONNECT_RECEIVER_EOF
        cleanup_needed = False

        try:
            while not self._closing and self._connected and session_id == self._active_read_session_id:
                try:
                    chunk = await asyncio.wait_for(
                        self._reader.read(4096),
                        timeout=self._read_timeout,
                    )
                except asyncio.TimeoutError:
                    continue

                if not chunk:
                    _LOGGER.warning(
                        "Pioneer eISCP session %d receiver closed connection",
                        session_id,
                    )
                    disconnect_reason = DISCONNECT_RECEIVER_EOF
                    cleanup_needed = True
                    break

                self._buffer += chunk
                frames, self._buffer = parse_packets(self._buffer)
                for frame in frames:
                    _LOGGER.debug("RX session %d %s", session_id, frame.raw_iscp)
                    if self._on_message:
                        result = self._on_message(frame)
                        if asyncio.iscoroutine(result):
                            await result

        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - trigger reconnect
            disconnect_reason = DISCONNECT_READ_ERROR
            cleanup_needed = True
            _LOGGER.warning(
                "Pioneer eISCP session %d read error (%s): %s",
                session_id,
                type(err).__name__,
                err,
            )

        if cleanup_needed:
            await self._finalize_read_loop(session_id, disconnect_reason)

    async def _finalize_read_loop(self, session_id: int, disconnect_reason: str) -> None:
        """Close a ended read session and optionally schedule reconnect."""
        if session_id != self._active_read_session_id:
            _LOGGER.debug(
                "Pioneer eISCP session %d read loop exiting (superseded by session %d)",
                session_id,
                self._active_read_session_id,
            )
            return

        if self._closing:
            return

        if disconnect_reason == DISCONNECT_LOCAL_CLOSE:
            return

        await self._close_transport(session_id=session_id, reason=disconnect_reason)
        if not self._closing:
            await self._schedule_reconnect(disconnect_reason)

    async def wait_connected(self, timeout: float = CONNECT_TIMEOUT) -> bool:
        """Wait until connected or timeout."""
        if self._connected:
            return True
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._connected:
                return True
            await asyncio.sleep(0.1)
        return self._connected
