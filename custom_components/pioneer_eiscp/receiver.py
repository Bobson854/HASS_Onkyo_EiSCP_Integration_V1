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
    INPUT_SOURCE_TO_CODE,
    LISTENING_MODES,
    QUERY_SUFFIX,
    STARTUP_QUERIES,
    normalize_port,
)
from .protocol.framing import EiscpFrame
from .protocol.capability_probe import CapabilitySnapshot, run_capability_probe
from .protocol.nri_capabilities import ReceiverCapabilities, build_receiver_capabilities
from .protocol.parsers import (
    AudioInformation,
    VideoInformation,
    parse_audio_information,
    parse_input_code,
    parse_mute,
    parse_power,
    parse_video_information,
)
from .protocol.transport import EiscpConnection
from .protocol.listening_mode import (
    build_user_listening_mode_map,
    format_static_listening_mode,
    normalize_lmd_code,
    resolve_listening_mode_display,
    resolve_select_option,
)
from .protocol.volume import VolumeState, build_volume_state, format_mvl_parameter

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZoneState:
    """State for a receiver zone."""

    power: bool | None = None
    volume: int | None = None
    mute: bool | None = None
    input_code: str | None = None
    volume_state: VolumeState = field(default_factory=VolumeState)


@dataclass
class ReceiverState:
    """Internal receiver state updated from unsolicited ISCP messages."""

    main: ZoneState = field(default_factory=ZoneState)
    zone2: ZoneState = field(default_factory=ZoneState)
    listening_mode: str | None = None
    listening_mode_code: str | None = None
    listening_mode_source: str | None = None
    listening_mode_select_option: str | None = None
    listening_mode_select_match_source: str | None = None
    hdmi_output: str | None = None
    audio: AudioInformation = field(default_factory=AudioInformation)
    video: VideoInformation = field(default_factory=VideoInformation)
    raw_commands: dict[str, str] = field(default_factory=dict)
    connected: bool = False
    capability_probe: dict[str, Any] = field(default_factory=dict)
    receiver_capabilities: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return full internal state for diagnostics."""
        input_map = INPUT_SOURCES
        return {
            "connected": self.connected,
            "main": {
                "power": self.main.power,
                "volume": self.main.volume,
                "volume_raw": self.main.volume_state.raw_parameter,
                "volume_reference": self.main.volume_state.volume_reference,
                "volume_db": self.main.volume_state.volume_db,
                "mute": self.main.mute,
                "input_code": self.main.input_code,
                "input_name": input_map.get(self.main.input_code or "", "unknown"),
            },
            "zone2": {
                "power": self.zone2.power,
                "volume": self.zone2.volume,
                "mute": self.zone2.mute,
                "input_code": self.zone2.input_code,
            },
            "listening_mode": self.listening_mode,
            "listening_mode_code": self.listening_mode_code,
            "listening_mode_source": self.listening_mode_source,
            "listening_mode_select_option": self.listening_mode_select_option,
            "listening_mode_select_match_source": self.listening_mode_select_match_source,
            "hdmi_output": self.hdmi_output,
            "audio": self.audio.as_dict(),
            "video": self.video.as_dict(),
            "raw_commands": dict(self.raw_commands),
            "capability_probe": self.capability_probe,
            "receiver_capabilities": self.receiver_capabilities,
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
        self.receiver_capabilities_model = ReceiverCapabilities()
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

    def get_transport_diagnostics(self) -> dict[str, Any]:
        """Return transport lifecycle diagnostics."""
        return self._connection.get_diagnostics()

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
        """Set main zone absolute volume using decimal MVL parameter."""
        reference = self.volume_reference or 100
        absolute = max(0, min(reference, level))
        await self.send_raw(f"{CMD_VOLUME}{format_mvl_parameter(absolute)}")

    async def set_volume_level(self, volume_level: float) -> None:
        """Set main zone volume from Home Assistant 0..1 level."""
        reference = self.volume_reference or 100
        absolute = round(max(0.0, min(1.0, volume_level)) * reference)
        await self.set_volume(absolute)

    @property
    def volume_reference(self) -> int | None:
        """Return NRI-derived main-zone volume reference when available."""
        return self.receiver_capabilities_model.volume_reference

    def get_input_source_map(self) -> dict[str, str]:
        """Return code->name input map from NRI or static fallback."""
        nri_map = self.receiver_capabilities_model.input_source_map()
        return nri_map if nri_map else dict(INPUT_SOURCES)

    def get_input_source_reverse_map(self) -> dict[str, str]:
        """Return name->code input map from NRI or static fallback."""
        nri_map = self.receiver_capabilities_model.input_source_reverse_map()
        return nri_map if nri_map else dict(INPUT_SOURCE_TO_CODE)

    def get_listening_mode_map(self) -> dict[str, str]:
        """Return user-facing option label->command code map from NRI or static fallback."""
        nri_map = self.receiver_capabilities_model.listening_mode_map()
        if nri_map:
            return build_user_listening_mode_map(nri_map)
        return {
            format_static_listening_mode(name): code
            for code, name in LISTENING_MODES.items()
        }

    def get_listening_mode_options(self) -> list[str]:
        """Return sorted selectable listening-mode option labels."""
        return sorted(self.get_listening_mode_map())

    def resolve_listening_mode_select_option(self) -> tuple[str | None, str | None]:
        """Map exact receiver state to a valid select option, if possible."""
        options = self.get_listening_mode_options()
        return resolve_select_option(
            self.state.listening_mode,
            self.state.listening_mode_code,
            options,
        )

    def resolve_listening_mode_name(self, code: str | None) -> str | None:
        """Resolve an LMD response code to a display name for diagnostics."""
        display, _source = resolve_listening_mode_display(
            code,
            ifa_output_format=self.state.audio.output_format,
        )
        return display

    def _refresh_listening_mode_display(self) -> bool:
        """Recalculate listening-mode display from LMD code and IFA fallback."""
        display, source = resolve_listening_mode_display(
            self.state.listening_mode_code,
            ifa_output_format=self.state.audio.output_format,
        )
        changed = False
        if display != self.state.listening_mode or source != self.state.listening_mode_source:
            self.state.listening_mode = display
            self.state.listening_mode_source = source
            changed = True

        select_option, select_source = resolve_select_option(
            self.state.listening_mode,
            self.state.listening_mode_code,
            self.get_listening_mode_options(),
        )
        if (
            select_option != self.state.listening_mode_select_option
            or select_source != self.state.listening_mode_select_match_source
        ):
            self.state.listening_mode_select_option = select_option
            self.state.listening_mode_select_match_source = select_source
            changed = True
        return changed

    def apply_nri_payload(self, raw: str) -> ReceiverCapabilities:
        """Parse and store structured capabilities from an NRI payload."""
        capabilities = build_receiver_capabilities(raw)
        self.receiver_capabilities_model = capabilities
        self.state.receiver_capabilities = capabilities.as_dict()
        reference = capabilities.volume_reference
        if reference is not None:
            self.state.main.volume_state.volume_reference = reference
        if self.state.main.volume_state.raw_parameter:
            self._update_main_volume(self.state.main.volume_state.raw_parameter)
        self._refresh_listening_mode_display()
        self._notify_listeners()
        return capabilities

    def resolve_input_name(self, code: str | None) -> str:
        """Resolve an input selector code to a display name."""
        if not code:
            return "unknown"
        return self.get_input_source_map().get(code.upper(), "unknown")

    def get_state_dict(self) -> dict[str, Any]:
        """Return receiver state with NRI-aware derived fields."""
        data = self.state.as_dict()
        code = self.state.main.input_code or ""
        data["main"]["input_name"] = self.resolve_input_name(code or None)
        return data

    async def set_mute(self, muted: bool) -> None:
        """Set main zone mute."""
        await self.send_raw(f"{CMD_MUTE}{'01' if muted else '00'}")

    async def set_input(self, code: str) -> None:
        """Set main zone input by 2-char hex code."""
        await self.send_raw(f"{CMD_INPUT}{code.upper()}")

    async def set_listening_mode(self, code: str) -> None:
        """Set listening mode by receiver-provided code suffix."""
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
            nri_record = snapshot.responses.get("NRI", {})
            nri_raw = nri_record.get("raw")
            if isinstance(nri_raw, str) and nri_raw:
                self.apply_nri_payload(nri_raw)
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

    def _update_main_volume(self, parameter: str) -> None:
        volume_state = build_volume_state(
            parameter,
            volume_reference=self.volume_reference,
        )
        self.state.main.volume_state = volume_state
        if volume_state.absolute_volume is not None:
            self.state.main.volume = volume_state.absolute_volume

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
            previous = self.state.main.volume_state.raw_parameter
            self._update_main_volume(param)
            if param != previous or self.state.main.volume is not None:
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
            code = normalize_lmd_code(param) if param else None
            if code != self.state.listening_mode_code:
                self.state.listening_mode_code = code
                changed = True
            if self._refresh_listening_mode_display():
                changed = True

        elif cmd == CMD_AUDIO_INFO:
            self.state.audio = parse_audio_information(param)
            changed = True
            if self._refresh_listening_mode_display():
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
            volume_state = build_volume_state(param, volume_reference=self.volume_reference)
            if volume_state.absolute_volume != self.state.zone2.volume:
                self.state.zone2.volume = volume_state.absolute_volume
                changed = True

        elif cmd == "NRI":
            self.apply_nri_payload(param if param else frame.raw_iscp[3:])
            changed = True

        elif cmd == "HDO":
            if param != self.state.hdmi_output:
                self.state.hdmi_output = param
                changed = True

        if changed:
            self._notify_listeners()
