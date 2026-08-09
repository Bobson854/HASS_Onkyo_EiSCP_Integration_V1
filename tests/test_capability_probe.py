"""Tests for capability probe sequencing and correlation."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "pioneer_eiscp"
PROTOCOL = BASE / "protocol"


def _load_modules():
    for mod in list(sys.modules):
        if mod.startswith("pioneer_eiscp"):
            del sys.modules[mod]

    pkg = types.ModuleType("pioneer_eiscp")
    pkg.__path__ = [str(BASE)]
    sys.modules["pioneer_eiscp"] = pkg

    proto_pkg = types.ModuleType("pioneer_eiscp.protocol")
    proto_pkg.__path__ = [str(PROTOCOL)]
    sys.modules["pioneer_eiscp.protocol"] = proto_pkg

    files = [
        ("pioneer_eiscp.const", BASE / "const.py"),
        ("pioneer_eiscp.capability_commands", BASE / "capability_commands.py"),
        ("pioneer_eiscp.protocol.framing", PROTOCOL / "framing.py"),
        ("pioneer_eiscp.protocol.parsers", PROTOCOL / "parsers.py"),
        ("pioneer_eiscp.protocol.nri_parser", PROTOCOL / "nri_parser.py"),
        ("pioneer_eiscp.protocol.capability_probe", PROTOCOL / "capability_probe.py"),
    ]
    loaded = {}
    for name, path in files:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        loaded[name.split(".")[-1]] = module
    return loaded


mods = _load_modules()
cp = mods["capability_probe"]
cmds = mods["capability_commands"]
framing = mods["framing"]
EiscpFrame = framing.EiscpFrame


class CorrelationWaiter:
    """Minimal probe waiter mimicking receiver correlation behaviour."""

    def __init__(self) -> None:
        self._waiters: dict[str, asyncio.Future[EiscpFrame]] = {}
        self.unrelated_frames: list[EiscpFrame] = []

    def on_frame(self, frame: EiscpFrame) -> None:
        waiter = self._waiters.get(frame.command)
        if waiter and not waiter.done():
            waiter.set_result(frame)
        else:
            self.unrelated_frames.append(frame)

    async def wait(self, command: str, timeout: float) -> EiscpFrame | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[EiscpFrame] = loop.create_future()
        self._waiters[command] = future
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            if self._waiters.get(command) is future:
                del self._waiters[command]


@pytest.mark.asyncio
async def test_probe_sequences_queries_in_order() -> None:
    sent: list[str] = []

    async def send(query: str) -> None:
        sent.append(query)

    async def wait(_command: str, _timeout: float) -> EiscpFrame | None:
        return EiscpFrame(command=_command, parameter="00", raw_iscp=f"{_command}00")

    snapshot = await cp.run_capability_probe(
        send,
        wait,
        queries=("PWRQSTN", "MVLQSTN"),
        delay=0,
        timeout=1,
    )

    assert sent == ["PWRQSTN", "MVLQSTN"]
    assert "PWR" in snapshot.responses
    assert "MVL" in snapshot.responses


@pytest.mark.asyncio
async def test_timeout_does_not_abort_whole_probe() -> None:
    sent: list[str] = []

    async def send(query: str) -> None:
        sent.append(query)

    async def wait(command: str, _timeout: float) -> EiscpFrame | None:
        if command == "PWR":
            return EiscpFrame(command="PWR", parameter="01", raw_iscp="PWR01")
        return None

    snapshot = await cp.run_capability_probe(
        send,
        wait,
        queries=("PWRQSTN", "MVLQSTN"),
        delay=0,
        timeout=0.1,
    )

    assert sent == ["PWRQSTN", "MVLQSTN"]
    assert snapshot.responses["PWR"]["raw"] == "PWR01"
    assert snapshot.responses["MVL"]["timed_out"] is True
    assert "MVLQSTN" in snapshot.timeouts


@pytest.mark.asyncio
async def test_unsolicited_message_not_consumed_by_probe() -> None:
    waiter = CorrelationWaiter()
    sent: list[str] = []

    async def send(query: str) -> None:
        sent.append(query)
        if query == "MVLQSTN":
            waiter.on_frame(EiscpFrame(command="IFA", parameter="x", raw_iscp="IFAx"))

    async def wait(command: str, timeout: float) -> EiscpFrame | None:
        if command == "MVL" and sent.count("MVLQSTN") == 1:
            asyncio.get_running_loop().call_later(
                0.05,
                lambda: waiter.on_frame(
                    EiscpFrame(command="MVL", parameter="14", raw_iscp="MVL14")
                ),
            )
        return await waiter.wait(command, timeout)

    snapshot = await cp.run_capability_probe(
        send,
        wait,
        queries=("MVLQSTN",),
        delay=0,
        timeout=1,
    )

    assert snapshot.responses["MVL"]["raw"] == "MVL14"
    assert len(waiter.unrelated_frames) == 1
    assert waiter.unrelated_frames[0].command == "IFA"


def test_safe_to_probe_excludes_state_changing_commands() -> None:
    safe = set(cmds.SAFE_TO_PROBE)
    blocked = set(cmds.STATE_CHANGING_DO_NOT_PROBE)
    assert safe.isdisjoint(blocked)
    for query in cmds.SAFE_TO_PROBE:
        assert query.endswith("QSTN")


def test_validate_probe_queries_rejects_state_changing() -> None:
    with pytest.raises(ValueError):
        cp._validate_probe_queries(("PWR01",))


def test_snapshot_json_serializable() -> None:
    snapshot = cp.CapabilitySnapshot(
        last_probe="2026-01-01T00:00:00+00:00",
        responses={"PWR": {"raw": "PWR01", "parsed": {"power": True}}},
    )
    json.loads(snapshot.to_json())


def test_nri_probe_response_preserves_raw() -> None:
    xml = "<response><model>VSX-1131</model></response>"
    frame = EiscpFrame(command="NRI", parameter=xml, raw_iscp=f"NRI{xml}")
    parsed, error = cp.parse_probe_response("NRI", frame)
    assert error is None
    assert parsed is not None
    assert parsed["raw"] == xml
    assert parsed["parsed"] is not None
