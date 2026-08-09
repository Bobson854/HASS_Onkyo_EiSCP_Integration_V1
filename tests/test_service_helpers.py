"""Tests for config-entry service resolution and services.yaml contract."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest
import voluptuous as vol
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"
SERVICES_YAML = BASE / "services.yaml"


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

    selector_mod = types.ModuleType("homeassistant.helpers.selector")

    class ConfigEntrySelector:
        def __init__(self, config: dict) -> None:
            self.config = config

        def __call__(self, value: str) -> str:
            return str(value)

    selector_mod.ConfigEntrySelector = ConfigEntrySelector

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.selector = selector_mod
    service_mod = types.ModuleType("homeassistant.helpers.service")
    service_mod.async_get_config_entry = MagicMock()
    helpers.service = service_mod
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.selector"] = selector_mod
    sys.modules["homeassistant.helpers.service"] = service_mod

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    path = BASE / "const.py"
    spec = importlib.util.spec_from_file_location("pioneer_eiscp.const", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["pioneer_eiscp.const"] = module
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
ConfigEntrySelector = sys.modules["homeassistant.helpers.selector"].ConfigEntrySelector
ATTR_CONFIG_ENTRY = sys.modules["pioneer_eiscp.const"].ATTR_CONFIG_ENTRY
ATTR_ENTRY_ID = sys.modules["pioneer_eiscp.const"].ATTR_ENTRY_ID
ATTR_ISCP_COMMAND = sys.modules["pioneer_eiscp.const"].ATTR_ISCP_COMMAND
DOMAIN = sys.modules["pioneer_eiscp.const"].DOMAIN


@pytest.fixture(autouse=True)
def _reset_service_stubs() -> None:
    service_stub.async_get_config_entry = MagicMock()
    service_stub.async_get_config_entry.side_effect = None


def _services_data() -> dict:
    return yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))


def _probe_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
            vol.Optional(ATTR_ENTRY_ID): str,
        }
    )


def _send_raw_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(ATTR_ISCP_COMMAND): str,
            vol.Optional(ATTR_CONFIG_ENTRY): ConfigEntrySelector({"integration": DOMAIN}),
            vol.Optional(ATTR_ENTRY_ID): str,
        }
    )


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


class TestServicesYamlContract:
    """Regression for live HA target UI / schema mismatch failures."""

    def test_probe_capabilities_has_no_generic_target_block(self) -> None:
        services = _services_data()
        assert "target" not in services["probe_capabilities"]

    def test_send_raw_has_no_generic_target_block(self) -> None:
        services = _services_data()
        assert "target" not in services["send_raw"]

    def test_probe_capabilities_exposes_config_entry_selector(self) -> None:
        field = _services_data()["probe_capabilities"]["fields"]["config_entry"]
        assert field["name"] == "Receiver"
        assert field["required"] is False
        assert field["selector"]["config_entry"]["integration"] == "pioneer_eiscp"

    def test_send_raw_exposes_config_entry_selector(self) -> None:
        field = _services_data()["send_raw"]["fields"]["config_entry"]
        assert field["selector"]["config_entry"]["integration"] == "pioneer_eiscp"

    def test_services_yaml_field_names_match_registered_schemas(self) -> None:
        probe_fields = set(_services_data()["probe_capabilities"]["fields"])
        send_raw_fields = set(_services_data()["send_raw"]["fields"])
        assert probe_fields <= {ATTR_CONFIG_ENTRY}
        assert send_raw_fields <= {ATTR_ISCP_COMMAND, ATTR_CONFIG_ENTRY}

    def test_probe_schema_rejects_device_id(self) -> None:
        with pytest.raises(vol.MultipleInvalid, match="extra keys not allowed"):
            _probe_schema()({"device_id": ["abc123"]})

    def test_send_raw_schema_rejects_device_id(self) -> None:
        with pytest.raises(vol.MultipleInvalid, match="extra keys not allowed"):
            _send_raw_schema()(
                {
                    "iscp_command": "IFAQSTN",
                    "device_id": ["abc123"],
                }
            )


class TestResolveCoordinator:
    """Config-entry resolution for pioneer_eiscp services."""

    def test_single_entry_implicit_fallback(self) -> None:
        coordinator = _make_coordinator()
        config_entry = _make_config_entry(runtime_data=coordinator)
        service_stub.async_get_config_entry.return_value = config_entry

        result = helpers_mod.resolve_coordinator(MagicMock(), _make_call())

        assert result is coordinator
        service_stub.async_get_config_entry.assert_called_once_with(ANY, "pioneer_eiscp", None)

    def test_explicit_config_entry_field(self) -> None:
        coordinator = _make_coordinator(entry_id="entry_a")
        config_entry = _make_config_entry(entry_id="entry_a", runtime_data=coordinator)
        service_stub.async_get_config_entry.return_value = config_entry

        call = _make_call({"config_entry": "entry_a"})
        result = helpers_mod.resolve_coordinator(MagicMock(), call)

        assert result is coordinator
        service_stub.async_get_config_entry.assert_called_with(ANY, "pioneer_eiscp", "entry_a")

    def test_config_entry_preferred_over_legacy_entry_id(self) -> None:
        coordinator = _make_coordinator(entry_id="entry_a")
        config_entry = _make_config_entry(entry_id="entry_a", runtime_data=coordinator)
        service_stub.async_get_config_entry.return_value = config_entry

        call = _make_call({"config_entry": "entry_a", "entry_id": "entry_b"})
        helpers_mod.resolve_coordinator(MagicMock(), call)

        service_stub.async_get_config_entry.assert_called_with(ANY, "pioneer_eiscp", "entry_a")

    def test_multiple_entries_without_selection_raises(self) -> None:
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_found_multiple_config_entry_for_domain"
        )

        with pytest.raises(HomeAssistantError, match="Multiple Pioneer eISCP receivers"):
            helpers_mod.resolve_coordinator(MagicMock(), _make_call())

    def test_invalid_config_entry_raises(self) -> None:
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_config_entry_not_found"
        )

        call = _make_call({"config_entry": "missing"})
        with pytest.raises(HomeAssistantError, match="was not found"):
            helpers_mod.resolve_coordinator(MagicMock(), call)

    def test_unloaded_entry_raises(self) -> None:
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_config_entry_not_loaded"
        )

        with pytest.raises(HomeAssistantError, match="not loaded"):
            helpers_mod.resolve_coordinator(MagicMock(), _make_call())

    def test_no_runtime_data_raises(self) -> None:
        config_entry = _make_config_entry(runtime_data=None)
        service_stub.async_get_config_entry.return_value = config_entry

        with pytest.raises(HomeAssistantError, match="not loaded"):
            helpers_mod.resolve_coordinator(MagicMock(), _make_call())

    def test_disconnected_receiver_raises(self) -> None:
        coordinator = _make_coordinator(connected=False)
        config_entry = _make_config_entry(runtime_data=coordinator)
        service_stub.async_get_config_entry.return_value = config_entry

        with pytest.raises(HomeAssistantError, match="not connected"):
            helpers_mod.resolve_coordinator(MagicMock(), _make_call())

    def test_no_configured_receiver_raises(self) -> None:
        service_stub.async_get_config_entry.side_effect = ServiceValidationError(
            translation_key="service_found_no_config_entry_for_domain"
        )

        with pytest.raises(HomeAssistantError, match="No Pioneer eISCP receiver"):
            helpers_mod.resolve_coordinator(MagicMock(), _make_call())

    def test_legacy_entry_id_field_still_resolves(self) -> None:
        coordinator = _make_coordinator(entry_id="legacy")
        config_entry = _make_config_entry(entry_id="legacy", runtime_data=coordinator)
        service_stub.async_get_config_entry.return_value = config_entry

        call = _make_call({"entry_id": "legacy"})
        result = helpers_mod.resolve_coordinator(MagicMock(), call)

        assert result is coordinator

    def test_resolver_does_not_use_target_extraction(self) -> None:
        source = (BASE / "helpers.py").read_text(encoding="utf-8")
        assert "async_extract_config_entry_ids" not in source
        assert "call.target" not in source

    def test_send_raw_uses_same_resolver(self) -> None:
        init_source = (BASE / "__init__.py").read_text(encoding="utf-8")
        assert "from .helpers import resolve_coordinator" in init_source
        assert init_source.count("resolve_coordinator(hass, call)") == 2
