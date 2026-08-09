"""Scheduled IFA/IFV information refresh while the receiver is powered on."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .const import (
    CMD_LISTENING_MODE,
    INFO_REFRESH_INTERVAL,
    INFO_REFRESH_LISTENING_MODE_SETTLE,
    INFO_REFRESH_POWER_ON_DELAY,
    INFO_REFRESH_QUERY_GAP,
    INFO_REFRESH_SOURCE_CHANGE_DELAY,
    QUERY_SUFFIX,
)

if TYPE_CHECKING:
    from .receiver import PioneerReceiver

_LOGGER = logging.getLogger(__name__)

REFRESH_REASON_PERIODIC = "periodic"
REFRESH_REASON_POWER_ON = "power_on"
REFRESH_REASON_SOURCE_CHANGE = "source_change"
REFRESH_REASON_LISTENING_MODE_CHANGE = "listening_mode_change"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class InfoRefreshDiagnostics:
    """Diagnostics for information refresh scheduling."""

    periodic_enabled: bool = False
    interval_seconds: float = INFO_REFRESH_INTERVAL
    task_active: bool = False
    last_refresh_at: str | None = None
    last_refresh_reason: str | None = None
    pending_delayed_refresh: bool = False
    pending_delayed_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "periodic_enabled": self.periodic_enabled,
            "interval_seconds": self.interval_seconds,
            "task_active": self.task_active,
            "last_refresh_at": self.last_refresh_at,
            "last_refresh_reason": self.last_refresh_reason,
            "pending_delayed_refresh": self.pending_delayed_refresh,
            "pending_delayed_reason": self.pending_delayed_reason,
        }


@dataclass
class _DelayedRequest:
    delay: float
    reason: str
    include_lmd: bool = False


class InfoRefreshScheduler:
    """Own periodic and delayed IFA/IFV refresh for one receiver."""

    def __init__(self, receiver: PioneerReceiver) -> None:
        self._receiver = receiver
        self._closing = False
        self._periodic_task: asyncio.Task[None] | None = None
        self._delayed_task: asyncio.Task[None] | None = None
        self._delayed_request: _DelayedRequest | None = None
        self._diagnostics = InfoRefreshDiagnostics()

    def get_diagnostics(self) -> dict[str, Any]:
        self._refresh_task_flags()
        return self._diagnostics.as_dict()

    def _refresh_task_flags(self) -> None:
        self._diagnostics.task_active = (
            self._periodic_task is not None and not self._periodic_task.done()
        )
        self._diagnostics.pending_delayed_refresh = (
            self._delayed_task is not None and not self._delayed_task.done()
        )
        self._diagnostics.pending_delayed_reason = (
            self._delayed_request.reason if self._delayed_request else None
        )

    async def start(self) -> None:
        """Start periodic refresh when conditions allow."""
        self._closing = False
        await self._ensure_periodic()

    async def stop(self) -> None:
        """Stop all refresh work."""
        self._closing = True
        await self._cancel_delayed()
        await self._cancel_periodic()

    async def on_connected(self) -> None:
        """Resume periodic refresh after transport connect."""
        if self._closing:
            return
        await self._ensure_periodic()

    async def on_disconnected(self) -> None:
        """Suppress refresh while transport is disconnected."""
        await self._cancel_delayed()
        await self._cancel_periodic()

    async def on_power_changed(self, previous: bool | None, current: bool | None) -> None:
        """Schedule or suppress refresh on main-zone power transitions."""
        if current is False:
            await self._cancel_delayed()
            await self._cancel_periodic()
            return

        if current is True and previous is not True:
            self.schedule_delayed(
                INFO_REFRESH_POWER_ON_DELAY,
                REFRESH_REASON_POWER_ON,
                include_lmd=True,
            )
            await self._ensure_periodic()

    def on_source_changed(self) -> None:
        """Schedule refresh after an input/source change."""
        self.schedule_delayed(
            INFO_REFRESH_SOURCE_CHANGE_DELAY,
            REFRESH_REASON_SOURCE_CHANGE,
        )

    def schedule_delayed(
        self,
        delay: float,
        reason: str,
        *,
        include_lmd: bool = False,
    ) -> None:
        """Schedule a one-shot information refresh."""
        if self._closing:
            return

        if (
            reason == REFRESH_REASON_POWER_ON
            and self._delayed_request is not None
            and self._delayed_request.reason == REFRESH_REASON_POWER_ON
            and self._delayed_task is not None
            and not self._delayed_task.done()
        ):
            return

        self._delayed_request = _DelayedRequest(
            delay=delay,
            reason=reason,
            include_lmd=include_lmd,
        )
        if self._delayed_task and not self._delayed_task.done():
            self._delayed_task.cancel()
        self._delayed_task = asyncio.create_task(
            self._run_delayed(),
            name="pioneer_eiscp_info_refresh_delayed",
        )
        self._refresh_task_flags()

    async def refresh_after_listening_mode_command(self) -> None:
        """Refresh IFA after a listening-mode command settles."""
        await asyncio.sleep(INFO_REFRESH_LISTENING_MODE_SETTLE)
        await self._refresh_information(
            REFRESH_REASON_LISTENING_MODE_CHANGE,
            include_ifv=False,
        )

    def _should_refresh(self) -> bool:
        return (
            not self._closing
            and self._receiver.connected
            and self._receiver.state.main.power is True
        )

    async def _ensure_periodic(self) -> None:
        if self._closing or not self._should_refresh():
            return
        if self._periodic_task and not self._periodic_task.done():
            return
        self._diagnostics.periodic_enabled = True
        self._periodic_task = asyncio.create_task(
            self._periodic_loop(),
            name="pioneer_eiscp_info_refresh_periodic",
        )
        self._refresh_task_flags()

    async def _cancel_periodic(self) -> None:
        if self._periodic_task and not self._periodic_task.done():
            self._periodic_task.cancel()
            try:
                await self._periodic_task
            except asyncio.CancelledError:
                pass
        self._periodic_task = None
        self._diagnostics.periodic_enabled = False
        self._refresh_task_flags()

    async def _cancel_delayed(self) -> None:
        if self._delayed_task and not self._delayed_task.done():
            self._delayed_task.cancel()
            try:
                await self._delayed_task
            except asyncio.CancelledError:
                pass
        self._delayed_task = None
        self._delayed_request = None
        self._refresh_task_flags()

    async def _run_delayed(self) -> None:
        request = self._delayed_request
        if request is None:
            return
        try:
            await asyncio.sleep(request.delay)
            if self._should_refresh():
                await self._refresh_information(
                    request.reason,
                    include_lmd=request.include_lmd,
                )
        except asyncio.CancelledError:
            raise
        finally:
            if self._delayed_task is asyncio.current_task():
                self._delayed_task = None
                self._delayed_request = None
                self._refresh_task_flags()

    async def _periodic_loop(self) -> None:
        try:
            while not self._closing:
                await asyncio.sleep(INFO_REFRESH_INTERVAL)
                if self._should_refresh():
                    await self._refresh_information(REFRESH_REASON_PERIODIC)
                elif not self._receiver.connected or self._receiver.state.main.power is False:
                    break
        except asyncio.CancelledError:
            raise
        finally:
            if self._periodic_task is asyncio.current_task():
                self._periodic_task = None
                self._diagnostics.periodic_enabled = False
                self._refresh_task_flags()

    async def _refresh_information(
        self,
        reason: str,
        *,
        include_lmd: bool = False,
        include_ifv: bool = True,
    ) -> None:
        if not self._should_refresh() and reason == REFRESH_REASON_PERIODIC:
            return
        if not self._receiver.connected:
            return

        try:
            if include_lmd:
                await self._receiver.send_raw(f"{CMD_LISTENING_MODE}{QUERY_SUFFIX}")
                await asyncio.sleep(INFO_REFRESH_QUERY_GAP)
            await self._receiver.query_audio_info()
            if include_ifv:
                await asyncio.sleep(INFO_REFRESH_QUERY_GAP)
                await self._receiver.query_video_info()
            self._diagnostics.last_refresh_at = _utc_now_iso()
            self._diagnostics.last_refresh_reason = reason
            _LOGGER.debug("Information refresh completed (%s)", reason)
        except ConnectionError:
            _LOGGER.debug("Information refresh skipped (not connected): %s", reason)
