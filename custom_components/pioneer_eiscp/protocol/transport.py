"""Async eISCP TCP transport with reconnect support."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..const import CONNECT_TIMEOUT, READ_TIMEOUT, RECONNECT_INTERVAL
from .framing import EiscpFrame, build_packet, parse_packets

_LOGGER = logging.getLogger(__name__)

MessageCallback = Callable[[EiscpFrame], Awaitable[None] | None]
ConnectionCallback = Callable[[], Awaitable[None] | None]


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
        self._send_lock = asyncio.Lock()
        self._buffer = b""
        self._connected = False
        self._closing = False

    @property
    def connected(self) -> bool:
        """Return True when the TCP session is active."""
        return self._connected

    async def start(self) -> None:
        """Connect and begin the read loop."""
        self._closing = False
        await self._connect()

    async def stop(self) -> None:
        """Close the connection and cancel background tasks."""
        self._closing = True
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        self._read_task = None
        await self._close_socket()

    async def send(self, iscp_body: str) -> None:
        """Send a raw ISCP body (e.g. ``MVLQSTN``)."""
        if not self._writer or not self._connected:
            raise ConnectionError("Not connected to receiver")

        packet = build_packet(iscp_body)
        _LOGGER.debug("TX %s", iscp_body)

        async with self._send_lock:
            self._writer.write(packet)
            await self._writer.drain()

    async def _connect(self) -> None:
        while not self._closing:
            try:
                _LOGGER.debug(
                    "Connecting to %s:%s (timeout=%ss)",
                    self.host,
                    self.port,
                    self._connect_timeout,
                )
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self._connect_timeout,
                )
                self._buffer = b""
                self._connected = True
                _LOGGER.info("Connected to %s:%s", self.host, self.port)

                if self._on_connected:
                    result = self._on_connected()
                    if asyncio.iscoroutine(result):
                        await result

                self._read_task = asyncio.create_task(
                    self._read_loop(),
                    name=f"pioneer_eiscp_read_{self.host}",
                )
                return

            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect loop
                _LOGGER.warning(
                    "Connection to %s:%s failed: %s; retrying in %ss",
                    self.host,
                    self.port,
                    err,
                    self._reconnect_interval,
                )
                await self._close_socket()
                if self._closing:
                    return
                await asyncio.sleep(self._reconnect_interval)

    async def _close_socket(self) -> None:
        was_connected = self._connected
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001 - best effort close
                pass
        self._reader = None
        self._writer = None

        if was_connected and self._on_disconnected and not self._closing:
            result = self._on_disconnected()
            if asyncio.iscoroutine(result):
                await result

    async def _read_loop(self) -> None:
        assert self._reader is not None

        try:
            while not self._closing and self._connected:
                try:
                    chunk = await asyncio.wait_for(
                        self._reader.read(4096),
                        timeout=self._read_timeout,
                    )
                except asyncio.TimeoutError:
                    # Idle connection; receiver sends unsolicited updates when state changes.
                    continue

                if not chunk:
                    _LOGGER.warning("Receiver closed connection")
                    break

                self._buffer += chunk
                frames, self._buffer = parse_packets(self._buffer)
                for frame in frames:
                    _LOGGER.debug("RX %s", frame.raw_iscp)
                    if self._on_message:
                        result = self._on_message(frame)
                        if asyncio.iscoroutine(result):
                            await result

        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - trigger reconnect
            _LOGGER.exception("Read loop error")
        finally:
            await self._close_socket()
            if not self._closing:
                _LOGGER.info("Scheduling reconnect to %s:%s", self.host, self.port)
                asyncio.create_task(self._connect())

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
