"""NluEngine.respond() (v2 plan Phase 19, "Antwortsystem"): same matching as
match(), but a miss carries a specific NluError instead of collapsing to
None. Not wired into conversation.py yet (see engine.py's respond()
docstring) - these tests exercise the engine method directly."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.response import NluError

HEATER = EntitySnapshot(
    "climate.heizung_buero", "Heizung Büro", "climate", "heat",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}),
    attributes={"temperature": 20},
)
PLAIN_CLIMATE = EntitySnapshot(
    "climate.einfach", "Einfache Heizung", "climate", "heat",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
CLIMATE_ENTITIES = [HEATER, PLAIN_CLIMATE]


def test_respond_success_action_carries_speech_and_command(engine, entities):
    result = engine.respond("Mach Treppenlicht an", entities)
    assert result.success is True
    assert result.error is None
    assert result.speech is not None
    assert result.command is not None
    assert result.command.intent == "HassTurnOn"


def test_respond_success_query_carries_speech_and_command(engine, sensor_entities):
    result = engine.respond("wie hoch ist die Außentemperatur?", sensor_entities)
    assert result.success is True
    assert result.error is None
    assert result.speech == "18.4 Grad."
    assert result.command is not None


def test_respond_no_template_match_is_no_match_error(engine, entities):
    result = engine.respond("blubb schnarch wuppdi", entities)
    assert result.success is False
    assert result.speech is None
    assert result.command is None
    assert result.error is NluError.NO_MATCH


def test_respond_unknown_entity_is_no_match_error(engine, entities):
    # The parser itself rejects an unresolvable {name} before a
    # SemanticCommand exists - never reaches the validator, so this is
    # NO_MATCH, not ENTITY_NOT_FOUND (see nlu/response.py's docstring).
    result = engine.respond("Mach Kellerdingsbums an", entities)
    assert result.success is False
    assert result.error is NluError.NO_MATCH


def test_respond_unsupported_capability_maps_validator_error(engine):
    result = engine.respond("stelle die Einfache Heizung auf 21 Grad", CLIMATE_ENTITIES)
    assert result.success is False
    assert result.speech is None
    assert result.command is None
    assert result.error is NluError.UNSUPPORTED_CAPABILITY
