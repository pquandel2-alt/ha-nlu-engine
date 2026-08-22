"""HomeIntent plan V4.6, "Comparisons": "mindestens 50 Prozent", "höchstens 70
Prozent", "nicht höher als 70 Prozent", "über 50 Prozent", "unter 20 Grad".

User decision (AskUserQuestion, 2026-08-11): needed both as a SET-command
setpoint synonym (PercentageParser/ClimateExtendedParser - the comparator is
recorded but ``value`` still drives the target, same as a plain number) and
as a standalone multi-entity query filter (ComparisonQueryParser, the 9th
separately-compiled hassil grammar, "welche Lichter sind mindestens 50
Prozent") - both halves are exercised here.
"""

from __future__ import annotations

from itertools import permutations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.frame import Comparison

HEATER = EntitySnapshot(
    "climate.heizung_buero", "Heizung Büro", "climate", "heat",
    area_id="buero", area_name="Büro",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}),
    attributes={"temperature": 20, "current_temperature": 18},
)
LAMP = EntitySnapshot(
    "light.wohnzimmerlampe", "Wohnzimmerlampe", "light", "on",
    area_id="wohnzimmer", area_name="Wohnzimmer",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    attributes={"brightness": 178},  # ~70%
)

SETPOINT_ENTITIES = [HEATER, LAMP]


def test_setpoint_percent_with_comparator_still_sets_plain_target(engine):
    # "mindestens" is recorded, not enforced - the target is exactly 50, same
    # as if the comparator word had been omitted entirely.
    result = engine.match("stelle die Wohnzimmerlampe auf mindestens 50 Prozent", SETPOINT_ENTITIES)
    assert result is not None
    assert result.plan.domain == "light"
    assert result.plan.data == {"brightness_pct": 50}


def test_setpoint_percent_nicht_hoeher_als_multiword_comparator(engine):
    result = engine.match("stelle die Wohnzimmerlampe auf nicht höher als 70 Prozent", SETPOINT_ENTITIES)
    assert result is not None
    assert result.plan.data == {"brightness_pct": 70}


def test_setpoint_percent_comparison_captured_in_frame_parameters(engine):
    result = engine.match("stelle die Wohnzimmerlampe auf mindestens 50 Prozent", SETPOINT_ENTITIES)
    assert result is not None
    assert result.frame.parameters["comparison"] == Comparison(operator="gte", value=50)


def test_setpoint_temperature_with_comparator_still_sets_plain_target(engine):
    result = engine.match("stelle die Heizung Büro auf mindestens 21 Grad", SETPOINT_ENTITIES)
    assert result is not None
    assert result.plan.domain == "climate"
    assert result.plan.data == {"temperature": 21}


def test_setpoint_temperature_unter_comparator(engine):
    result = engine.match("stelle die Heizung Büro auf unter 20 Grad", SETPOINT_ENTITIES)
    assert result is not None
    assert result.plan.data == {"temperature": 20}
    assert result.frame.parameters["comparison"] == Comparison(operator="lt", value=20)


def test_setpoint_plain_sentences_without_comparator_still_work(engine):
    # Regression: adding the {comparator} sentences must not break the
    # pre-existing plain phrasing.
    result = engine.match("stelle die Wohnzimmerlampe auf 50 Prozent", SETPOINT_ENTITIES)
    assert result is not None
    assert result.plan.data == {"brightness_pct": 50}
    assert "comparison" not in result.frame.parameters

    result = engine.match("stelle die Heizung Büro auf 21 Grad", SETPOINT_ENTITIES)
    assert result is not None
    assert result.plan.data == {"temperature": 21}
    assert "comparison" not in result.frame.parameters


# --- Query filter (ComparisonQueryParser) --------------------------------

LIGHTS_AND_COVERS = [
    EntitySnapshot(
        "light.wohnzimmer", "Wohnzimmerlampe", "light", "on",
        area_id="wohnzimmer", area_name="Wohnzimmer", attributes={"brightness": 178},  # ~70%
    ),
    EntitySnapshot(
        "light.kueche", "Küchenlampe", "light", "on",
        area_id="kueche", area_name="Küche", attributes={"brightness": 51},  # ~20%
    ),
    EntitySnapshot(
        "light.flur", "Flurlicht", "light", "off",
        area_id="flur", area_name="Flur", attributes={},  # no brightness reported at all
    ),
    EntitySnapshot(
        "cover.buero", "Bürorolladen", "cover", "open",
        area_id="buero", area_name="Büro", attributes={"current_position": 80},
    ),
]

ROOMS = [
    EntitySnapshot(
        "climate.wohnzimmer", "Wohnzimmerheizung", "climate", "heat",
        area_id="wohnzimmer", area_name="Wohnzimmer",
        attributes={"temperature": 21, "current_temperature": 18},
    ),
    EntitySnapshot(
        "climate.buero", "Büroheizung", "climate", "heat",
        area_id="buero", area_name="Büro",
        attributes={"temperature": 22, "current_temperature": 23},
    ),
]


