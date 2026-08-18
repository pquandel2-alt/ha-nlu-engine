"""V5 Wave 1 (V5.3): automation_trigger_parser.py's AutomationTriggerParser -
spoken automation-trigger sentences -> nlu.automation_model.TriggerModel.

Two positive cases per trigger type, plus negative/ambiguity/large-range
cases, plus the architecture-required semantic-equivalence tests (several
natural phrasings of "the same trigger" must produce an *identical*
TriggerModel; STATE and NUMERIC_STATE triggers must stay distinguishable,
never artificially merged).

This parser has no caller in engine.py/conversation.py in this wave (see its
own module docstring) - tests exercise it directly, mirroring
tests/test_parsers.py's "call the parser, not the engine" style.
"""

from __future__ import annotations

import pytest
from hassil import Intents

from ha_nlu.automation_trigger_parser import AUTOMATION_TRIGGER_DIR, AutomationTriggerParser
from ha_nlu.devices import DeviceSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.automation_model import NumericComparator, SunEvent, TriggerType
from ha_nlu.nlu.parser import ParseContext
from ha_nlu.nlu.semantic_state import SemanticState
from ha_nlu.world_model import build_world_model

KUECHE_FENSTER = EntitySnapshot(
    entity_id="binary_sensor.kueche_fenster", friendly_name="Küchenfenster", domain="binary_sensor",
    state="off", area_id="kueche", area_name="Küche", device_class="window",
)
WOHNZIMMER_FENSTER = EntitySnapshot(
    entity_id="binary_sensor.wohnzimmer_fenster", friendly_name="Wohnzimmer Fenster", domain="binary_sensor",
    state="off", area_id="wohnzimmer", area_name="Wohnzimmer", device_class="window",
)
KUECHE_TUER = EntitySnapshot(
    entity_id="binary_sensor.kueche_tuer", friendly_name="Küchentür", domain="binary_sensor",
    state="off", area_id="kueche", area_name="Küche", device_class="door",
)
WOHNZIMMER_TEMPERATUR = EntitySnapshot(
    entity_id="sensor.wohnzimmer_temperatur", friendly_name="Wohnzimmer Temperatur", domain="sensor",
    state="20", area_id="wohnzimmer", area_name="Wohnzimmer", device_class="temperature",
)
KUECHE_LUFTFEUCHTIGKEIT = EntitySnapshot(
    entity_id="sensor.kueche_luftfeuchtigkeit", friendly_name="Küche Luftfeuchtigkeit", domain="sensor",
    state="45", area_id="kueche", area_name="Küche", device_class="humidity",
)
PHILIPP = EntitySnapshot(entity_id="person.philipp", friendly_name="Philipp", domain="person", state="home")
ANNA = EntitySnapshot(entity_id="person.anna", friendly_name="Anna", domain="person", state="not_home")
WOHNZIMMER_TASTER_ENTITY = EntitySnapshot(
    entity_id="sensor.wohnzimmer_taster_action", friendly_name="Wohnzimmer Taster", domain="sensor",
    state="", area_id="wohnzimmer", area_name="Wohnzimmer",
)
FLUR_TASTER_ENTITY = EntitySnapshot(
    entity_id="sensor.flur_taster_action", friendly_name="Flur Taster", domain="sensor",
    state="", area_id="flur", area_name="Flur",
)

ALL_ENTITIES = [
    KUECHE_FENSTER, WOHNZIMMER_FENSTER, KUECHE_TUER, WOHNZIMMER_TEMPERATUR, KUECHE_LUFTFEUCHTIGKEIT,
    PHILIPP, ANNA, WOHNZIMMER_TASTER_ENTITY, FLUR_TASTER_ENTITY,
]
ALL_DEVICES = [
    DeviceSnapshot(
        device_id="dev_wohnzimmer_taster", name="Wohnzimmer Taster", area_id="wohnzimmer", area_name="Wohnzimmer",
        entity_ids=("sensor.wohnzimmer_taster_action",),
    ),
    DeviceSnapshot(
        device_id="dev_flur_taster", name="Flur Taster", area_id="flur", area_name="Flur",
        entity_ids=("sensor.flur_taster_action",),
    ),
]


@pytest.fixture(scope="module")
def parser() -> AutomationTriggerParser:
    yaml_files = list(AUTOMATION_TRIGGER_DIR.glob("*.yaml"))
    intents = Intents.from_files(yaml_files)
    return AutomationTriggerParser(intents)


@pytest.fixture(scope="module")
def context() -> ParseContext:
    world_model = build_world_model(ALL_ENTITIES, ALL_DEVICES)
    return ParseContext(entities=ALL_ENTITIES, index=world_model.entity_index, world_model=world_model)


# -- STATE ---------------------------------------------------------------


