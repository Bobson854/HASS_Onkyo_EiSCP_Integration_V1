"""Regression tests for media player availability on disconnect."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"


def _install_homeassistant_stubs() -> None:
    """Minimal Home Assistant stubs for media_player import."""
    if "homeassistant.components.media_player" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = MagicMock
    sys.modules["homeassistant.config_entries"] = config_entries

    const = types.ModuleType("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_PORT = "port"
    sys.modules["homeassistant.const"] = const

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = MagicMock
    sys.modules["homeassistant.core"] = core

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = MagicMock
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = dict
    sys.modules["homeassistant.helpers.device_registry"] = device_registry

    coordinator_mod = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class CoordinatorEntity:
        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

        def __class_getitem__(cls, item):
            return cls

    coordinator_mod.DataUpdateCoordinator = DataUpdateCoordinator
    coordinator_mod.CoordinatorEntity = CoordinatorEntity
    sys.modules["homeassistant.helpers.update_coordinator"] = coordinator_mod

    mp = types.ModuleType("homeassistant.components.media_player")

    class MediaPlayerDeviceClass:
        RECEIVER = "receiver"

    class MediaPlayerEntityFeature:
        VOLUME_SET = 4
        VOLUME_MUTE = 8
        VOLUME_STEP = 1024
        TURN_ON = 128
        TURN_OFF = 256
        SELECT_SOURCE = 512

    class MediaPlayerState:
        ON = "on"
        OFF = "off"
        UNKNOWN = "unknown"

    class MediaPlayerEntity:
        pass

    mp.MediaPlayerDeviceClass = MediaPlayerDeviceClass
    mp.MediaPlayerEntityFeature = MediaPlayerEntityFeature
    mp.MediaPlayerState = MediaPlayerState
    mp.MediaPlayerEntity = MediaPlayerEntity
    sys.modules["homeassistant.components.media_player"] = mp

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    for name, rel in [
        ("pioneer_eiscp.const", "const.py"),
        ("pioneer_eiscp.receiver", "receiver.py"),
    ]:
        path = BASE / rel
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    coordinator_stub = types.ModuleType("pioneer_eiscp.coordinator")

    class PioneerEiscpCoordinator:
        """Stub coordinator type for entity imports."""

    coordinator_stub.PioneerEiscpCoordinator = PioneerEiscpCoordinator
    sys.modules["pioneer_eiscp.coordinator"] = coordinator_stub

    entity_path = BASE / "entity.py"
    entity_spec = importlib.util.spec_from_file_location("pioneer_eiscp.entity", entity_path)
    assert entity_spec and entity_spec.loader
    entity_module = importlib.util.module_from_spec(entity_spec)
    sys.modules["pioneer_eiscp.entity"] = entity_module
    entity_spec.loader.exec_module(entity_module)


def _load_media_player():
    _install_homeassistant_stubs()
    name = "pioneer_eiscp.media_player"
    sys.modules.pop(name, None)
    path = BASE / "media_player.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mp_mod = _load_media_player()
MediaPlayerState = sys.modules["homeassistant.components.media_player"].MediaPlayerState
ReceiverState = sys.modules["pioneer_eiscp.receiver"].ReceiverState


def _make_media_player(*, connected: bool = True, power: bool | None = True):
    coordinator = MagicMock()
    coordinator.device_name = "VSX-1131"
    coordinator.data = ReceiverState()
    coordinator.data.main.power = power
    coordinator.receiver = MagicMock(connected=connected)

    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.data = {"host": "192.168.1.10", "port": 60128, "model": "VSX-1131"}

    entity = mp_mod.PioneerMainZoneMediaPlayer(coordinator, entry)
    return entity, coordinator


class TestMediaPlayerAvailability:
    """Media player must use entity availability, not MediaPlayerState.UNAVAILABLE."""

    def test_connected_receiver_is_available(self) -> None:
        entity, _ = _make_media_player(connected=True)
        assert entity.available is True

    def test_disconnected_receiver_is_unavailable(self) -> None:
        entity, _ = _make_media_player(connected=False)
        assert entity.available is False

    def test_state_never_returns_unavailable_enum(self) -> None:
        entity, _ = _make_media_player(connected=False, power=True)
        assert not hasattr(MediaPlayerState, "UNAVAILABLE")
        assert entity.state == MediaPlayerState.ON

    def test_state_on_when_power_true(self) -> None:
        entity, _ = _make_media_player(power=True)
        assert entity.state == MediaPlayerState.ON

    def test_state_off_when_power_false(self) -> None:
        entity, _ = _make_media_player(power=False)
        assert entity.state == MediaPlayerState.OFF

    def test_state_unknown_when_power_unknown(self) -> None:
        entity, _ = _make_media_player(power=None)
        assert entity.state == MediaPlayerState.UNKNOWN

    def test_disconnect_update_does_not_raise(self) -> None:
        entity, coordinator = _make_media_player(connected=True)
        assert entity.available is True

        coordinator.receiver.connected = False
        coordinator.data.connected = False

        assert entity.available is False
        assert entity.state in (
            MediaPlayerState.ON,
            MediaPlayerState.OFF,
            MediaPlayerState.UNKNOWN,
        )

    def test_no_unavailable_in_media_player_source(self) -> None:
        source = (BASE / "media_player.py").read_text(encoding="utf-8")
        assert "MediaPlayerState.UNAVAILABLE" not in source


class TestConnectionSensorStaysAvailable:
    """Connection sensor reports disconnected without becoming unavailable."""

    def test_connection_sensor_has_no_connected_entity_base(self) -> None:
        sensor_source = (BASE / "sensor.py").read_text(encoding="utf-8")
        assert "PioneerConnectedEntity" not in sensor_source
