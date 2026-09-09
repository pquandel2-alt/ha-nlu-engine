"""HomeIntent plan V4.7, "Temporal Expressions": "in fünf Minuten" (delay),
"für eine Stunde" (duration), "morgen früh"/"heute Abend" (relative_time),
"um 20 Uhr" (absolute_time).

The semantic interpreter retains the typed temporal expression, while the
generic direct boundary refuses an immediate ServiceCallPlan. Supported
scheduling routes may project it into an AutomationModel first.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.frame import TemporalExpression
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_interpreter import SemanticInterpreter
from ha_nlu.nlu.understanding import UnderstandingKind

LAMP = EntitySnapshot(
    "light.wohnzimmerlampe", "Wohnzimmerlampe", "light", "on",
    area_id="wohnzimmer", area_name="Wohnzimmer",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)

ENTITIES = [LAMP]


def _parsed_temporal(text: str):
    interpreted = SemanticInterpreter.interpret(analyse_language(text), ENTITIES)
    assert interpreted.parse_result is not None
    return interpreted.parse_result.frame.parameters["temporal"]


def _assert_parsed_but_not_immediate(engine, text: str) -> None:
    outcome = engine.understand(text, ENTITIES)
    assert outcome.kind is UnderstandingKind.UNSUPPORTED
    assert not outcome.actionable


def test_delay_minutes(engine):
    text = "mach die Wohnzimmerlampe in fünf Minuten aus"
    assert _parsed_temporal(text) == TemporalExpression(kind="delay", minutes=5)
    _assert_parsed_but_not_immediate(engine, text)


def test_duration_hours_converted_to_minutes(engine):
    text = "mach die Wohnzimmerlampe für eine Stunde an"
    assert _parsed_temporal(text) == TemporalExpression(kind="duration", minutes=60)
    _assert_parsed_but_not_immediate(engine, text)


def test_duration_minutes_not_converted(engine):
    text = "mach die Wohnzimmerlampe für zehn Minuten an"
    assert _parsed_temporal(text) == TemporalExpression(kind="duration", minutes=10)
    _assert_parsed_but_not_immediate(engine, text)


def test_relative_time_morgen_frueh(engine):
    text = "mach die Wohnzimmerlampe morgen früh an"
    assert _parsed_temporal(text) == TemporalExpression(kind="relative_time", relative="tomorrow_morning")
    _assert_parsed_but_not_immediate(engine, text)


def test_relative_time_heute_abend(engine):
    text = "mach die Wohnzimmerlampe heute abend aus"
    assert _parsed_temporal(text) == TemporalExpression(kind="relative_time", relative="today_evening")
    _assert_parsed_but_not_immediate(engine, text)


def test_relative_time_morgen_abend(engine):
    text = "mach die Wohnzimmerlampe morgen abend an"
    assert _parsed_temporal(text) == TemporalExpression(kind="relative_time", relative="tomorrow_evening")
    _assert_parsed_but_not_immediate(engine, text)


def test_relative_time_heute_frueh(engine):
    text = "mach die Wohnzimmerlampe heute früh an"
    assert _parsed_temporal(text) == TemporalExpression(kind="relative_time", relative="today_morning")
    _assert_parsed_but_not_immediate(engine, text)


def test_absolute_time_hour(engine):
    text = "mach die Wohnzimmerlampe um 20 Uhr an"
    assert _parsed_temporal(text) == TemporalExpression(kind="absolute_time", hour=20)
    _assert_parsed_but_not_immediate(engine, text)


def test_plain_sentence_without_temporal_modifier_still_works(engine):
    # Regression: adding the 10th grammar must not break the pre-existing
    # plain on/off phrasing, and must not spuriously attach a temporal.
    result = engine.match("mach die Wohnzimmerlampe an", ENTITIES)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert "temporal" not in result.frame.parameters


def test_cover_direction_is_not_misclassified_as_temporal(engine):
    cover = EntitySnapshot(
        "cover.buero",
        "Rollladen Büro",
        "cover",
        "open",
        capabilities=frozenset({"POSITION"}),
    )

    outcome = engine.understand("Fahre Rollladen Büro nach unten", [cover])

    assert outcome.actionable
    assert outcome.payload is not None


def test_unresolvable_entity_returns_none_no_guessing(engine):
    # "never guess": an unknown entity name must not silently fall back to
    # some other match.
    assert engine.match("mach die Nichtvorhandene in fünf Minuten aus", ENTITIES) is None
