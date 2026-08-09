"""Phase 1 (v2 plan): every MatchResult now also carries a SemanticFrame -
a resolved-but-not-yet-service-call representation of the same match. This
is purely additive: plan/response_text keep driving behaviour unchanged
(see test_engine_*.py), these tests only pin down the new frame field."""

from __future__ import annotations

from ha_nlu.nlu.frame import AreaReference, SemanticFrame, TargetReference


def test_single_match_frame_has_resolved_target(engine, entities):
    result = engine.match("Mach Treppenlicht an", entities)
    assert result is not None
    assert isinstance(result.frame, SemanticFrame)
    assert result.frame.intent == "HassTurnOn"
    assert result.frame.target == TargetReference(
        text="Treppenlicht", entity_id="light.treppen_licht_gruppe", domain="light"
    )
    assert result.frame.area is None
    assert result.frame.source_text == "Mach Treppenlicht an"


def test_query_match_frame_has_resolved_target(engine, sensor_entities):
    result = engine.match("wie hoch ist die Außentemperatur?", sensor_entities)
    assert result is not None
    assert result.frame.intent == "HassGetState"
    assert result.frame.target.entity_id == "sensor.aussentemperatur"


def test_percentage_match_frame_has_percent_parameter(engine, entities):
    result = engine.match("mach das Treppenlicht auf 50 Prozent", entities)
    assert result is not None
    assert result.frame.intent == "HassSetPercentage"
    assert result.frame.target.entity_id == "light.treppen_licht_gruppe"
    assert result.frame.parameters == {"percent": 50}


def test_quantifier_match_frame_has_domain_target_and_area(engine, quantifier_entities):
    result = engine.match("Fahre beide Rollladen im Poleraum hoch", quantifier_entities)
    assert result is not None
    assert result.frame.intent == "HassOpenCover"
    assert result.frame.target == TargetReference(text="cover", domain="cover")
    assert result.frame.area == AreaReference(text="Poleraum", area_id="poleraum")
    assert result.frame.parameters == {"quantifier": "both"}


def test_quantifier_match_without_area_has_no_area_reference(engine, quantifier_entities):
    result = engine.match("fahre alle Rolladen hoch", quantifier_entities)
    assert result is not None
    assert result.frame.area is None
    assert result.frame.parameters == {"quantifier": "all"}


def test_no_match_returns_none_not_a_frame(engine, entities):
    assert engine.match("Das ergibt keinen Sinn", entities) is None
