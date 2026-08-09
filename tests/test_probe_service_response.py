"""Tests for probe_capabilities service response handling."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"
PROTOCOL = BASE / "protocol"


def _load_coordinator_module():
    for mod in list(sys.modules):
        if mod.startswith("pioneer_eiscp"):
            del sys.modules[mod]

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = MagicMock
    core.ServiceCall = MagicMock
    core.ServiceResponse = dict
    core.SupportsResponse = types.SimpleNamespace(NONE="none", OPTIONAL="optional", ONLY="only")
    sys.modules["homeassistant.core"] = core

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def async_set_updated_data(self, _data) -> None:
            pass

        def __class_getitem__(cls, item):
            return cls

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    proto_pkg = types.ModuleType("pioneer_eiscp.protocol")
    proto_pkg.__path__ = [str(PROTOCOL)]
    sys.modules["pioneer_eiscp.protocol"] = proto_pkg

    for name, rel in [
        ("pioneer_eiscp.const", "const.py"),
        ("pioneer_eiscp.capability_commands", "capability_commands.py"),
        ("pioneer_eiscp.protocol.framing", "protocol/framing.py"),
        ("pioneer_eiscp.protocol.parsers", "protocol/parsers.py"),
        ("pioneer_eiscp.protocol.nri_parser", "protocol/nri_parser.py"),
        ("pioneer_eiscp.protocol.capability_probe", "protocol/capability_probe.py"),
        ("pioneer_eiscp.protocol.transport", "protocol/transport.py"),
        ("pioneer_eiscp.receiver", "receiver.py"),
    ]:
        path = BASE / rel if not rel.startswith("protocol/") else BASE / rel
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    name = "pioneer_eiscp.coordinator"
    sys.modules.pop(name, None)
    path = BASE / "coordinator.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


coordinator_mod = _load_coordinator_module()
CapabilitySnapshot = sys.modules["pioneer_eiscp.protocol.capability_probe"].CapabilitySnapshot
PioneerEiscpCoordinator = coordinator_mod.PioneerEiscpCoordinator


def _sample_snapshot(*, with_nri: bool = True, timed_out: bool = False) -> CapabilitySnapshot:
    snapshot = CapabilitySnapshot(last_probe="2026-01-01T00:00:00+00:00")
    if timed_out:
        snapshot.timeouts.append("NRIQSTN")
        snapshot.unsupported.append("NRIQSTN")
        snapshot.responses["NRI"] = {
            "query": "NRIQSTN",
            "command": "NRI",
            "raw": None,
            "parsed": None,
            "parse_error": None,
            "received_at": None,
            "timed_out": True,
        }
    elif with_nri:
        snapshot.responses["NRI"] = {
            "query": "NRIQSTN",
            "command": "NRI",
            "raw": "<response><device id='x'/></response>",
            "parsed": {"raw": "<response><device id='x'/></response>", "parsed": {"device": {"@id": "x"}}, "parse_error": None},
            "parse_error": None,
            "received_at": "2026-01-01T00:00:01+00:00",
            "timed_out": False,
        }
        snapshot.responses["PWR"] = {
            "query": "PWRQSTN",
            "command": "PWR",
            "raw": "PWR01",
            "parsed": {"power": True, "parameter": "01"},
            "parse_error": None,
            "received_at": "2026-01-01T00:00:02+00:00",
            "timed_out": False,
        }
        snapshot.parse_errors.append("IFA: bad parse")
    return snapshot


def _make_coordinator() -> PioneerEiscpCoordinator:
    coordinator = PioneerEiscpCoordinator.__new__(PioneerEiscpCoordinator)
    coordinator.entry_id = "entry123"
    coordinator.device_name = "VSX-1131"
    coordinator.receiver = MagicMock()
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


class TestProbeServiceResponse:
    """Regression for Developer Tools NoneType response failure."""

    def test_build_probe_service_response_is_dict(self) -> None:
        response = PioneerEiscpCoordinator.build_probe_service_response(_sample_snapshot())
        assert isinstance(response, dict)

    def test_build_probe_service_response_is_json_serializable(self) -> None:
        response = PioneerEiscpCoordinator.build_probe_service_response(_sample_snapshot())
        json.dumps(response)

    def test_response_contains_summary_and_capability_probe(self) -> None:
        coordinator = _make_coordinator()
        response = coordinator.probe_service_response(_sample_snapshot())

        assert response["config_entry_id"] == "entry123"
        assert response["receiver_name"] == "VSX-1131"
        assert response["summary"]["responses"] == 2
        assert response["summary"]["timeouts"] == 0
        assert response["summary"]["parse_errors"] == 1
        assert "capability_probe" in response
        assert "NRI" in response["capability_probe"]["responses"]
        assert response["capability_probe"]["responses"]["NRI"]["raw"].startswith("<response")

    def test_timeout_only_probe_still_returns_dict(self) -> None:
        response = PioneerEiscpCoordinator.build_probe_service_response(
            _sample_snapshot(with_nri=False, timed_out=True)
        )
        assert isinstance(response, dict)
        assert response["summary"]["responses"] == 0
        assert response["summary"]["timeouts"] == 1
        json.dumps(response)

    def test_parse_error_probe_still_returns_dict(self) -> None:
        response = PioneerEiscpCoordinator.build_probe_service_response(_sample_snapshot())
        assert response["summary"]["parse_errors"] == 1
        json.dumps(response)

    @pytest.mark.asyncio
    async def test_async_probe_capabilities_returns_dict_not_none(self) -> None:
        coordinator = _make_coordinator()
        snapshot = _sample_snapshot()
        coordinator.receiver.probe_capabilities = AsyncMock(return_value=snapshot)

        result = await coordinator.async_probe_capabilities()

        assert result is not None
        assert isinstance(result, dict)
        assert result["capability_probe"]["responses"]["NRI"]["raw"]
        coordinator.receiver.probe_capabilities.assert_awaited_once()
        coordinator.async_set_updated_data.assert_called_once()

    def test_init_registers_supports_response_only_for_probe(self) -> None:
        source = (BASE / "__init__.py").read_text(encoding="utf-8")
        assert "supports_response=SupportsResponse.ONLY" in source
        assert "supports_response=SupportsResponse.NONE" in source
        assert "supports_response=False" not in source
        assert "-> ServiceResponse" in source

    def test_send_raw_handler_returns_none_type_hint(self) -> None:
        source = (BASE / "__init__.py").read_text(encoding="utf-8")
        assert "async def handle_send_raw(call: ServiceCall) -> None:" in source
        assert "supports_response=SupportsResponse.NONE" in source

    @pytest.mark.asyncio
    async def test_handler_returns_dict_from_coordinator(self) -> None:
        init_source = (BASE / "__init__.py").read_text(encoding="utf-8")
        assert "return await coordinator.async_probe_capabilities()" in init_source

        coordinator = _make_coordinator()
        expected = coordinator.probe_service_response(_sample_snapshot())
        coordinator.receiver.probe_capabilities = AsyncMock(return_value=_sample_snapshot())

        result = await coordinator.async_probe_capabilities()

        assert result == expected
        assert result is not None
