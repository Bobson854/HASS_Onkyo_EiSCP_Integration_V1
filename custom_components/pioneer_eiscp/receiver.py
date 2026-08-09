"""Receiver state and command handling (protocol layer, not HA entities)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .const import (
    CMD_AUDIO_INFO,
    CMD_INPUT,
    CMD_LISTENING_MODE,
    CMD_MUTE,
    CMD_POWER,
    CMD_VIDEO_INFO,
    CMD_VOLUME,
    CMD_ZONE2_INPUT,
    CMD_ZONE2_POWER,
    CMD_ZONE2_VOLUME,
    INPUT_SOURCES,
    LISTENING_MODES,
    QUERY_SUFFIX,
    STARTUP_QUERIES,
    normalize_port,
)
from .protocol.framing import EiscpFrame
from .protocol.capability_probe import CapabilitySnapshot, run_capability_probe
from .protocol.parsers import (
    AudioInformation,
    VideoInformation,
    parse_audio_information,
    parse_input_code,
    parse_mute,
    parse_power,
    parse_video_information,
    parse_volume_hex,
)
from .protocol.transport import EiscpConnection

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZoneState:
    """State for a receiver zone."""

    power: bool | None = None
    volume: int | None = None
    mute: bool | None = None
    input_code: str | None = None


@dataclass
class ReceiverState:
    """Internal receiver state updated from unsolicited ISCP messages."""

    main: ZoneState = field(default_factory=ZoneState)
    zone2: ZoneState = field(default_factory=ZoneState)
    listening_mode: str | None = None
    listening_mode_code: str | None = None
    hdmi_output: str | None = None
    audio: AudioInformation = field(default_factory=AudioInformation)
    video: VideoInformation = field(default_factory=VideoInformation)
    raw_commands: dict[str, str] = field(default_factory=dict)
    connected: bool = False
    capability_probe: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return full internal state for diagnostics."""
        return {
            "connected": self.connected,
            "main": {
                "power": self.main.power,
                "volume": self.main.volume,
                "mute": self.main.mute,
                "input_code": self.main.input_code,
                "input_name": INPUT_SOURCES.get(self.main.input_code or "", "unknown"),
            },
            "zone2": {
                "power": self.zone2.power,
                "volume": self.zone2.volume,
                "mute": self.zone2.mute,
                "input_code": self.zone2.input_code,
            },
            "listening_mode": self.listening_mode,
            "listening_mode_code": self.listening_mode_code,
            "hdmi_output": self.hdmi_output,
            "audio": self.audio.as_dict(),
            "video": self.video.as_dict(),
            "raw_commands": dict(self.raw_commands),
            "capability_probe": self.capability_probe,
        }


