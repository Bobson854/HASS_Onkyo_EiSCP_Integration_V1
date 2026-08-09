"""Tests for absolute volume model."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "custom_components" / "pioneer_eiscp" / "protocol"


def _load_volume():
    name = "pioneer_eiscp.protocol.volume"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROTOCOL / "volume.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vol = _load_volume()


class TestAbsoluteVolumeModel:
    """MVL decimal absolute volume with NRI volmax reference."""

    def test_mvl52_with_volmax_82(self) -> None:
        state = vol.build_volume_state("52", volume_reference=82)
        assert state.raw_parameter == "52"
        assert state.absolute_volume == 52
        assert state.volume_reference == 82
        assert state.volume_db == -30.0
        assert state.normalized_level() == pytest.approx(52 / 82)

    def test_mvl52_is_not_hex_82(self) -> None:
        assert vol.parse_mvl_parameter("52") == 52
        assert vol.parse_mvl_parameter("52") != 0x52

    def test_format_mvl_parameter_decimal(self) -> None:
        assert vol.format_mvl_parameter(52) == "52"

    def test_normalized_level_without_reference_uses_fallback(self) -> None:
        state = vol.build_volume_state("52")
        assert state.normalized_level(fallback_reference=100) == 0.52
