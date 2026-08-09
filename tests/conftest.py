"""Test configuration — import protocol modules without loading Home Assistant."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "custom_components" / "pioneer_eiscp" / "protocol"
INTEGRATION = ROOT / "custom_components" / "pioneer_eiscp"
sys.path.insert(0, str(PROTOCOL))
sys.path.insert(0, str(ROOT))


def _ensure_protocol_package() -> None:
    """Register protocol modules for relative imports in tests."""
    if "pioneer_eiscp.protocol.parsers" in sys.modules:
        return

    pioneer_pkg = types.ModuleType("pioneer_eiscp")
    pioneer_pkg.__path__ = [str(INTEGRATION)]
    sys.modules["pioneer_eiscp"] = pioneer_pkg

    protocol_pkg = types.ModuleType("pioneer_eiscp.protocol")
    protocol_pkg.__path__ = [str(PROTOCOL)]
    sys.modules["pioneer_eiscp.protocol"] = protocol_pkg

    for module_name in ("volume", "parsers"):
        full_name = f"pioneer_eiscp.protocol.{module_name}"
        path = PROTOCOL / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(full_name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
        sys.modules[module_name] = module


_ensure_protocol_package()
