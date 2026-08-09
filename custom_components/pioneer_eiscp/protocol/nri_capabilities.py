"""Structured receiver capabilities parsed from NRI XML."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .nri_parser import parse_nri_response


def extract_text(value: Any) -> str | None:
    """Extract scalar text from parser nodes or plain strings."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        if "@text" in value:
            return extract_text(value["@text"])
        return None
    return str(value).strip() or None


def extract_attributes(node: Any) -> dict[str, str]:
    """Return @attributes from a parsed NRI node as string values."""
    if not isinstance(node, dict):
        return {}
    attrs = node.get("@attributes")
    if not isinstance(attrs, dict):
        return {}
    return {str(key): str(val) for key, val in attrs.items()}


def normalize_list(value: Any) -> list[dict[str, Any]]:
    """Normalize singleton-or-list collection nodes into a list of dicts."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def get_device_container(response: dict[str, Any]) -> dict[str, Any] | None:
    """Return the device container that holds NRI capability collections."""
    device = response.get("device")
    if isinstance(device, dict):
        return device
    devices = normalize_list(device)
    return devices[0] if devices else None


def _attr_true(value: str | None) -> bool:
    return value == "1"


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value, 10)
    except ValueError:
        return None


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
    position: str | None = None
    zone: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    step: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "enabled": self.enabled,
            "code": self.code,
            "position": self.position,
            "zone": self.zone,
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
    network_services: list[dict[str, Any]] = field(default_factory=list)
    tuners: list[dict[str, Any]] = field(default_factory=list)
    zone2_supported: bool = False
    raw: str = ""
    parse_error: str | None = None

    def main_zone(self) -> ZoneCapability | None:
        for zone in self.zones:
            zone_name = (zone.name or "").lower().replace(" ", "")
            zone_id = zone.zone_id.lower()
            if zone_name == "main" or zone_id in {"1", "main", "zone1", "mainzone"}:
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


def _identity_field_map() -> tuple[tuple[str, str], ...]:
    return (
        ("brand", "brand"),
        ("model", "model"),
        ("modelname", "model"),
        ("deviceserial", "serial"),
        ("macaddress", "mac_address"),
        ("firmwareversion", "firmware_version"),
        ("year", "year"),
        ("category", "category"),
    )


def _parse_identity(device: dict[str, Any]) -> ReceiverIdentity:
    identity = ReceiverIdentity()
    device_attrs = extract_attributes(device)

    for xml_key, attr_name in _identity_field_map():
        if xml_key in device:
            value = extract_text(device[xml_key])
            if value:
                setattr(identity, attr_name, value)

    if device_attrs:
        identity.serial = identity.serial or device_attrs.get("deviceserial") or device_attrs.get("serial")
        identity.mac_address = identity.mac_address or device_attrs.get("macaddress")
        identity.model = identity.model or device_attrs.get("model") or device_attrs.get("modelname")
        identity.brand = identity.brand or device_attrs.get("brand")
        identity.firmware_version = identity.firmware_version or device_attrs.get("firmwareversion")
        identity.year = identity.year or device_attrs.get("year")
        identity.category = identity.category or device_attrs.get("category")

    return identity


def _parse_zones(device: dict[str, Any]) -> list[ZoneCapability]:
    zones: list[ZoneCapability] = []
    zone_root = device.get("zonelist")
    if not isinstance(zone_root, dict):
        return zones

    for node in normalize_list(zone_root.get("zone")):
        attrs = extract_attributes(node)
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


def _parse_selectors(device: dict[str, Any]) -> list[InputSelector]:
    selectors: list[InputSelector] = []
    selector_root = device.get("selectorlist")
    if not isinstance(selector_root, dict):
        return selectors

    for node in normalize_list(selector_root.get("selector")):
        attrs = extract_attributes(node)
        code = (attrs.get("id") or attrs.get("code") or "").upper()
        if not code:
            continue
        name = attrs.get("name") or extract_text(node) or code
        extra = {
            key: value
            for key, value in attrs.items()
            if key not in {"id", "code", "name", "value", "zone", "iconid"}
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


def _parse_controls(device: dict[str, Any]) -> list[ControlCapability]:
    controls: list[ControlCapability] = []
    control_root = device.get("controllist")
    if not isinstance(control_root, dict):
        return controls

    for node in normalize_list(control_root.get("control")):
        attrs = extract_attributes(node)
        control_id = attrs.get("id") or attrs.get("name") or extract_text(node) or "unknown"
        controls.append(
            ControlCapability(
                control_id=control_id,
                enabled=_attr_true(attrs.get("value")),
                code=attrs.get("code"),
                position=attrs.get("position"),
                zone=attrs.get("zone"),
                min_value=attrs.get("min"),
                max_value=attrs.get("max"),
                step=attrs.get("step"),
            )
        )
    return controls


def _parse_functions(device: dict[str, Any]) -> dict[str, bool]:
    functions: dict[str, bool] = {}
    function_root = device.get("functionlist")
    if not isinstance(function_root, dict):
        return functions

    for node in normalize_list(function_root.get("function")):
        attrs = extract_attributes(node)
        name = attrs.get("id") or attrs.get("name") or extract_text(node)
        if name:
            functions[name] = _attr_true(attrs.get("value"))
    return functions


def _parse_network_services(device: dict[str, Any]) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    service_root = device.get("netservicelist")
    if not isinstance(service_root, dict):
        return services

    for node in normalize_list(service_root.get("netservice")):
        attrs = extract_attributes(node)
        services.append(
            {
                "id": attrs.get("id") or attrs.get("name"),
                "name": attrs.get("name") or extract_text(node),
                "enabled": _attr_true(attrs.get("value")),
                "attributes": attrs,
            }
        )
    return services


def _parse_tuners(device: dict[str, Any]) -> list[dict[str, Any]]:
    tuners: list[dict[str, Any]] = []
    tuner_root = device.get("tuners")
    if not isinstance(tuner_root, dict):
        return tuners

    for node in normalize_list(tuner_root.get("tuner")):
        attrs = extract_attributes(node)
        tuners.append(
            {
                "id": attrs.get("id") or attrs.get("name"),
                "name": attrs.get("name") or extract_text(node),
                "enabled": _attr_true(attrs.get("value")),
                "band": attrs.get("band"),
                "attributes": attrs,
            }
        )
    return tuners


def _detect_zone2(zones: list[ZoneCapability]) -> bool:
    for zone in zones:
        if not zone.enabled:
            continue
        zone_name = (zone.name or "").lower().replace(" ", "")
        zone_id = zone.zone_id.lower()
        if zone_id in {"2", "zone2"} or zone_name == "zone2":
            return True
    return False


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

    device = get_device_container(response)
    if device is None:
        capabilities.parse_error = capabilities.parse_error or "Missing device container"
        return capabilities

    capabilities.identity = _parse_identity(device)
    capabilities.zones = _parse_zones(device)
    capabilities.selectors = _parse_selectors(device)
    capabilities.controls = _parse_controls(device)
    capabilities.functions = _parse_functions(device)
    capabilities.network_services = _parse_network_services(device)
    capabilities.tuners = _parse_tuners(device)
    capabilities.zone2_supported = _detect_zone2(capabilities.zones)

    return capabilities
