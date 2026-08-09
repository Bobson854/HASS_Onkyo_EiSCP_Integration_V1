"""Test configuration — import protocol modules without loading Home Assistant."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "custom_components" / "pioneer_eiscp" / "protocol"
sys.path.insert(0, str(PROTOCOL))
sys.path.insert(0, str(ROOT))
