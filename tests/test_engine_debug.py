"""NluEngine.debug() (v2 plan Phase 22, "Debug-Modus"): a structured trace
of every pipeline stage for one utterance, alongside match()/respond(). Not
wired into conversation.py (see engine.py's debug() docstring) - these tests
exercise the engine method directly, same pattern as test_engine_response.py.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

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


def test_debug_success_action_populates_every_field(engine, entities):
    trace = engine.debug("Mach Treppenlicht an", entities)
    assert trace.input == "Mach Treppenlicht an"
    assert trace.normalized == "Mach Treppenlicht an"
    assert trace.parser == "SingleTargetParser"
    assert trace.intent == "HassTurnOn"
    assert trace.target == "Treppenlicht"
    assert trace.area is None
    assert trace.candidates == ("light.treppen_licht_gruppe",)
    assert trace.resolution == "light.treppen_licht_gruppe"
    assert trace.command is not None
    assert trace.command.startswith("HassTurnOn")
    assert trace.validation == "OK"
    assert trace.service == "homeassistant.turn_on"
    assert trace.data is not None


def test_debug_success_query_has_no_service_call(engine, sensor_entities):
    trace = engine.debug("wie hoch ist die Außentemperatur?", sensor_entities)
    assert trace.intent == "HassGetState"
    assert trace.validation == "OK"
    assert trace.service is None
    assert trace.data is None


def test_debug_no_template_match_is_mostly_empty(engine, entities):
    trace = engine.debug("blubb schnarch wuppdi", entities)
    assert trace.input == "blubb schnarch wuppdi"
    assert trace.normalized == "blubb schnarch wuppdi"
    assert trace.intent is None
    assert trace.target is None
    assert trace.area is None
    assert trace.candidates == ()
    assert trace.resolution is None
    assert trace.capabilities == ()
    assert trace.command is None
    assert trace.validation == "NO_MATCH"
    assert trace.service is None
    assert trace.data is None


def test_debug_validation_rejection_has_no_service_call(engine):
    trace = engine.debug("stelle die Einfache Heizung auf 21 Grad", CLIMATE_ENTITIES)
    assert trace.intent is not None
    assert trace.validation == "UNSUPPORTED_CAPABILITY"
    assert trace.service is None
    assert trace.data is None


def test_debug_format_renders_all_lines(engine, entities):
    trace = engine.debug("Mach Treppenlicht an", entities)
    formatted = trace.format()
    assert "INPUT: 'Mach Treppenlicht an'" in formatted
    assert "INTENT: HassTurnOn" in formatted
    assert "VALIDATION: OK" in formatted
    assert "SERVICE: homeassistant.turn_on" in formatted
