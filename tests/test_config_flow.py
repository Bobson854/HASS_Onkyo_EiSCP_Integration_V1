"""Regression tests for config flow schema and setup dialog."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"


def _install_homeassistant_stubs() -> None:
    """Minimal Home Assistant stubs so config_flow can be imported in tests."""
    if "homeassistant.helpers.selector" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigFlow:
        """Stub ConfigFlow base."""

        VERSION = 1
        domain: str | None = None

        def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
            cls.domain = domain

        def __init__(self) -> None:
            self.hass = MagicMock()
            self.context: dict[str, Any] = {}

        async def async_set_unique_id(self, unique_id: str) -> None:
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            pass

        def _get_reconfigure_entry(self):
            return MagicMock()

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_update_reload_and_abort(self, *args, **kwargs):
            return {"type": "update_reload_and_abort", **kwargs}

    class ConfigFlowResult(dict):
        pass

    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = ConfigFlowResult
    sys.modules["homeassistant.config_entries"] = config_entries

    const = types.ModuleType("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_NAME = "name"
    const.CONF_PORT = "port"
    sys.modules["homeassistant.const"] = const

    selector_mod = types.ModuleType("homeassistant.helpers.selector")

    class TextSelectorType:
        TEXT = "text"

    class TextSelectorConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class TextSelector:
        def __init__(self, config: TextSelectorConfig) -> None:
            self.config = config

        def __voluptuous_compile__(self, _schema: Any) -> Any:
            return lambda _path, value: value

    class NumberSelectorMode:
        BOX = "box"
        SLIDER = "slider"

    class NumberSelectorConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class NumberSelector:
        def __init__(self, config: NumberSelectorConfig) -> None:
            self.config = config

        def __voluptuous_compile__(self, _schema: Any) -> Any:
            return lambda _path, value: value

    selector_mod.TextSelectorType = TextSelectorType
    selector_mod.TextSelectorConfig = TextSelectorConfig
    selector_mod.TextSelector = TextSelector
    selector_mod.NumberSelectorMode = NumberSelectorMode
    selector_mod.NumberSelectorConfig = NumberSelectorConfig
    selector_mod.NumberSelector = NumberSelector

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.selector = selector_mod
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.selector"] = selector_mod

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    proto_pkg = types.ModuleType("pioneer_eiscp.protocol")
    proto_pkg.__path__ = [str(BASE / "protocol")]
    sys.modules["pioneer_eiscp.protocol"] = proto_pkg

    for name, rel in [
        ("pioneer_eiscp.const", "const.py"),
        ("pioneer_eiscp.protocol.framing", "protocol/framing.py"),
        ("pioneer_eiscp.config_validation", "config_validation.py"),
    ]:
        path = BASE / rel
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)


def _load_config_flow():
    _install_homeassistant_stubs()
    name = "pioneer_eiscp.config_flow"
    # Force reload so config_flow picks up selector stub updates.
    sys.modules.pop(name, None)
    path = BASE / "config_flow.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cf = _load_config_flow()
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
DEFAULT_PORT = cf.DEFAULT_PORT
DEFAULT_NAME = cf.DEFAULT_NAME


def _schema_key_default(schema: vol.Schema, field: str) -> Any:
    """Return the voluptuous default for a named field, or vol.UNDEFINED."""
    for key in schema.schema:
        key_field = key.schema if isinstance(key, (vol.Required, vol.Optional)) else key
        if key_field == field:
            default = getattr(key, "default", vol.UNDEFINED)
            if default is vol.UNDEFINED:
                return vol.UNDEFINED
            if callable(default):
                return default()
            return default
    raise KeyError(field)


def _schema_field_selector_config(schema: vol.Schema, field: str) -> dict[str, Any]:
    """Return kwargs passed to TextSelectorConfig for a schema field."""
    selector_obj = schema.schema[
        next(k for k in schema.schema if getattr(k, "schema", k) == field)
    ]
    return selector_obj.config.kwargs


class TestConnectionSchemaInitial:
    """Initial setup schema must open without unsupported selector APIs."""

    def test_construction_succeeds(self) -> None:
        schema = cf._connection_schema_initial()
        assert isinstance(schema, vol.Schema)

    def test_host_has_no_default(self) -> None:
        default = _schema_key_default(cf._connection_schema_initial(), CONF_HOST)
        assert default is vol.UNDEFINED

    def test_port_defaults_to_60128(self) -> None:
        default = _schema_key_default(cf._connection_schema_initial(), CONF_PORT)
        assert default == DEFAULT_PORT

    def test_name_defaults(self) -> None:
        default = _schema_key_default(cf._connection_schema_initial(), CONF_NAME)
        assert default == DEFAULT_NAME

    def test_host_selector_does_not_use_text_selector_type_host(self) -> None:
        kwargs = cf._HOST_SELECTOR.config.kwargs
        assert "type" not in kwargs
        source = (BASE / "config_flow.py").read_text(encoding="utf-8")
        assert "TextSelectorType.HOST" not in source


class TestConnectionSchemaReconfigure:
    """Reconfigure schema pre-fills existing entry values."""

    @pytest.fixture
    def defaults(self) -> dict[str, str | int]:
        return {
            CONF_HOST: "192.0.2.20",
            CONF_PORT: 60128,
            CONF_NAME: "Living Room AVR",
        }

    def test_construction_succeeds(self, defaults: dict[str, str | int]) -> None:
        schema = cf._connection_schema_reconfigure(defaults)
        assert isinstance(schema, vol.Schema)

    def test_host_prefilled(self, defaults: dict[str, str | int]) -> None:
        assert _schema_key_default(cf._connection_schema_reconfigure(defaults), CONF_HOST) == "192.0.2.20"

    def test_port_prefilled(self, defaults: dict[str, str | int]) -> None:
        assert _schema_key_default(cf._connection_schema_reconfigure(defaults), CONF_PORT) == 60128

    def test_name_prefilled(self, defaults: dict[str, str | int]) -> None:
        assert _schema_key_default(cf._connection_schema_reconfigure(defaults), CONF_NAME) == "Living Room AVR"


class TestAsyncStepUserOpensForm:
    """Opening Add Integration must not raise before user submits."""

    @pytest.mark.asyncio
    async def test_returns_user_form_without_validation(self) -> None:
        flow = cf.PioneerEiscpConfigFlow()
        flow.hass.async_add_executor_job = AsyncMock()

        result = await flow.async_step_user(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["data_schema"] is not None
        flow.hass.async_add_executor_job.assert_not_called()


class TestPortNormalization:
    """Home Assistant NumberSelector returns float ports (e.g. 60128.0)."""

    USER_INPUT = {
        CONF_HOST: "192.0.2.10",
        CONF_PORT: 60128.0,
        CONF_NAME: "Test AVR",
    }

    @pytest.mark.asyncio
    async def test_user_step_normalizes_float_port_for_validation(self) -> None:
        flow = cf.PioneerEiscpConfigFlow()
        captured: dict[str, Any] = {}

        async def capture_validate(host: str, port: int) -> dict[str, str]:
            captured["host"] = host
            captured["port"] = port
            return {"base": "cannot_connect"}

        flow._async_validate_receiver = capture_validate  # type: ignore[method-assign]
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        await flow.async_step_user(user_input=dict(self.USER_INPUT))

        assert captured["port"] == 60128
        assert isinstance(captured["port"], int)
        flow.async_set_unique_id.assert_awaited_once_with("192.0.2.10:60128")
        uid = flow.async_set_unique_id.await_args.args[0]
        assert uid == "192.0.2.10:60128"
        assert uid.endswith(":60128")
        assert ":60128.0" not in uid

    @pytest.mark.asyncio
    async def test_user_step_stores_int_port_in_config_entry(self) -> None:
        flow = cf.PioneerEiscpConfigFlow()
        flow._async_validate_receiver = AsyncMock(return_value={})
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        result = await flow.async_step_user(user_input=dict(self.USER_INPUT))

        assert result["type"] == "create_entry"
        assert result["data"][CONF_PORT] == 60128
        assert isinstance(result["data"][CONF_PORT], int)

    @pytest.mark.asyncio
    async def test_reconfigure_normalizes_float_port(self) -> None:
        flow = cf.PioneerEiscpConfigFlow()
        entry = MagicMock()
        entry.entry_id = "entry-1"
        entry.data = {
            CONF_HOST: "192.0.2.20",
            CONF_PORT: 60128,
            CONF_NAME: "Old Name",
        }
        entry.title = "Old Name"
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.hass.config_entries.async_entries = MagicMock(return_value=[])
        flow._async_validate_receiver = AsyncMock(return_value={})
        flow.async_set_unique_id = AsyncMock()

        result = await flow.async_step_reconfigure(
            user_input={
                CONF_HOST: "192.0.2.20",
                CONF_PORT: 60128.0,
                CONF_NAME: "New Name",
            }
        )

        assert result["type"] == "update_reload_and_abort"
        assert result["data_updates"][CONF_PORT] == 60128
        assert isinstance(result["data_updates"][CONF_PORT], int)
        flow.async_set_unique_id.assert_awaited_once_with("192.0.2.20:60128")
