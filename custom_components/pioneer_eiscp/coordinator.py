"""Data update coordinator for Pioneer eISCP."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, RECOVERY_QUERY_INTERVAL
from .protocol.capability_probe import CapabilitySnapshot
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

        Primary updates arrive via unsolicited ISCP messages. Periodic IFA/IFV
        refresh is handled by the receiver information refresh scheduler.
        """
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

    async def async_probe_capabilities(self) -> dict[str, Any]:
        """Run capability probe, refresh coordinator state, return snapshot."""
        snapshot = await self.receiver.probe_capabilities()
        self.async_set_updated_data(self.receiver.state)
        return self.probe_service_response(snapshot)

    @staticmethod
    def build_probe_service_response(snapshot: CapabilitySnapshot) -> dict[str, Any]:
        """Build a JSON-serializable Developer Tools / service response payload."""
        capability_probe = snapshot.as_dict()
        responses = capability_probe.get("responses", {})
        response_count = sum(
            1 for record in responses.values() if not record.get("timed_out")
        )
        return {
            "config_entry_id": None,
            "receiver_name": None,
            "summary": {
                "responses": response_count,
                "timeouts": len(capability_probe.get("timeouts", [])),
                "parse_errors": len(capability_probe.get("parse_errors", [])),
            },
            "capability_probe": capability_probe,
        }

    def probe_service_response(self, snapshot: CapabilitySnapshot) -> dict[str, Any]:
        """Build probe service response including coordinator identity fields."""
        response = self.build_probe_service_response(snapshot)
        response["config_entry_id"] = self.entry_id
        response["receiver_name"] = self.device_name
        return response

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic payload."""
        return {
            "host": self.receiver.host,
            "port": self.receiver.port,
            "connected": self.receiver.connected,
            "transport": self.receiver.get_transport_diagnostics(),
            "info_refresh": self.receiver.get_info_refresh_diagnostics(),
            "state": self.receiver.get_state_dict(),
            "capability_probe": self.receiver.capabilities.as_dict(),
            "receiver_capabilities": self.receiver.receiver_capabilities_model.as_dict(),
        }
