"""Data update coordinator for Pioneer eISCP."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, RECOVERY_QUERY_INTERVAL
from .receiver import PioneerReceiver, ReceiverState

_LOGGER = logging.getLogger(__name__)


class PioneerEiscpCoordinator(DataUpdateCoordinator[ReceiverState]):
    """Coordinator bridging receiver state to Home Assistant."""

    def __init__(
        self,
        hass: HomeAssistant,
        receiver: PioneerReceiver,
        entry_id: str,
        device_name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=timedelta(seconds=RECOVERY_QUERY_INTERVAL),
        )
        self.receiver = receiver
        self.entry_id = entry_id
        self.device_name = device_name
        self._update_event = asyncio.Event()
        self.receiver.add_listener(self._update_event)

    async def _async_update_data(self) -> ReceiverState:
        """Return current receiver state.

        Primary updates arrive via unsolicited ISCP messages. This method
        runs occasionally for recovery queries when connected.
        """
        if self.receiver.connected:
            # Light recovery: re-query audio/video info only.
            try:
                await self.receiver.query_audio_info()
                await asyncio.sleep(0.1)
                await self.receiver.query_video_info()
            except ConnectionError:
                _LOGGER.debug("Recovery query skipped (not connected)")

        return self.receiver.state

    async def async_listen(self) -> None:
        """Wait for receiver-pushed state changes and notify HA."""
        while True:
            await self._update_event.wait()
            self._update_event.clear()
            self.async_set_updated_data(self.receiver.state)

    async def async_send_raw(self, iscp_command: str) -> None:
        """Send a raw ISCP command through the receiver."""
        await self.receiver.send_raw(iscp_command)

    async def async_probe_capabilities(self) -> None:
        """Run capability probe and refresh coordinator state."""
        await self.receiver.probe_capabilities()
        self.async_set_updated_data(self.receiver.state)

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic payload."""
        return {
            "host": self.receiver.host,
            "port": self.receiver.port,
            "connected": self.receiver.connected,
            "state": self.receiver.state.as_dict(),
            "capability_probe": self.receiver.capabilities.as_dict(),
        }
