"""Phase 16 (v2 plan): Fan-NLU erweitern - HassFanSetSpeed/HassFanIncreaseSpeed/
HassFanDecreaseSpeed, the engine's 5th separately-compiled hassil grammar
(see engine.py's _FAN_EXTENDED_RE routing). "Stufe N" is converted to a
percentage via the resolved fan's own percentage_step attribute; "schneller"/
"langsamer" call HA's native fan.increase_speed/decrease_speed directly, with
no invented step size."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

# percentage_step=20.0 -> a 5-speed fan (100 / 20 = 5 steps), so "Stufe 3"
# should compute to 60%.
STEPPED_FAN = EntitySnapshot(
    "fan.gestuft", "Gestufter Ventilator", "fan", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "FAN_SPEED"}),
    attributes={"percentage_step": 20.0},
)
# No percentage_step attribute at all -> build() must fall back to 1.0
# (continuous-percentage fan default) rather than crashing.
CONTINUOUS_FAN = EntitySnapshot(
    "fan.stufenlos", "Stufenloser Ventilator", "fan", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "FAN_SPEED"}),
    attributes={},
)
PLAIN_FAN = EntitySnapshot(
    "fan.einfach", "Einfacher Ventilator", "fan", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)

ENTITIES = [STEPPED_FAN, CONTINUOUS_FAN, PLAIN_FAN]


def test_set_speed_computes_percentage_from_percentage_step(engine):
    result = engine.match("stelle den Gestufter Ventilator auf Stufe 3", ENTITIES)
    assert result is not None
    assert result.plan.domain == "fan"
    assert result.plan.service == "turn_on"
    assert result.plan.data == {"percentage": 60}
    assert "Stufe 3" in result.response_text


def test_set_speed_defaults_percentage_step_to_one_when_missing(engine):
    result = engine.match("mach den Stufenloser Ventilator auf Stufe 7", ENTITIES)
    assert result is not None
    assert result.plan.data == {"percentage": 7}


def test_set_speed_clamps_percentage_to_hundred(engine):
    result = engine.match("stelle den Gestufter Ventilator auf Stufe 10", ENTITIES)
    assert result is not None
    assert result.plan.data == {"percentage": 100}


def test_increase_speed_calls_native_service_with_no_extra_data(engine):
    result = engine.match("mach den Gestufter Ventilator schneller", ENTITIES)
    assert result is not None
    assert result.plan.domain == "fan"
    assert result.plan.service == "increase_speed"
    assert result.plan.data == {}
    assert result.plan.entity_id == "fan.gestuft"


def test_decrease_speed_calls_native_service_with_no_extra_data(engine):
    result = engine.match("mach den Gestufter Ventilator langsamer", ENTITIES)
    assert result is not None
    assert result.plan.domain == "fan"
    assert result.plan.service == "decrease_speed"
    assert result.plan.data == {}


def test_set_speed_rejected_without_fan_speed_capability(engine):
    assert engine.match("stelle den Einfacher Ventilator auf Stufe 3", ENTITIES) is None


def test_increase_speed_rejected_without_fan_speed_capability(engine):
    assert engine.match("mach den Einfacher Ventilator schneller", ENTITIES) is None


def test_decrease_speed_rejected_without_fan_speed_capability(engine):
    assert engine.match("mach den Einfacher Ventilator langsamer", ENTITIES) is None
