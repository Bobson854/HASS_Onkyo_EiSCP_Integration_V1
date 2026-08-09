"""Tests for setup-time eISCP validation."""

from __future__ import annotations

import importlib.util
import socket
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"


def _load_config_validation():
    """Load config_validation without importing Home Assistant dependencies."""
    if "pioneer_eiscp.config_validation" in sys.modules:
        return sys.modules["pioneer_eiscp.config_validation"]

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    proto_pkg = types.ModuleType("pioneer_eiscp.protocol")
    proto_pkg.__path__ = [str(BASE / "protocol")]
    sys.modules["pioneer_eiscp.protocol"] = proto_pkg

    modules = [
        ("pioneer_eiscp.const", BASE / "const.py"),
        ("pioneer_eiscp.protocol.framing", BASE / "protocol" / "framing.py"),
        ("pioneer_eiscp.config_validation", BASE / "config_validation.py"),
    ]
    for name, path in modules:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    return sys.modules["pioneer_eiscp.config_validation"]


cv = _load_config_validation()
build_packet = sys.modules["pioneer_eiscp.protocol.framing"].build_packet


class TestPwrResponseValidation:
    """PWR response frame checks."""

    def test_valid_pwr_on(self) -> None:
        frame = cv.validate_pwr_response_buffer(build_packet("PWR01"))
        assert frame is not None
        assert frame.raw_iscp == "PWR01"
        assert cv.is_valid_pwr_response(frame) is True

    def test_valid_pwr_off(self) -> None:
        frame = cv.validate_pwr_response_buffer(build_packet("PWR00"))
        assert frame is not None
        assert cv.is_valid_pwr_response(frame) is True

    def test_rejects_non_pwr_command(self) -> None:
        frame = cv.validate_pwr_response_buffer(build_packet("MVL14"))
        assert frame is None

    def test_rejects_invalid_pwr_parameter(self) -> None:
        frame = cv.validate_pwr_response_buffer(build_packet("PWR99"))
        assert frame is None

    def test_rejects_non_eiscp_data(self) -> None:
        frame = cv.validate_pwr_response_buffer(b"HTTP/1.1 200 OK\r\n\r\n")
        assert frame is None


class TestValidateEiscpReceiver:
    """Socket-level validation with mocks."""

    def test_successful_validation(self) -> None:
        response = build_packet("PWR01")
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [response, b""]

        with patch.object(cv.socket, "create_connection", return_value=mock_sock):
            result = cv.validate_eiscp_receiver("192.0.2.10", 60128)

        assert result == "PWR01"
        mock_sock.sendall.assert_called_once()
        mock_sock.close.assert_called_once()

    def test_connection_failure(self) -> None:
        with patch.object(
            cv.socket,
            "create_connection",
            side_effect=OSError("Connection refused"),
        ):
            with pytest.raises(cv.EiscpConnectionError):
                cv.validate_eiscp_receiver("192.0.2.10", 60128)

    def test_malformed_response_timeout(self) -> None:
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = socket.timeout

        with patch.object(cv.socket, "create_connection", return_value=mock_sock):
            with pytest.raises(cv.EiscpInvalidResponseError):
                cv.validate_eiscp_receiver(
                    "192.0.2.10",
                    60128,
                    read_timeout=0.2,
                )

    def test_non_eiscp_response(self) -> None:
        mock_sock = MagicMock()
        responses = iter([b"NOT-ISCP-DATA"])

        def recv_side_effect(*_args, **_kwargs):
            try:
                return next(responses)
            except StopIteration:
                raise socket.timeout

        mock_sock.recv.side_effect = recv_side_effect

        with patch.object(cv.socket, "create_connection", return_value=mock_sock):
            with pytest.raises(cv.EiscpInvalidResponseError):
                cv.validate_eiscp_receiver(
                    "192.0.2.10",
                    60128,
                    read_timeout=0.2,
                )

    def test_connection_closed_early(self) -> None:
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""

        with patch.object(cv.socket, "create_connection", return_value=mock_sock):
            with pytest.raises(cv.EiscpInvalidResponseError):
                cv.validate_eiscp_receiver("192.0.2.10", 60128)
