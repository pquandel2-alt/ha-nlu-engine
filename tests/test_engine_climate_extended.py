"""Phase 17 (v2 plan): Climate-NLU - HassClimateSetTemperature/
HassClimateIncreaseTemperature/HassClimateDecreaseTemperature, the engine's
6th separately-compiled hassil grammar (see engine.py's _CLIMATE_EXTENDED_RE
routing). "wärmer"/"kälter" compute a new absolute target from the resolved
climate entity's own current ``temperature`` attribute plus a fixed default
step of 1 - no invented user-specified amount, no native HA increase/decrease
service to defer to (unlike fan speed in Phase 16)."""

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

ENTITIES = [HEATER, PLAIN_CLIMATE]


def test_set_temperature_absolute_target(engine):
    result = engine.match("stelle die Heizung Büro auf 21 Grad", ENTITIES)
    assert result is not None
    assert result.plan.domain == "climate"
    assert result.plan.service == "set_temperature"
    assert result.plan.data == {"temperature": 21}
    assert "21" in result.response_text


def test_set_temperature_degree_symbol(engine):
    # HomeIntent plan V4.2 ("Number Normalization"): "21°" must normalize
    # to the same value as "21 Grad" - see nlu/normalize.py's
    # _DEGREE_SYMBOL_RE.
    result = engine.match("stelle die Heizung Büro auf 21°", ENTITIES)
    assert result is not None
    assert result.plan.data == {"temperature": 21}


def test_set_temperature_spelled_out_number(engine):
    # hassil parses spelled-out German numbers natively - no normalize()
    # step needed, verified here end-to-end for the plan's own example.
    result = engine.match("stelle die Heizung Büro auf einundzwanzig Grad", ENTITIES)
    assert result is not None
    assert result.plan.data == {"temperature": 21}


def test_increase_temperature_computes_target_from_current_attribute(engine):
    result = engine.match("mach die Heizung Büro wärmer", ENTITIES)
    assert result is not None
    assert result.plan.domain == "climate"
    assert result.plan.service == "set_temperature"
    assert result.plan.data == {"temperature": 21}
    assert result.plan.entity_id == "climate.heizung_buero"


def test_decrease_temperature_computes_target_from_current_attribute(engine):
    result = engine.match("mach die Heizung Büro kälter", ENTITIES)
    assert result is not None
    assert result.plan.data == {"temperature": 19}


def test_degree_words_control_relative_temperature_step(engine):
    slight = engine.match("mach die Heizung Büro etwas wärmer", ENTITIES)
    large = engine.match("mach die Heizung Büro viel kälter", ENTITIES)
    assert slight.plan.data == {"temperature": 20.5}
    assert large.plan.data == {"temperature": 18.0}
    assert slight.frame.degree.name == "SLIGHT"
    assert large.frame.degree.name == "LARGE"


def test_increase_temperature_via_erhoehe_die_temperatur(engine):
    result = engine.match("erhöhe die Temperatur von der Heizung Büro", ENTITIES)
    assert result is not None
    assert result.plan.data == {"temperature": 21}


def test_set_temperature_rejected_without_temperature_capability(engine):
    assert engine.match("stelle die Einfache Heizung auf 21 Grad", ENTITIES) is None


def test_increase_temperature_rejected_without_temperature_capability(engine):
    assert engine.match("mach die Einfache Heizung wärmer", ENTITIES) is None


def test_decrease_temperature_rejected_without_temperature_capability(engine):
    assert engine.match("mach die Einfache Heizung kälter", ENTITIES) is None


def test_climate_turn_on_via_generic_intent(engine):
    result = engine.match("mach die Heizung Büro an", ENTITIES)
    assert result is not None
    assert result.plan.domain == "homeassistant"
    assert result.plan.service == "turn_on"
    assert result.plan.entity_id == "climate.heizung_buero"


def test_climate_turn_off_via_generic_intent(engine):
    result = engine.match("mach die Heizung Büro aus", ENTITIES)
    assert result is not None
    assert result.plan.service == "turn_off"
