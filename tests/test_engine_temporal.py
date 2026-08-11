"""HomeIntent plan V4.7, "Temporal Expressions": "in fünf Minuten" (delay),
"für eine Stunde" (duration), "morgen früh"/"heute Abend" (relative_time),
"um 20 Uhr" (absolute_time).

Per the plan's own scoping ("Zunächst nur parsen und validieren -
tatsächliche HA-Ausführung erst in einer späteren Execution-Schicht"), the
resulting ``ServiceCallPlan`` is byte-identical to a plain on/off command -
only ``frame.parameters["temporal"]`` differs. These tests assert both
halves: the plan is unaffected, and the ``TemporalExpression`` is captured
correctly.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.frame import TemporalExpression

LAMP = EntitySnapshot(
    "light.wohnzimmerlampe", "Wohnzimmerlampe", "light", "on",
    area_id="wohnzimmer", area_name="Wohnzimmer",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)

ENTITIES = [LAMP]


def test_delay_minutes(engine):
    result = engine.match("mach die Wohnzimmerlampe in fünf Minuten aus", ENTITIES)
    assert result is not None
    assert result.plan.domain == "homeassistant"
    assert result.plan.service == "turn_off"
    assert result.plan.entity_id == "light.wohnzimmerlampe"
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="delay", minutes=5)


def test_duration_hours_converted_to_minutes(engine):
    result = engine.match("mach die Wohnzimmerlampe für eine Stunde an", ENTITIES)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="duration", minutes=60)


def test_duration_minutes_not_converted(engine):
    result = engine.match("mach die Wohnzimmerlampe für zehn Minuten an", ENTITIES)
    assert result is not None
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="duration", minutes=10)


def test_relative_time_morgen_frueh(engine):
    result = engine.match("mach die Wohnzimmerlampe morgen früh an", ENTITIES)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="relative_time", relative="tomorrow_morning")


def test_relative_time_heute_abend(engine):
    result = engine.match("mach die Wohnzimmerlampe heute abend aus", ENTITIES)
    assert result is not None
    assert result.plan.service == "turn_off"
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="relative_time", relative="today_evening")


def test_relative_time_morgen_abend(engine):
    result = engine.match("mach die Wohnzimmerlampe morgen abend an", ENTITIES)
    assert result is not None
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="relative_time", relative="tomorrow_evening")


def test_relative_time_heute_frueh(engine):
    result = engine.match("mach die Wohnzimmerlampe heute früh an", ENTITIES)
    assert result is not None
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="relative_time", relative="today_morning")


def test_absolute_time_hour(engine):
    result = engine.match("mach die Wohnzimmerlampe um 20 Uhr an", ENTITIES)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert result.frame.parameters["temporal"] == TemporalExpression(kind="absolute_time", hour=20)


def test_plain_sentence_without_temporal_modifier_still_works(engine):
    # Regression: adding the 10th grammar must not break the pre-existing
    # plain on/off phrasing, and must not spuriously attach a temporal.
    result = engine.match("mach die Wohnzimmerlampe an", ENTITIES)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert "temporal" not in result.frame.parameters


def test_unresolvable_entity_returns_none_no_guessing(engine):
    # "never guess": an unknown entity name must not silently fall back to
    # some other match.
    assert engine.match("mach die Nichtvorhandene in fünf Minuten aus", ENTITIES) is None
