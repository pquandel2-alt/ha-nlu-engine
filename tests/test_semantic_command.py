"""Phase 10 (v2 plan): every MatchResult now also carries a SemanticCommand -
the fully-resolved counterpart to its SemanticFrame (real EntitySnapshot/
AreaSnapshot objects instead of text references). Purely additive: plan/
response_text keep driving behaviour unchanged (see test_engine_*.py), these
tests only pin down the new command field."""

from __future__ import annotations

from ha_nlu.areas import AreaSnapshot
from ha_nlu.nlu.command import SemanticCommand


def test_single_match_command_has_resolved_entity(engine, entities):
    result = engine.match("Mach Treppenlicht an", entities)
    assert result is not None
    assert isinstance(result.command, SemanticCommand)
    assert result.command.intent == "HassTurnOn"
    assert [e.entity_id for e in result.command.entities] == ["light.treppen_licht_gruppe"]
    assert result.command.area is None
    assert result.command.parameters == {}
    assert result.command.source_frame is result.frame


def test_percentage_match_command_has_percent_parameter(engine, entities):
    result = engine.match("mach das Treppenlicht auf 50 Prozent", entities)
    assert result is not None
    assert result.command.parameters == {"percent": 50}
    assert [e.entity_id for e in result.command.entities] == ["light.treppen_licht_gruppe"]


def test_quantifier_match_command_has_resolved_entities_and_area(engine, quantifier_entities):
    from conftest import POLERAUM_COVERS

    result = engine.match("Fahre beide Rollladen im Poleraum hoch", quantifier_entities)
    assert result is not None
    assert result.command.area == AreaSnapshot(area_id="poleraum", name="Poleraum")
    assert sorted(e.entity_id for e in result.command.entities) == sorted(e.entity_id for e in POLERAUM_COVERS)


def test_quantifier_match_without_area_has_no_area_snapshot(engine, quantifier_entities):
    result = engine.match("fahre alle Rolladen hoch", quantifier_entities)
    assert result is not None
    assert result.command.area is None


def test_no_match_returns_none_not_a_command(engine, entities):
    assert engine.match("Das ergibt keinen Sinn", entities) is None
