"""Defensive NRI (Network Remote Information) response parsing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def _local_tag(tag: str) -> str:
    """Strip XML namespace from an element tag."""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _element_to_dict(element: ET.Element) -> dict[str, Any]:
    """Convert an XML element to a JSON-serializable dict."""
    node: dict[str, Any] = {}
    if element.attrib:
        node["@attributes"] = dict(element.attrib)

    text = (element.text or "").strip()
    if text:
        node["@text"] = text

    for child in element:
        child_tag = _local_tag(child.tag)
        child_value = _element_to_dict(child)
        if child_tag in node:
            existing = node[child_tag]
            if isinstance(existing, list):
                existing.append(child_value)
            else:
                node[child_tag] = [existing, child_value]
        else:
            node[child_tag] = child_value

    return node


def parse_nri_response(raw: str) -> dict[str, Any]:
    """Parse NRI payload defensively."""
    result: dict[str, Any] = {
        "raw": raw,
        "parsed": None,
        "parse_error": None,
    }

    if not raw or not raw.strip():
        result["parse_error"] = "Empty NRI payload"
        return result

    payload = raw.strip()
    xml_start = payload.find("<")
    if xml_start > 0:
        payload = payload[xml_start:]

    if not payload.startswith("<"):
        result["parse_error"] = "NRI payload is not XML"
        return result

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as err:
        result["parse_error"] = f"XML parse error: {err}"
        return result

    try:
        parsed: dict[str, Any] = {_local_tag(root.tag): _element_to_dict(root)}
        result["parsed"] = parsed
    except Exception as err:  # noqa: BLE001
        result["parse_error"] = f"NRI structure conversion error: {err}"

    return result
