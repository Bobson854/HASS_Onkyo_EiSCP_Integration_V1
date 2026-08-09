"""Structured receiver capabilities parsed from NRI XML."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .nri_parser import parse_nri_response


def _node_attrs(node: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(node, dict):
        return {}
    attrs = node.get("@attributes", {})
    return {str(k): str(v) for k, v in attrs.items()} if isinstance(attrs, dict) else {}


def _as_nodes(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _attr_true(value: str | None) -> bool:
    return value == "1"


@dataclass(slots=True)
class ReceiverIdentity:
    """Stable receiver identity from NRI."""

    serial: str | None = None
    mac_address: str | None = None
    model: str | None = None
    brand: str | None = None
    firmware_version: str | None = None
    year: str | None = None
    category: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "mac_address": self.mac_address,
            "model": self.model,
            "brand": self.brand,
            "firmware_version": self.firmware_version,
            "year": self.year,
            "category": self.category,
        }


@dataclass(slots=True)
class ZoneCapability:
    """Zone capability block from NRI."""

    zone_id: str
    enabled: bool = False
    name: str | None = None
    volume_max: int | None = None
    volume_step: str | None = None
    src: str | None = None
    dst: str | None = None
    lrselect: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "enabled": self.enabled,
            "name": self.name,
            "volume_max": self.volume_max,
            "volume_step": self.volume_step,
            "src": self.src,
            "dst": self.dst,
            "lrselect": self.lrselect,
        }


@dataclass(slots=True)
class InputSelector:
    """Input selector entry from NRI selectorlist."""

    code: str
    name: str
    enabled: bool = False
    zone_mask: str | None = None
    icon_id: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "enabled": self.enabled,
            "zone_mask": self.zone_mask,
            "icon_id": self.icon_id,
            "attributes": self.attributes,
        }


@dataclass(slots=True)
class ControlCapability:
    """Control/tone/listening-mode capability from NRI controllist."""

    control_id: str
    enabled: bool = False
    code: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    step: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "enabled": self.enabled,
            "code": self.code,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "step": self.step,
        }


@dataclass
class ReceiverCapabilities:
    """Structured NRI-derived receiver capabilities."""

    identity: ReceiverIdentity = field(default_factory=ReceiverIdentity)
    zones: list[ZoneCapability] = field(default_factory=list)
    selectors: list[InputSelector] = field(default_factory=list)
    controls: list[ControlCapability] = field(default_factory=list)
    functions: dict[str, bool] = field(default_factory=dict)
    network_services: dict[str, Any] = field(default_factory=dict)
    tuners: dict[str, Any] = field(default_factory=dict)
    zone2_supported: bool = False
    raw: str = ""
    parse_error: str | None = None

    def main_zone(self) -> ZoneCapability | None:
        for zone in self.zones:
            zone_id = zone.zone_id.lower()
            if zone_id in {"main", "zone1", "mainzone"}:
                return zone
        return self.zones[0] if self.zones else None

    @property
    def volume_reference(self) -> int | None:
        main = self.main_zone()
        return main.volume_max if main else None

    def enabled_selectors(self) -> list[InputSelector]:
        return [selector for selector in self.selectors if selector.enabled]

    def input_source_map(self) -> dict[str, str]:
        return {selector.code.upper(): selector.name for selector in self.enabled_selectors()}

    def input_source_reverse_map(self) -> dict[str, str]:
        return {selector.name: selector.code.upper() for selector in self.enabled_selectors()}

    def listening_mode_controls(self) -> list[ControlCapability]:
        return [
            control
            for control in self.controls
            if control.enabled and control.control_id.upper().startswith("LMD")
        ]

    def listening_mode_map(self) -> dict[str, str]:
        """Map display name -> LMD command suffix/code."""
        result: dict[str, str] = {}
        for control in self.listening_mode_controls():
            if control.code:
                result[control.control_id] = control.code
        return result

    def resolve_listening_mode_name(self, code: str | None) -> str | None:
        if not code:
            return None
        normalized = code.strip().upper()
        for control in self.listening_mode_controls():
            if control.code and control.code.strip().upper() == normalized:
                return control.control_id
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.as_dict(),
            "zones": [zone.as_dict() for zone in self.zones],
            "selectors": [selector.as_dict() for selector in self.selectors],
            "controls": [control.as_dict() for control in self.controls],
            "functions": self.functions,
            "network_services": self.network_services,
            "tuners": self.tuners,
            "zone2_supported": self.zone2_supported,
            "raw": self.raw,
            "parse_error": self.parse_error,
        }


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value, 10)
    except ValueError:
        return None


def _parse_identity(response: dict[str, Any]) -> ReceiverIdentity:
    device_nodes = _as_nodes(response.get("device"))
    identity = ReceiverIdentity()
    if not device_nodes:
        return identity

    device = device_nodes[0]
    attrs = _node_attrs(device)
    identity.serial = attrs.get("deviceserial") or attrs.get("serial")
    identity.mac_address = attrs.get("macaddress")
    identity.model = attrs.get("model") or attrs.get("modelname")
    identity.brand = attrs.get("brand")
    identity.firmware_version = attrs.get("firmwareversion")
    identity.year = attrs.get("year")
    identity.category = attrs.get("category")

    for key, attr in (
        ("modelname", "model"),
        ("deviceserial", "serial"),
        ("macaddress", "mac_address"),
        ("firmwareversion", "firmware_version"),
    ):
        if key in device and isinstance(device[key], dict):
            text = device[key].get("@text")
            if text and getattr(identity, attr if attr != "mac_address" else "mac_address") is None:
                setattr(identity, attr, text)

    return identity


def _parse_zones(response: dict[str, Any]) -> list[ZoneCapability]:
    zones: list[ZoneCapability] = []
    for zonelist_key in ("zonelist", "zone_list", "zones"):
        zone_root = response.get(zonelist_key)
        if zone_root is None:
            continue
        if isinstance(zone_root, dict):
            zone_nodes = _as_nodes(zone_root.get("zone"))
        else:
            zone_nodes = []
        for node in zone_nodes:
            attrs = _node_attrs(node)
            zone_id = attrs.get("id") or attrs.get("name") or "unknown"
            zones.append(
                ZoneCapability(
                    zone_id=zone_id,
                    enabled=_attr_true(attrs.get("value")),
                    name=attrs.get("name"),
                    volume_max=_parse_int(attrs.get("volmax")),
                    volume_step=attrs.get("volstep"),
                    src=attrs.get("src"),
                    dst=attrs.get("dst"),
                    lrselect=attrs.get("lrselect"),
                )
            )
    return zones


def _parse_selectors(response: dict[str, Any]) -> list[InputSelector]:
    selectors: list[InputSelector] = []
    selector_root = response.get("selectorlist")
    if not isinstance(selector_root, dict):
        return selectors

    for node in _as_nodes(selector_root.get("selector")):
        attrs = _node_attrs(node)
        code = (attrs.get("id") or attrs.get("code") or "").upper()
        if not code:
            continue
        name = attrs.get("name") or node.get("@text") or code
        extra = {
            k: v
            for k, v in attrs.items()
            if k not in {"id", "code", "name", "value", "zone", "iconid"}
        }
        selectors.append(
            InputSelector(
                code=code,
                name=name,
                enabled=_attr_true(attrs.get("value")),
                zone_mask=attrs.get("zone"),
                icon_id=attrs.get("iconid"),
                attributes=extra,
            )
        )
    return selectors


def _parse_controls(response: dict[str, Any]) -> list[ControlCapability]:
    controls: list[ControlCapability] = []
    control_root = response.get("controllist")
    if not isinstance(control_root, dict):
        return controls

    for node in _as_nodes(control_root.get("control")):
        attrs = _node_attrs(node)
        control_id = attrs.get("id") or attrs.get("name") or "unknown"
        controls.append(
            ControlCapability(
                control_id=control_id,
                enabled=_attr_true(attrs.get("value")),
                code=attrs.get("code"),
                min_value=attrs.get("min"),
                max_value=attrs.get("max"),
                step=attrs.get("step"),
            )
        )
    return controls


def _parse_functions(response: dict[str, Any]) -> dict[str, bool]:
    functions: dict[str, bool] = {}
    for root_key in ("functionlist", "functions"):
        function_root = response.get(root_key)
        if not isinstance(function_root, dict):
            continue
        for node in _as_nodes(function_root.get("function")):
            attrs = _node_attrs(node)
            name = attrs.get("id") or attrs.get("name")
            if name:
                functions[name] = _attr_true(attrs.get("value"))
    return functions


def build_receiver_capabilities(raw: str) -> ReceiverCapabilities:
    """Parse raw NRI XML into structured receiver capabilities."""
    parsed = parse_nri_response(raw)
    capabilities = ReceiverCapabilities(raw=raw, parse_error=parsed.get("parse_error"))

    if not parsed.get("parsed"):
        return capabilities

    response = parsed["parsed"].get("response")
    if not isinstance(response, dict):
        capabilities.parse_error = capabilities.parse_error or "Missing response root"
        return capabilities

    capabilities.identity = _parse_identity(response)
    capabilities.zones = _parse_zones(response)
    capabilities.selectors = _parse_selectors(response)
    capabilities.controls = _parse_controls(response)
    capabilities.functions = _parse_functions(response)

    if isinstance(response.get("networkservices"), dict):
        capabilities.network_services = response["networkservices"]
    if isinstance(response.get("tunerlist"), dict):
        capabilities.tuners = response["tunerlist"]

    for zone in capabilities.zones:
        if zone.zone_id.lower() in {"zone2", "zone 2"} and zone.enabled:
            capabilities.zone2_supported = True

    return capabilities
