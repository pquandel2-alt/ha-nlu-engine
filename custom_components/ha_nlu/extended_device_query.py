"""Read-only state and capability queries for extended device domains."""

from __future__ import annotations

import re

from .entities import EntitySnapshot
from .entity_scope import DOMAIN_WORDS, resolve_entity_scope
from .device_control import DeviceControlResult


_DOMAINS = frozenset(DOMAIN_WORDS)
_QUERY_CUE = re.compile(
    r"\b(?:welch\w*|wie\s+hoch|wie\s+viel|ist|sind|laeuft|laufen|steht|status|zustand)\b",
    re.I,
)


def _state_text(entity: EntitySnapshot) -> str:
    if entity.domain == "humidifier":
        humidity = entity.attributes.get("humidity")
        return f"{entity.friendly_name}: {humidity} Prozent" if humidity is not None else f"{entity.friendly_name}: {entity.state}"
    if entity.domain in {"number", "input_number"}:
        unit = entity.unit or entity.attributes.get("unit_of_measurement") or ""
        return f"{entity.friendly_name}: {entity.state} {unit}".strip()
    if entity.domain == "water_heater":
        value = entity.attributes.get("temperature")
        return f"{entity.friendly_name}: {value} Grad" if value is not None else f"{entity.friendly_name}: {entity.state}"
    return f"{entity.friendly_name}: {entity.state}"


def match_extended_device_query(
    text: str, entities: list[EntitySnapshot]
) -> DeviceControlResult | None:
    if _QUERY_CUE.search(text) is None:
        return None
    scope = resolve_entity_scope(text, entities, _DOMAINS)
    if scope is None or not scope.entities:
        return None
    rendered = "; ".join(_state_text(entity) for entity in scope.entities[:8])
    suffix = "" if len(scope.entities) <= 8 else f"; und {len(scope.entities) - 8} weitere"
    return DeviceControlResult(None, rendered + suffix + ".", entity=(scope.entities[0] if len(scope.entities) == 1 else None))
