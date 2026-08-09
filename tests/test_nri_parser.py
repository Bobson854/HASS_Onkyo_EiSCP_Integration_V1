"""Tests for NRI response parsing."""

import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "custom_components" / "pioneer_eiscp" / "protocol"


def _load_nri_parser():
    name = "pioneer_eiscp.protocol.nri_parser"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROTOCOL / "nri_parser.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


nri = _load_nri_parser()


class TestParseNriResponse:
    """NRI XML parsing."""

    def test_parses_basic_xml(self) -> None:
        raw = '<?xml version="1.0"?><response><device><modelname>VSX-1131</modelname></device></response>'
        result = nri.parse_nri_response(raw)
        assert result["raw"] == raw
        assert result["parse_error"] is None
        assert result["parsed"] is not None
        assert "response" in result["parsed"]

    def test_preserves_raw_on_malformed_xml(self) -> None:
        raw = "<not>valid<xml"
        result = nri.parse_nri_response(raw)
        assert result["raw"] == raw
        assert result["parsed"] is None
        assert result["parse_error"] is not None

    def test_empty_payload(self) -> None:
        result = nri.parse_nri_response("")
        assert result["parse_error"] is not None

    def test_json_serializable(self) -> None:
        raw = "<response><selectorlist><selector id='01'>HDMI1</selector></selectorlist></response>"
        result = nri.parse_nri_response(raw)
        json.dumps(result)
