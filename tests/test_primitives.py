"""V6.1 (Semantic Primitives): pins the enum/dataclass vocabulary in
nlu/primitives.py. This module is purely additive/unwired (see its own
docstring) - these tests only check the vocabulary shape itself, not any
pipeline behaviour."""

from __future__ import annotations

import pytest

from ha_nlu.nlu.primitives import (
    NumericUnit,
    NumericValue,
    SemanticAction,
    SemanticDegree,
    SemanticDirection,
    SemanticProperty,
    SemanticQuantity,
    SemanticQuantityKind,
)


def test_semantic_action_has_expected_members():
    assert {member.name for member in SemanticAction} == {
        "TURN_ON",
        "TURN_OFF",
        "TOGGLE",
        "OPEN",
        "CLOSE",
        "SET",
        "ADJUST",
        "QUERY",
    }


def test_semantic_property_has_expected_members():
    assert {member.name for member in SemanticProperty} == {
        "BRIGHTNESS",
        "COLOR",
        "COLOR_TEMPERATURE",
        "TEMPERATURE",
        "POSITION",
        "POWER",
        "ENERGY",
        "HUMIDITY",
        "FAN_SPEED",
        "BATTERY",
    }


def test_semantic_direction_has_expected_members():
    assert {member.name for member in SemanticDirection} == {"INCREASE", "DECREASE"}


def test_semantic_degree_has_expected_members():
    assert {member.name for member in SemanticDegree} == {"SLIGHT", "MODERATE", "LARGE"}


def test_semantic_action_members_are_distinct_values():
    """Enum members must not accidentally alias each other (auto() collision)."""
    values = [member.value for member in SemanticAction]
    assert len(values) == len(set(values))


def test_semantic_quantity_all():
    quantity = SemanticQuantity.all()
    assert quantity.kind is SemanticQuantityKind.ALL
    assert quantity.count is None
    assert quantity.excluded == ()


def test_semantic_quantity_exactly():
    quantity = SemanticQuantity.exactly(2)
    assert quantity.kind is SemanticQuantityKind.EXACTLY
    assert quantity.count == 2


def test_semantic_quantity_some():
    quantity = SemanticQuantity.some()
    assert quantity.kind is SemanticQuantityKind.SOME
    assert quantity.count is None


def test_semantic_quantity_exclude():
    quantity = SemanticQuantity.exclude("Küchenlampe", "Flurlampe")
    assert quantity.kind is SemanticQuantityKind.EXCLUDE
    assert quantity.excluded == ("Küchenlampe", "Flurlampe")


def test_semantic_quantity_is_frozen():
    quantity = SemanticQuantity.all()
    with pytest.raises(AttributeError):
        quantity.count = 5  # type: ignore[misc]


def test_semantic_quantity_equality_by_value():
    assert SemanticQuantity.exactly(3) == SemanticQuantity.exactly(3)
    assert SemanticQuantity.exactly(3) != SemanticQuantity.exactly(2)
    assert SemanticQuantity.all() != SemanticQuantity.some()


def test_numeric_unit_has_expected_members():
    assert {member.name for member in NumericUnit} == {"PERCENT", "CELSIUS", "LEVEL"}


def test_numeric_value_percent():
    value = NumericValue(50, NumericUnit.PERCENT)
    assert value.value == 50
    assert value.unit is NumericUnit.PERCENT


def test_numeric_value_celsius():
    value = NumericValue(21, NumericUnit.CELSIUS)
    assert value.unit is NumericUnit.CELSIUS


def test_numeric_value_level():
    value = NumericValue(3, NumericUnit.LEVEL)
    assert value.unit is NumericUnit.LEVEL


def test_numeric_value_is_frozen():
    value = NumericValue(50, NumericUnit.PERCENT)
    with pytest.raises(AttributeError):
        value.value = 10  # type: ignore[misc]


def test_numeric_value_equality_by_value():
    assert NumericValue(50, NumericUnit.PERCENT) == NumericValue(50, NumericUnit.PERCENT)
    assert NumericValue(50, NumericUnit.PERCENT) != NumericValue(50, NumericUnit.CELSIUS)
    assert NumericValue(50, NumericUnit.PERCENT) != NumericValue(21, NumericUnit.PERCENT)


def test_semantic_frame_bridges_legacy_numeric_parameter():
    from ha_nlu.nlu.frame import SemanticFrame

    frame = SemanticFrame(
        intent="HassSetPercentage",
        target=None,
        area=None,
        parameters={"percent": 50},
    )

    assert frame.numeric_value == NumericValue(50, NumericUnit.PERCENT)