def test_state_trigger_via_device_class_and_area(parser, context):
    trigger = parser.parse("wenn das Fenster in der Küche geöffnet wird", context)
    assert trigger.type is TriggerType.STATE
    assert trigger.target.domain == "binary_sensor"
    assert trigger.target.device_class == "window"
    assert trigger.target.area_id == "kueche"
    assert trigger.target.entity_id is None
    assert trigger.state is SemanticState.OPEN


def test_state_trigger_via_named_entity_closing(parser, context):
    trigger = parser.parse("sobald das Küchenfenster geschlossen wird", context)
    assert trigger.type is TriggerType.STATE
    assert trigger.target.domain == "binary_sensor"
    assert trigger.target.device_class == "window"
    assert trigger.target.area_id == "kueche"
    assert trigger.state is SemanticState.CLOSED


def test_state_trigger_accepts_plural_verb_form_for_plural_device_class(parser, context):
    # Regression: "wird"/"werden" is a grammatical-number variant, not a
    # separate meaning - "die Fenster ... werden" must parse just like the
    # singular "das Fenster ... wird" (both device_class+area sentences).
    trigger = parser.parse("wenn die Fenster in der Küche geöffnet werden", context)
    assert trigger.type is TriggerType.STATE
    assert trigger.target.device_class == "window"
    assert trigger.target.area_id == "kueche"
    assert trigger.state is SemanticState.OPEN


# -- NUMERIC_STATE ---------------------------------------------------------


def test_numeric_state_trigger_above_threshold(parser, context):
    trigger = parser.parse("wenn die Wohnzimmer Temperatur über 25 Grad steigt", context)
    assert trigger.type is TriggerType.NUMERIC_STATE
    assert trigger.target.domain == "sensor"
    assert trigger.target.device_class == "temperature"
    assert trigger.target.area_id == "wohnzimmer"
    assert trigger.comparator is NumericComparator.ABOVE
    assert trigger.threshold == 25.0


def test_numeric_state_trigger_below_threshold(parser, context):
    trigger = parser.parse("falls die Küche Luftfeuchtigkeit unter 30 Prozent fällt", context)
    assert trigger.type is TriggerType.NUMERIC_STATE
    assert trigger.target.domain == "sensor"
    assert trigger.target.device_class == "humidity"
    assert trigger.target.area_id == "kueche"
    assert trigger.comparator is NumericComparator.BELOW
    assert trigger.threshold == 30.0


def test_numeric_state_trigger_refuses_inclusive_comparators_never_guesses_an_approximation(parser, context):
    # {comparator} also matches "mindestens"/"höchstens" (shared
    # _COMPARATOR_SLOT_LIST), but HA's numeric_state trigger has no
    # inclusive comparator - the parser must refuse (Regel 4), not silently
    # round to above/below.
    assert parser.parse("wenn die Wohnzimmer Temperatur mindestens 25 Grad liegt", context) is None


# -- DEVICE ---------------------------------------------------------------


def test_device_trigger_single_press(parser, context):
    trigger = parser.parse("wenn der Wohnzimmer Taster gedrückt wird", context)
    assert trigger.type is TriggerType.DEVICE
    assert trigger.device_id == "dev_wohnzimmer_taster"
    assert trigger.device_trigger_type == "pressed"


def test_device_trigger_double_press(parser, context):
    # Regression: the {name} WildcardSlotList directly precedes
    # {device_press_type} - with the slot list's entries in the wrong order
    # {name} used to swallow "doppelt"/"zweimal" as if it were part of the
    # entity name, making double_pressed unreachable.
    trigger = parser.parse("sobald der Wohnzimmer Taster doppelt gedrückt wird", context)
    assert trigger.type is TriggerType.DEVICE
    assert trigger.device_id == "dev_wohnzimmer_taster"
    assert trigger.device_trigger_type == "double_pressed"


def test_device_trigger_long_press(parser, context):
    trigger = parser.parse("wenn der Flur Taster gehalten wird", context)
    assert trigger.type is TriggerType.DEVICE
    assert trigger.device_id == "dev_flur_taster"
    assert trigger.device_trigger_type == "long_pressed"


# -- PRESENCE ---------------------------------------------------------------


def test_presence_trigger_arrival(parser, context):
    trigger = parser.parse("wenn Philipp nach Hause kommt", context)
    assert trigger.type is TriggerType.PRESENCE
    assert trigger.target.domain == "person"
    assert trigger.target.entity_id == "person.philipp"
    assert trigger.zone_id == "home"


def test_presence_trigger_departure(parser, context):
    trigger = parser.parse("sobald Anna das Haus verlässt", context)
    assert trigger.type is TriggerType.PRESENCE
    assert trigger.target.entity_id == "person.anna"
    assert trigger.zone_id == "home"


def test_presence_trigger_refuses_a_named_entity_that_is_not_a_person(parser, context):
    # "Küchenfenster" resolves, but isn't a person - never guess a presence
    # trigger for a non-person entity.
    assert parser.parse("wenn Küchenfenster nach Hause kommt", context) is None