def test_query_percent_mindestens_filters_lights(engine):
    result = engine.match("welche Lichter sind mindestens 50 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.plan is None  # query, no service call
    assert result.command.entities == (LIGHTS_AND_COVERS[0],)
    assert "Wohnzimmerlampe" in result.response_text


def test_query_percent_hoechstens_filters_lights(engine):
    result = engine.match("welche Lichter sind höchstens 30 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.command.entities == (LIGHTS_AND_COVERS[1],)


def test_query_percent_covers_uber(engine):
    result = engine.match("welche Rollläden sind über 50 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.command.entities == (LIGHTS_AND_COVERS[3],)


def test_query_percent_heller_als_filters_lights(engine):
    # Spec gap #5: "heller als"/"dunkler als"/"mehr als"/"weniger als" are
    # brightness-flavored synonyms for "über"/"unter" - same "gt"/"lt"
    # operators, not a new comparison semantic.
    result = engine.match("welche Lichter sind heller als 50 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.command.entities == (LIGHTS_AND_COVERS[0],)


def test_query_percent_dunkler_als_filters_lights(engine):
    result = engine.match("welche Lichter sind dunkler als 50 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.command.entities == (LIGHTS_AND_COVERS[1],)


def test_query_percent_mehr_als_filters_lights(engine):
    result = engine.match("welche Lichter sind mehr als 50 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.command.entities == (LIGHTS_AND_COVERS[0],)


def test_query_percent_weniger_als_filters_lights(engine):
    result = engine.match("welche Lichter sind weniger als 50 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.command.entities == (LIGHTS_AND_COVERS[1],)


def test_query_percent_heller_als_does_not_misroute_to_light_extended(engine):
    # "heller als" contains the bare word "heller", which _LIGHT_EXTENDED_RE
    # also matches (LightExtendedParser's "mach das Licht heller" command) -
    # _COMPARISON_QUERY_RE must win since it's checked first in engine.py.
    result = engine.match("welche Lichter sind heller als 50 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    assert result.frame.intent == "HassQueryComparison"


def test_query_percent_entity_without_attribute_excluded_not_crashed(engine):
    # Flurlicht reports no "brightness" attribute at all - excluded from the
    # match set rather than treated as 0% or raising.
    result = engine.match("welche Lichter sind höchstens 100 Prozent", LIGHTS_AND_COVERS)
    assert result is not None
    ids = {e.entity_id for e in result.command.entities}
    assert "light.flur" not in ids


def test_query_temperature_unter_filters_climate(engine):
    result = engine.match("welche Heizungen sind unter 20 Grad", ROOMS)
    assert result is not None
    assert result.command.entities == (ROOMS[0],)


def test_query_temperature_ueber_filters_climate(engine):
    result = engine.match("welche Heizungen sind über 20 Grad", ROOMS)
    assert result is not None
    assert result.command.entities == (ROOMS[1],)


def test_query_temperature_raeume_synonym_and_area_scoping(engine):
    result = engine.match("welche Räume sind nicht höher als 19 Grad im Büro", ROOMS)
    assert result is None  # Büroheizung is 23 Grad - doesn't satisfy <=19


def test_query_temperature_area_scoped_positive_match(engine):
    result = engine.match("welche Räume sind unter 20 Grad im Wohnzimmer", ROOMS)
    assert result is not None
    assert result.command.entities == (ROOMS[0],)


def test_query_no_matches_returns_none(engine):
    # Never guess: nothing satisfies this, so no result at all rather than
    # an empty/misleading response.
    assert engine.match("welche Lichter sind mindestens 95 Prozent", LIGHTS_AND_COVERS) is None


def test_query_unknown_area_returns_none(engine):
    assert engine.match("welche Heizungen sind unter 20 Grad im Bunker", ROOMS) is None


def test_query_domain_value_mismatch_returns_none(engine):
    # HomeIntent plan's "never guess" rule: a light has no "Grad" value and
    # a climate entity has no domain word in this grammar's {domain} slot
    # combined with {percent} - both combinations are undefined, not
    # silently reinterpreted.
    assert engine.match("welche Lichter sind unter 20 Grad", LIGHTS_AND_COVERS) is None
    assert engine.match("welche Heizungen sind mindestens 50 Prozent", ROOMS) is None


def test_query_sets_all_quantifier_avoiding_ambiguous_entity_validation_error(engine):
    # Regression for nlu/validator.py check #3 (AMBIGUOUS_ENTITY when
    # frame.quantifier is None and multiple entities match) - a comparison
    # query resolving to 2+ entities must not misfire that check.
    many_lights = [
        EntitySnapshot("light.a", "A", "light", "on", attributes={"brightness": 255}),
        EntitySnapshot("light.b", "B", "light", "on", attributes={"brightness": 200}),
    ]
    result = engine.match("welche Lichter sind mindestens 50 Prozent", many_lights)
    assert result is not None
    assert len(result.command.entities) == 2


def test_comparison_components_have_free_order(engine):
    for parts in permutations(("welche Lichter", "sind", "mindestens", "50 Prozent")):
        result = engine.match(" ".join(parts) + "?", LIGHTS_AND_COVERS)

        assert result is not None, parts
        assert result.plan is None
        assert result.command.entities == (LIGHTS_AND_COVERS[0],)


def test_temperature_comparison_components_have_free_order(engine):
    for parts in permutations(("welche Räume", "im Wohnzimmer", "unter", "20 Grad")):
        result = engine.match(" ".join(parts) + "?", ROOMS)

        assert result is not None, parts
        assert result.plan is None
        assert result.command.entities == (ROOMS[0],)
