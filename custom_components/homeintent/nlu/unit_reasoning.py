"""Closed, deterministic unit normalization for semantic comparisons."""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import SemanticProperty


@dataclass(frozen=True)
class NormalizedMeasurement:
    value: float
    unit: str


_CANONICAL_UNIT = {
    SemanticProperty.TEMPERATURE: "°C",
    SemanticProperty.POWER: "W",
    SemanticProperty.ENERGY: "Wh",
    SemanticProperty.HUMIDITY: "%",
    SemanticProperty.BATTERY: "%",
    SemanticProperty.POSITION: "%",
    SemanticProperty.FAN_SPEED: "%",
    SemanticProperty.BRIGHTNESS: "ha_brightness",
}


def normalize_measurement(
    value: float,
    unit: str | None,
    property_: SemanticProperty,
) -> NormalizedMeasurement | None:
    """Normalize only explicitly supported, dimension-compatible units.

    Dimensionless readings are comparable only when both callers retain the
    same explicit unit. Unknown spellings never receive a guessed meaning.
    """
    canonical = _CANONICAL_UNIT.get(property_)
    if canonical is None:
        return None
    if property_ is SemanticProperty.TEMPERATURE:
        if unit in {"°C", "C", "celsius"}:
            return NormalizedMeasurement(value, canonical)
        if unit in {"°F", "F", "fahrenheit"}:
            return NormalizedMeasurement((value - 32.0) * 5.0 / 9.0, canonical)
    elif property_ is SemanticProperty.POWER:
        if unit == "W":
            return NormalizedMeasurement(value, canonical)
        if unit == "kW":
            return NormalizedMeasurement(value * 1000.0, canonical)
    elif property_ is SemanticProperty.ENERGY:
        if unit == "Wh":
            return NormalizedMeasurement(value, canonical)
        if unit == "kWh":
            return NormalizedMeasurement(value * 1000.0, canonical)
    elif property_ in {
        SemanticProperty.HUMIDITY,
        SemanticProperty.BATTERY,
        SemanticProperty.POSITION,
        SemanticProperty.FAN_SPEED,
    }:
        if unit in {"%", "percent", "Prozent"}:
            return NormalizedMeasurement(value, canonical)
    elif property_ is SemanticProperty.BRIGHTNESS:
        # Home Assistant's native brightness attribute is the deterministic
        # 0..255 scale and conventionally has no unit. Percent brightness is
        # a different representation and is not silently mixed with it.
        if unit in {None, "", "ha_brightness"}:
            return NormalizedMeasurement(value, canonical)
    return None
