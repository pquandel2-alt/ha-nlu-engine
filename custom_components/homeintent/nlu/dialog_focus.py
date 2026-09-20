"""Derive the semantic focus carried from one conversation turn to the next."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..entities import EntitySnapshot
from .command import SemanticCommand
from .primitives import SemanticProperty

ScopeKind = Literal["entity", "area", "floor"]


@dataclass(frozen=True)
class DialogFocus:
    """The smallest explicit representation of what a follow-up refers to."""

    property: SemanticProperty | None
    scope_kind: ScopeKind | None
    scope_id: str | None
    candidate_entity_ids: tuple[str, ...]
    source_intent: str


_PROPERTY_NAMES = {
    "temperatur": SemanticProperty.TEMPERATURE,
    "temperature": SemanticProperty.TEMPERATURE,
    "helligkeit": SemanticProperty.BRIGHTNESS,
    "brightness": SemanticProperty.BRIGHTNESS,
    "position": SemanticProperty.POSITION,
    "leistung": SemanticProperty.POWER,
    "power": SemanticProperty.POWER,
    "energie": SemanticProperty.ENERGY,
    "energy": SemanticProperty.ENERGY,
    "luftfeuchtigkeit": SemanticProperty.HUMIDITY,
    "humidity": SemanticProperty.HUMIDITY,
    "batterie": SemanticProperty.BATTERY,
    "battery": SemanticProperty.BATTERY,
    "geschwindigkeit": SemanticProperty.FAN_SPEED,
    "stufe": SemanticProperty.FAN_SPEED,
}

_INTENT_PROPERTIES = {
    "HassClimateSetTemperature": SemanticProperty.TEMPERATURE,
    "HassClimateIncreaseTemperature": SemanticProperty.TEMPERATURE,
    "HassClimateDecreaseTemperature": SemanticProperty.TEMPERATURE,
    "HassLightBrighten": SemanticProperty.BRIGHTNESS,
    "HassLightDim": SemanticProperty.BRIGHTNESS,
    "HassSetPercentage": None,  # inferred from the resolved domain below
    "HassFanSetSpeed": SemanticProperty.FAN_SPEED,
    "HassFanIncreaseSpeed": SemanticProperty.FAN_SPEED,
    "HassFanDecreaseSpeed": SemanticProperty.FAN_SPEED,
}


def _property_from_command(command: SemanticCommand) -> SemanticProperty | None:
    explicit = command.source_frame.property
    if explicit is not None:
        return explicit
    raw = command.parameters.get("property")
    if isinstance(raw, str):
        mapped = _PROPERTY_NAMES.get(raw.casefold())
        if mapped is not None:
            return mapped
    mapped = _INTENT_PROPERTIES.get(command.intent)
    if mapped is not None:
        return mapped
    if command.intent == "HassSetPercentage" and command.entities:
        if command.entities[0].domain == "light":
            return SemanticProperty.BRIGHTNESS
        if command.entities[0].domain == "cover":
            return SemanticProperty.POSITION
    return None


def derive_dialog_focus(command: SemanticCommand) -> DialogFocus:
    """Create a stable focus from a successfully resolved command/query."""

    entities: tuple[EntitySnapshot, ...] = command.entities
    parameters = command.parameters
    location_kind = parameters.get("location_kind")
    location_id = parameters.get("location_id")
    if location_kind in ("area", "floor") and isinstance(location_id, str):
        scope_kind: ScopeKind | None = location_kind
        scope_id = location_id
    elif command.area is not None:
        scope_kind = "area"
        scope_id = command.area.area_id
    elif len(entities) == 1:
        scope_kind = "entity"
        scope_id = entities[0].entity_id
    else:
        area_ids = {entity.area_id for entity in entities if entity.area_id}
        floor_ids = {entity.floor_id for entity in entities if entity.floor_id}
        if len(area_ids) == 1:
            scope_kind, scope_id = "area", next(iter(area_ids))
        elif len(floor_ids) == 1:
            scope_kind, scope_id = "floor", next(iter(floor_ids))
        else:
            scope_kind, scope_id = None, None

    return DialogFocus(
        property=_property_from_command(command),
        scope_kind=scope_kind,
        scope_id=scope_id,
        candidate_entity_ids=tuple(entity.entity_id for entity in entities),
        source_intent=command.intent,
    )