# -- SUN ---------------------------------------------------------------


def test_sun_trigger_sunset(parser, context):
    trigger = parser.parse("bei Sonnenuntergang", context)
    assert trigger.type is TriggerType.SUN
    assert trigger.sun_event is SunEvent.SUNSET
    assert trigger.offset_minutes is None


def test_sun_trigger_sunrise_with_offset(parser, context):
    trigger = parser.parse("20 Minuten vor Sonnenaufgang", context)
    assert trigger.type is TriggerType.SUN
    assert trigger.sun_event is SunEvent.SUNRISE
    assert trigger.offset_minutes == -20


# -- TIME ---------------------------------------------------------------


def test_time_trigger_hour_only(parser, context):
    trigger = parser.parse("um 20 Uhr", context)
    assert trigger.type is TriggerType.TIME
    assert trigger.time_hour == 20
    assert trigger.time_minute == 0


def test_time_trigger_hour_and_minute(parser, context):
    trigger = parser.parse("wenn es 7 Uhr 15 ist", context)
    assert trigger.type is TriggerType.TIME
    assert trigger.time_hour == 7
    assert trigger.time_minute == 15


# -- WEEKDAY ---------------------------------------------------------------


def test_weekday_trigger_single_day(parser, context):
    trigger = parser.parse("wenn Montag ist", context)
    assert trigger.type is TriggerType.WEEKDAY
    assert trigger.weekdays == ("mon",)


def test_weekday_trigger_composite_weekend(parser, context):
    trigger = parser.parse("am Wochenende", context)
    assert trigger.type is TriggerType.WEEKDAY
    assert trigger.weekdays == ("sat", "sun")


# -- Negative / ambiguity cases ---------------------------------------------


def test_parser_returns_none_for_unrelated_sentences(parser, context):
    assert parser.parse("Das ergibt keinen Sinn", context) is None


def test_state_trigger_refuses_an_unknown_area(parser, context):
    assert parser.parse("wenn das Fenster im Partykeller geöffnet wird", context) is None


def test_state_trigger_refuses_an_unresolvable_name(parser, context):
    assert parser.parse("wenn das Dingsbums geöffnet wird", context) is None


def test_numeric_state_trigger_handles_a_wide_threshold_range_without_exploding(parser, context):
    # RangeSlotList(..., words=False, 0-5000) - a large numeric range that
    # must stay usable (no combinatorial explosion), not just a small one.
    trigger = parser.parse("wenn die Wohnzimmer Temperatur über 4999 Grad steigt", context)
    assert trigger.type is TriggerType.NUMERIC_STATE
    assert trigger.threshold == 4999.0


# -- Semantic equivalence (architecture addendum) ---------------------------


@pytest.mark.parametrize(
    "text",
    [
        "wenn das Küchenfenster geöffnet wird",
        "sobald das Fenster in der Küche aufgeht",
        "wenn das Küchenfenster offen wird",
    ],
)
def test_state_trigger_equivalent_phrasings_produce_an_identical_trigger_model(parser, context, text):
    trigger = parser.parse(text, context)
    assert trigger.type is TriggerType.STATE
    assert trigger.target.domain == "binary_sensor"
    assert trigger.target.device_class == "window"
    assert trigger.target.area_id == "kueche"
    # The compound name "Küchenfenster" does no disambiguation beyond
    # domain/device_class/area (it's the only window in the Küche) - so
    # entity_id must stay unset, exactly like the device_class+area phrasing
    # (see _build_named_target()'s equivalence recheck).
    assert trigger.target.entity_id is None
    assert trigger.state is SemanticState.OPEN


def test_state_and_numeric_state_triggers_stay_distinguishable_not_merged_across_domains():
    # Deliberate non-equivalence check: a STATE trigger (equality/transition,
    # binary_sensor) and a NUMERIC_STATE trigger (threshold, sensor) must
    # never collapse onto the same type/fields just because both are
    # "triggered by a change".
    yaml_files = list(AUTOMATION_TRIGGER_DIR.glob("*.yaml"))
    intents = Intents.from_files(yaml_files)
    parser = AutomationTriggerParser(intents)
    world_model = build_world_model(ALL_ENTITIES, ALL_DEVICES)
    context = ParseContext(entities=ALL_ENTITIES, index=world_model.entity_index, world_model=world_model)

    state_trigger = parser.parse("wenn das Küchenfenster geöffnet wird", context)
    numeric_trigger = parser.parse("wenn die Wohnzimmer Temperatur über 25 Grad steigt", context)

    assert state_trigger.type is TriggerType.STATE
    assert numeric_trigger.type is TriggerType.NUMERIC_STATE
    assert state_trigger.type != numeric_trigger.type
    assert state_trigger.state is not None
    assert numeric_trigger.state is None
    assert state_trigger.comparator is None
    assert numeric_trigger.comparator is not None
