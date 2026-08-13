"""Unit tests for nlu.reasoning (V6 architecture plan, V6.25/V6.26,
"Reasoning Engine"/"Resolved Semantic Intent") - hass-free, no engine/hassil
involved. Not wired into engine.py/conversation.py yet (see
nlu/reasoning.py's module docstring), so these tests exercise
ReasoningEngine.resolve() directly against hand-built SemanticFrame/
ConversationContext/EntitySnapshot instances, same style as
test_conversation_context.py/test_primitives.py.
"""

from __future__ import annotations

import pytest

from ha_nlu.areas import AreaSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext
from ha_nlu.nlu.frame import AreaReference, SemanticFrame, TargetReference
from ha_nlu.nlu.primitives import (
    SemanticAction,
    SemanticDegree,
    SemanticDirection,
    SemanticProperty,
)
from ha_nlu.nlu.reasoning import ReasoningEngine, ResolvedSemanticIntent
from ha_nlu.nlu.semantic_state import SemanticState
from ha_nlu.floors import FloorSnapshot

LIGHT_WOHNZIMMER = EntitySnapshot(
    "light.wohnzimmer", "Wohnzimmerlicht", "light", "on",
    area_id="wohnzimmer", capabilities=frozenset({"BRIGHTNESS"}),
)
LIGHT_KUECHE = EntitySnapshot(
    "light.kueche", "Küchenlicht", "light", "on",
    area_id="kueche", capabilities=frozenset({"BRIGHTNESS"}),
)
SWITCH_WOHNZIMMER = EntitySnapshot(
    "switch.wohnzimmer_stecker", "Wohnzimmer Steckdose", "switch", "on",
    area_id="wohnzimmer",
)

ALL_ENTITIES = [LIGHT_WOHNZIMMER, LIGHT_KUECHE, SWITCH_WOHNZIMMER]


def test_domain_and_area_constraint_resolves_matching_entities():
    frame = SemanticFrame(
        intent="HassTurnOn",
        target=TargetReference(text="Licht", domain="light"),
        area=AreaReference(text="Wohnzimmer", area_id="wohnzimmer"),
        action=SemanticAction.TURN_ON,
    )
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES)

    assert isinstance(result, ResolvedSemanticIntent)
    assert result.entities == (LIGHT_WOHNZIMMER,)
    assert result.action is SemanticAction.TURN_ON
    assert result.area == frame.area


def test_property_constraint_filters_by_capability():
    frame = SemanticFrame(
        intent="HassLightSetColor",
        target=TargetReference(text="Licht", domain="light"),
        area=None,
        property=SemanticProperty.COLOR,
    )
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES)

    # Neither light in ALL_ENTITIES carries the COLOR capability.
    assert result.entities == ()
    assert result.property is SemanticProperty.COLOR

    frame_brightness = SemanticFrame(
        intent="HassLightBrighten",
        target=TargetReference(text="Licht", domain="light"),
        area=None,
        property=SemanticProperty.BRIGHTNESS,
    )
    result_brightness = ReasoningEngine.resolve(frame_brightness, ALL_ENTITIES)
    assert {e.entity_id for e in result_brightness.entities} == {
        "light.wohnzimmer", "light.kueche",
    }


def test_no_context_case_leaves_area_none_when_frame_has_none():
    frame = SemanticFrame(
        intent="HassTurnOn",
        target=TargetReference(text="Licht", domain="light"),
        area=None,
    )
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES, context=None)

    assert result.area is None
    assert {e.entity_id for e in result.entities} == {"light.wohnzimmer", "light.kueche"}


def test_context_fills_in_area_when_frame_has_none():
    frame = SemanticFrame(
        intent="HassTurnOn",
        target=TargetReference(text="Licht", domain="light"),
        area=None,
    )
    context = ConversationContext(
        last_command=None,
        last_entities=(),
        last_area=AreaSnapshot(area_id="wohnzimmer", name="Wohnzimmer"),
        pending_clarification=None,
    )
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES, context=context)

    assert result.area == AreaReference(text="Wohnzimmer", area_id="wohnzimmer")
    assert result.entities == (LIGHT_WOHNZIMMER,)


def test_context_floor_narrows_candidates():
    context = ConversationContext(
        last_command=None,
        last_entities=(),
        last_area=None,
        pending_clarification=None,
        last_floor=FloorSnapshot(floor_id="og", name="Obergeschoss"),
    )
    entities = [
        EntitySnapshot("light.og_a", "OG Lampe", "light", "off", floor_id="og"),
        EntitySnapshot("light.eg_a", "EG Lampe", "light", "off", floor_id="eg"),
    ]
    frame = SemanticFrame(
        intent="HassTurnOn",
        target=TargetReference(text="Licht", domain="light"),
        area=None,
    )
    result = ReasoningEngine.resolve(frame, entities, context=context)

    assert result.entities == (entities[0],)


def test_frame_area_takes_precedence_over_context_area():
    frame = SemanticFrame(
        intent="HassTurnOn",
        target=TargetReference(text="Licht", domain="light"),
        area=AreaReference(text="Küche", area_id="kueche"),
    )
    context = ConversationContext(
        last_command=None,
        last_entities=(),
        last_area=AreaSnapshot(area_id="wohnzimmer", name="Wohnzimmer"),
        pending_clarification=None,
    )
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES, context=context)

    assert result.area == frame.area
    assert result.entities == (LIGHT_KUECHE,)


def test_empty_candidate_pool_returns_empty_entities():
    frame = SemanticFrame(
        intent="HassTurnOn",
        target=TargetReference(text="Licht", domain="light"),
        area=None,
    )
    result = ReasoningEngine.resolve(frame, [])
    assert result.entities == ()


def test_action_direction_degree_pass_through_unchanged():
    frame = SemanticFrame(
        intent="HassLightDim",
        target=TargetReference(text="Licht", domain="light"),
        area=AreaReference(text="Küche", area_id="kueche"),
        action=SemanticAction.ADJUST,
        direction=SemanticDirection.DECREASE,
        degree=SemanticDegree.SLIGHT,
    )
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES)

    assert result.action is SemanticAction.ADJUST
    assert result.direction is SemanticDirection.DECREASE
    assert result.degree is SemanticDegree.SLIGHT


def test_no_target_no_area_matches_every_entity():
    frame = SemanticFrame(intent="HassGetState", target=None, area=None)
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES)
    assert list(result.entities) == ALL_ENTITIES


def test_resolved_semantic_intent_is_frozen():
    frame = SemanticFrame(intent="HassGetState", target=None, area=None)
    result = ReasoningEngine.resolve(frame, [])
    with pytest.raises(AttributeError):
        result.action = SemanticAction.QUERY  # type: ignore[misc]


# SemanticState import kept only to document that ConversationContext.last_state
# exists and is untouched by ReasoningEngine today - no live consumer/parser
# populates or reads it yet (see context.py's own docstring), so there is
# nothing to compose from it here.
def test_last_state_on_context_is_ignored_without_error():
    context = ConversationContext(
        last_command=None,
        last_entities=(),
        last_area=None,
        pending_clarification=None,
        last_state=SemanticState.ON,
    )
    frame = SemanticFrame(intent="HassGetState", target=None, area=None)
    result = ReasoningEngine.resolve(frame, ALL_ENTITIES, context=context)
    assert list(result.entities) == ALL_ENTITIES
