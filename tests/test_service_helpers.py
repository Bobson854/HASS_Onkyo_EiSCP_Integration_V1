"""Tests for config-entry service resolution."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"


def _install_homeassistant_stubs() -> None:
    """Minimal Home Assistant stubs for helpers import."""
    if "homeassistant.helpers.service" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    const = types.ModuleType("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_PORT = "port"
    sys.modules["homeassistant.const"] = const

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        pass

    class ServiceCall:
        __slots__ = ("context", "data", "domain", "hass", "return_response", "service")

        def __init__(
            self,
            hass: HomeAssistant,
            domain: str,
            service: str,
            data: dict | None = None,
        ) -> None:
            self.hass = hass
            self.domain = domain
            self.service = service
            self.data = data or {}
            self.context = MagicMock()
            self.return_response = False

    core.HomeAssistant = HomeAssistant
    core.ServiceCall = ServiceCall
    sys.modules["homeassistant.core"] = core

    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ServiceValidationError(HomeAssistantError):
        def __init__(self, translation_key: str | None = None, **kwargs) -> None:
            super().__init__(translation_key or "validation error")
            self.translation_key = translation_key

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ServiceValidationError = ServiceValidationError
    sys.modules["homeassistant.exceptions"] = exceptions

    helpers = types.ModuleType("homeassistant.helpers")
    service_mod = types.ModuleType("homeassistant.helpers.service")
    service_mod.async_extract_config_entry_ids = AsyncMock(return_value=set())
    service_mod.async_get_config_entry = MagicMock()
    helpers.service = service_mod
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.service"] = service_mod

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    for name, rel in [
        ("pioneer_eiscp.const", "const.py"),
    ]:
        path = BASE / rel
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)


def _load_helpers():
    _install_homeassistant_stubs()
    name = "pioneer_eiscp.helpers"
    sys.modules.pop(name, None)
    path = BASE / "helpers.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


helpers_mod = _load_helpers()
HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError
ServiceValidationError = sys.modules["homeassistant.exceptions"].ServiceValidationError
service_stub = sys.modules["homeassistant.helpers.service"]
ServiceCall = sys.modules["homeassistant.core"].ServiceCall


@pytest.fixture(autouse=True)
def _reset_service_stubs() -> None:
    service_stub.async_extract_config_entry_ids = AsyncMock(return_value=set())
    service_stub.async_get_config_entry = MagicMock()
    service_stub.async_get_config_entry.side_effect = None


def _make_coordinator(*, connected: bool = True, entry_id: str = "entry1"):
    coordinator = MagicMock()
    coordinator.entry_id = entry_id
    coordinator.receiver = MagicMock(connected=connected)
    return coordinator


def _make_config_entry(*, entry_id: str = "entry1", runtime_data=None):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.domain = "pioneer_eiscp"
    entry.runtime_data = runtime_data
    entry.title = "VSX-1131"
    return entry


def _make_call(data: dict | None = None) -> ServiceCall:
    return ServiceCall(MagicMock(), "pioneer_eiscp", "probe_capabilities", data or {})


class TestServiceCallHasNoTargetAttribute:
    """Regression: ServiceCall.target does not exist in current Home Assistant."""

    def test_service_call_has_no_target_attribute(self) -> None:
        call = _make_call()
        assert not hasattr(call, "target")


class TestAsyncResolveCoordinator:
    """Config-entry resolution for pioneer_eiscp services."""

    @pytest.mark.asyncio
    async def test_single_entry_implicit_fallback(self) -> None:
        coordinator = _make_coordinator()
        config_entry = _make_config_entry(runtime_data=coordinator)
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.return_value = config_entry

        result = await helpers_mod.async_resolve_coordinator(MagicMock(), _make_call())

        assert result is coordinator
        service_stub.async_get_config_entry.assert_called_once_with(ANY, "pioneer_eiscp", None)

    @pytest.mark.asyncio
    async def test_explicit_config_entry_field(self) -> None:
        coordinator = _make_coordinator(entry_id="entry_a")
        config_entry = _make_config_entry(entry_id="entry_a", runtime_data=coordinator)
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.return_value = config_entry

        call = _make_call({"config_entry": "entry_a"})
        result = await helpers_mod.async_resolve_coordinator(MagicMock(), call)

        assert result is coordinator
        service_stub.async_get_config_entry.assert_called_with(ANY, "pioneer_eiscp", "entry_a")

    @pytest.mark.asyncio
    async def test_extracted_config_entry_from_target(self) -> None:
        coordinator = _make_coordinator(entry_id="entry_b")
        config_entry = _make_config_entry(entry_id="entry_b", runtime_data=coordinator)
        service_stub.async_extract_config_entry_ids.return_value = {"entry_b"}
        service_stub.async_get_config_entry.return_value = config_entry

        result = await helpers_mod.async_resolve_coordinator(MagicMock(), _make_call())

        assert result is coordinator
        service_stub.async_get_config_entry.assert_called_with(ANY, "pioneer_eiscp", "entry_b")

    @pytest.mark.asyncio
    async def test_multiple_entries_without_target_raises(self) -> None:
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_found_multiple_config_entry_for_domain"
        )

        with pytest.raises(HomeAssistantError, match="Multiple Pioneer eISCP receivers"):
            await helpers_mod.async_resolve_coordinator(MagicMock(), _make_call())

    @pytest.mark.asyncio
    async def test_multiple_explicit_targets_raises(self) -> None:
        service_stub.async_extract_config_entry_ids.return_value = {"entry_b"}

        call = _make_call({"config_entry": "entry_a"})
        with pytest.raises(HomeAssistantError, match="Multiple Pioneer eISCP receivers"):
            await helpers_mod.async_resolve_coordinator(MagicMock(), call)

    @pytest.mark.asyncio
    async def test_invalid_target_raises(self) -> None:
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_config_entry_not_found"
        )

        call = _make_call({"config_entry": "missing"})
        with pytest.raises(HomeAssistantError, match="was not found"):
            await helpers_mod.async_resolve_coordinator(MagicMock(), call)

    @pytest.mark.asyncio
    async def test_unloaded_entry_raises(self) -> None:
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_config_entry_not_loaded"
        )

        with pytest.raises(HomeAssistantError, match="not loaded"):
            await helpers_mod.async_resolve_coordinator(MagicMock(), _make_call())

    @pytest.mark.asyncio
    async def test_no_runtime_data_raises(self) -> None:
        config_entry = _make_config_entry(runtime_data=None)
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.return_value = config_entry

        with pytest.raises(HomeAssistantError, match="not loaded"):
            await helpers_mod.async_resolve_coordinator(MagicMock(), _make_call())

    @pytest.mark.asyncio
    async def test_disconnected_receiver_raises(self) -> None:
        coordinator = _make_coordinator(connected=False)
        config_entry = _make_config_entry(runtime_data=coordinator)
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.return_value = config_entry

        with pytest.raises(HomeAssistantError, match="not connected"):
            await helpers_mod.async_resolve_coordinator(MagicMock(), _make_call())

    @pytest.mark.asyncio
    async def test_no_configured_receiver_raises(self) -> None:
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_found_no_config_entry_for_domain"
        )

        with pytest.raises(HomeAssistantError, match="No Pioneer eISCP receiver"):
            await helpers_mod.async_resolve_coordinator(MagicMock(), _make_call())

    @pytest.mark.asyncio
    async def test_legacy_entry_id_field_still_resolves(self) -> None:
        coordinator = _make_coordinator(entry_id="legacy")
        config_entry = _make_config_entry(entry_id="legacy", runtime_data=coordinator)
        service_stub.async_extract_config_entry_ids.return_value = set()
        service_stub.async_get_config_entry.return_value = config_entry

        call = _make_call({"entry_id": "legacy"})
        result = await helpers_mod.async_resolve_coordinator(MagicMock(), call)

        assert result is coordinator

    @pytest.mark.asyncio
    async def test_send_raw_uses_same_resolver(self) -> None:
        """Both services import async_resolve_coordinator from helpers."""
        init_path = BASE / "__init__.py"
        source = init_path.read_text(encoding="utf-8")
        assert "from .helpers import async_resolve_coordinator" in source
        assert "from .helpers import resolve_coordinator" not in source
        assert "call.target" not in source
        helpers_source = (BASE / "helpers.py").read_text(encoding="utf-8")
        assert "call.target" not in helpers_source