class PioneerReceiver:
    """High-level receiver interface over eISCP transport."""

    def __init__(self, host: str, port: int | float | str) -> None:
        self.host = host
        self.port = normalize_port(port)
        self.state = ReceiverState()
        self._listeners: list[asyncio.Event] = []
        self._probe_waiters: dict[str, asyncio.Future[EiscpFrame]] = {}
        self._probe_lock = asyncio.Lock()
        self.capabilities = CapabilitySnapshot()
        self._connection = EiscpConnection(
            host,
            port,
            on_message=self._handle_frame,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )

    async def start(self) -> None:
        """Start the persistent connection."""
        await self._connection.start()

    async def stop(self) -> None:
        """Stop the connection."""
        await self._connection.stop()

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connection.connected

    def add_listener(self, event: asyncio.Event) -> None:
        """Register a listener notified on state changes."""
        self._listeners.append(event)

    def remove_listener(self, event: asyncio.Event) -> None:
        """Remove a previously registered listener."""
        if event in self._listeners:
            self._listeners.remove(event)

    def _notify_listeners(self) -> None:
        for listener in self._listeners:
            listener.set()

    async def send_raw(self, iscp_body: str) -> None:
        """Send a raw ISCP command body."""
        await self._connection.send(iscp_body)

    async def query_startup_state(self) -> None:
        """Query receiver state after connect/reconnect."""
        for command in STARTUP_QUERIES:
            try:
                await self._connection.send(command)
                await asyncio.sleep(0.15)
            except ConnectionError:
                _LOGGER.debug("Startup query skipped (not connected): %s", command)
                break

    async def set_power(self, on: bool) -> None:
        """Set main zone power."""
        await self.send_raw(f"{CMD_POWER}{'01' if on else '00'}")

    async def set_volume(self, level: int) -> None:
        """Set main zone volume (0-100)."""
        level = max(0, min(100, level))
        await self.send_raw(f"{CMD_VOLUME}{level:02X}")

    async def set_mute(self, muted: bool) -> None:
        """Set main zone mute."""
        await self.send_raw(f"{CMD_MUTE}{'01' if muted else '00'}")

    async def set_input(self, code: str) -> None:
        """Set main zone input by 2-char hex code."""
        await self.send_raw(f"{CMD_INPUT}{code.upper()}")

    async def set_listening_mode(self, code: str) -> None:
        """Set listening mode by 2-char hex code."""
        await self.send_raw(f"{CMD_LISTENING_MODE}{code.upper()}")

    async def query_audio_info(self) -> None:
        """Request IFA audio information."""
        await self.send_raw(f"{CMD_AUDIO_INFO}{QUERY_SUFFIX}")

    async def query_video_info(self) -> None:
        """Request IFV video information."""
        await self.send_raw(f"{CMD_VIDEO_INFO}{QUERY_SUFFIX}")

    async def probe_capabilities(self) -> CapabilitySnapshot:
        """Run a manual read-only capability probe using the live connection."""
        if not self.connected:
            raise ConnectionError("Not connected to receiver")

        async with self._probe_lock:
            snapshot = await run_capability_probe(
                self.send_raw,
                self._probe_wait_for,
            )
            self.capabilities = snapshot
            self.state.capability_probe = snapshot.as_dict()
            self._notify_listeners()
            return snapshot

    async def _probe_wait_for(self, command: str, timeout: float) -> EiscpFrame | None:
        """Wait for a correlated probe response by 3-letter command prefix."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[EiscpFrame] = loop.create_future()
        self._probe_waiters[command] = future
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            if self._probe_waiters.get(command) is future:
                del self._probe_waiters[command]

    async def _on_connected(self) -> None:
        self.state.connected = True
        self._notify_listeners()
        await self.query_startup_state()

    async def _on_disconnected(self) -> None:
        self.state.connected = False
        self._notify_listeners()

    async def _handle_frame(self, frame: EiscpFrame) -> None:
        """Process an incoming ISCP frame and update internal state."""
        waiter = self._probe_waiters.get(frame.command)
        if waiter and not waiter.done():
            waiter.set_result(frame)

        cmd = frame.command
        param = frame.parameter
        self.state.raw_commands[cmd] = frame.raw_iscp
        changed = False

        if cmd == CMD_POWER:
            power = parse_power(param)
            if power is not None and power != self.state.main.power:
                self.state.main.power = power
                changed = True

        elif cmd == CMD_VOLUME:
            volume = parse_volume_hex(param)
            if volume is not None and volume != self.state.main.volume:
                self.state.main.volume = volume
                changed = True

        elif cmd == CMD_MUTE:
            mute = parse_mute(param)
            if mute is not None and mute != self.state.main.mute:
                self.state.main.mute = mute
                changed = True

        elif cmd == CMD_INPUT:
            code = parse_input_code(param)
            if code is not None and code != self.state.main.input_code:
                self.state.main.input_code = code
                changed = True

        elif cmd == CMD_LISTENING_MODE:
            code = param.strip().upper()[:2] if param else None
            name = LISTENING_MODES.get(code or "", code)
            if code != self.state.listening_mode_code:
                self.state.listening_mode_code = code
                self.state.listening_mode = name
                changed = True

        elif cmd == CMD_AUDIO_INFO:
            self.state.audio = parse_audio_information(param)
            changed = True

        elif cmd == CMD_VIDEO_INFO:
            self.state.video = parse_video_information(param)
            changed = True

        elif cmd == CMD_ZONE2_POWER:
            power = parse_power(param)
            if power is not None and power != self.state.zone2.power:
                self.state.zone2.power = power
                changed = True

        elif cmd == CMD_ZONE2_INPUT:
            code = parse_input_code(param)
            if code is not None and code != self.state.zone2.input_code:
                self.state.zone2.input_code = code
                changed = True

        elif cmd == CMD_ZONE2_VOLUME:
            volume = parse_volume_hex(param)
            if volume is not None and volume != self.state.zone2.volume:
                self.state.zone2.volume = volume
                changed = True

        elif cmd == "HDO":
            if param != self.state.hdmi_output:
                self.state.hdmi_output = param
                changed = True

        if changed:
            self._notify_listeners()
