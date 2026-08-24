"""Behavioural tests for the model-free semantic command compiler.

These are deliberately phrased as combinations of meaning components, not
as additions to a sentence-template catalogue.  The same compiler must cope
with location, target, action and value in different orders.
"""

from __future__ import annotations

import pytest

from ha_nlu.entities import EntitySnapshot


HOUSE = [
    EntitySnapshot(
        "cover.eg_wohnzimmer", "Rollladen Wohnzimmer", "cover", "open",
        area_id="wohnzimmer", area_name="Wohnzimmer",
        floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
        capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot(
        "cover.eg_kueche", "Rollladen Küche", "cover", "open",
        area_id="kueche", area_name="Küche",
        floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
        capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot(
        "cover.dg_buero", "Rollladen Büro", "cover", "open",
        area_id="buero", area_name="Büro",
        floor_id="dg", floor_name="Dachgeschoss", floor_level=1,
        capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot(
        "light.flur", "Flurlicht", "light", "on",
        area_id="flur", area_name="Flur",
        floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    ),
]


@pytest.mark.parametrize(
    ("sentence", "service", "entity_id"),
    (
        ("Flurlicht bitte an", "turn_on", "light.flur"),
        ("Ich möchte, dass Flurlicht ausgeschaltet wird", "turn_off", "light.flur"),
        ("Rollladen Büro nach unten", "close_cover", "cover.dg_buero"),
        ("Komplett hochfahren soll Rollladen Büro", "open_cover", "cover.dg_buero"),
        ("Bitte Rollladen Büro auf halbe Höhe", "set_cover_position", "cover.dg_buero"),
        ("Stelle Rollladen Büro auf fünfzig Prozent", "set_cover_position", "cover.dg_buero"),
    ),
)
def test_request_envelopes_do_not_depend_on_sentence_templates(
    engine, sentence, service, entity_id
):
    result = engine.match(sentence, HOUSE)

    assert result is not None
    assert result.plan.service == service
    assert result.plan.entity_id == entity_id


def test_direction_word_inside_registered_name_is_not_a_floor_scope(engine):
    entities = HOUSE + [
        EntitySnapshot(
            "light.flur_unten", "Flurlicht unten", "light", "off",
            area_id="flur_unten", area_name="Flur unten",
            floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        )
    ]

    result = engine.match("Schalte Flurlicht unten ein", entities)

    assert result is not None
    assert result.plan.entity_id == "light.flur_unten"


def test_explicit_area_is_applied_before_duplicate_name_clarification(engine):
    entities = [
        EntitySnapshot(
            "light.buero", "Deckenlicht", "light", "off",
            area_id="buero", area_name="Büro",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.kueche", "Deckenlicht", "light", "off",
            area_id="kueche", area_name="Küche",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
    ]

    result = engine.match("Mach das Deckenlicht im Büro an", entities)

    assert result is not None
    assert result.clarification is None
    assert result.plan.entity_id == "light.buero"


@pytest.mark.parametrize(
    "sentence",
    (
        "Sämtliche Rollläden bitte im Erdgeschoss nach oben fahren",
        "Nach oben fahren sollen bitte im Erdgeschoss sämtliche Rollläden",
        "Im Erdgeschoss möchte ich sämtliche Rollläden nach oben gefahren haben",
    ),
)
def test_meaning_components_compose_independently_of_order(engine, sentence):
    result = engine.match(sentence, HOUSE)

    assert result is not None
    assert result.plan.service == "open_cover"
    assert sorted(result.plan.entity_id) == ["cover.eg_kueche", "cover.eg_wohnzimmer"]


@pytest.mark.parametrize(
    "sentence",
    (
        "Im Erdgeschoss sämtliche Rollläden bitte auf halbe Höhe stellen",
        "Auf halbe Höhe im Erdgeschoss bitte sämtliche Rollläden fahren",
        "Sämtliche im Erdgeschoss vorhandenen Rollläden auf 50 Prozent setzen",
    ),
)
def test_value_location_action_and_target_have_free_order(engine, sentence):
    result = engine.match(sentence, HOUSE)

    assert result is not None
    assert result.plan.service == "set_cover_position"
    assert result.plan.data == {"position": 50}
    assert sorted(result.plan.entity_id) == ["cover.eg_kueche", "cover.eg_wohnzimmer"]


def test_registry_entity_name_can_be_separated_from_action(engine):
    result = engine.match("Auf 35 Prozent bitte den Rollladen Büro stellen", HOUSE)

    assert result is not None
    assert result.plan.entity_id == "cover.dg_buero"
    assert result.plan.data == {"position": 35}


def test_compound_entity_name_supplies_domain_without_generic_target_word(engine):
    result = engine.match("Bitte ausschalten: das Flurlicht", HOUSE)

    assert result is not None
    assert result.plan.service == "turn_off"
    assert result.plan.entity_id == "light.flur"


@pytest.mark.parametrize(
    "sentence",
    (
        "Fahre sämtliche Rollläden im Erdgeschoss hoch und runter",
        "Fahre sämtliche Rollläden im unbekannten Bunker hoch",
    ),
)
def test_compiler_refuses_conflict_question_and_unknown_scope(engine, sentence):
    assert engine.match(sentence, HOUSE) is None


def test_state_question_remains_a_query_and_never_becomes_a_command(engine):
    result = engine.match("Sind sämtliche Rollläden im Erdgeschoss oben?", HOUSE)

    assert result is not None
    assert result.plan is None
    assert result.frame.intent == "HassStateQuery"


def test_compiler_exposes_composed_semantic_primitives(engine):
    result = engine.match(
        "Auf halbe Höhe im Erdgeschoss bitte sämtliche Rollläden fahren", HOUSE
    )

    assert result.frame.action.name == "SET"
    assert result.frame.property.name == "POSITION"
    assert result.frame.quantity.kind.name == "ALL"


@pytest.mark.parametrize(
    "sentence",
    (
        "Mach in Küche und Flur alle Lichter aus",
        "Alle Lichter ausschalten, und zwar im Flur und in der Küche",
        "In der Küche und im Flur möchte ich sämtliche Lichter ausgeschaltet haben",
    ),
)
def test_coordinated_locations_form_one_order_independent_scope(engine, sentence):
    result = engine.match(sentence, HOUSE)

    assert result is not None
    assert result.plan.service == "turn_off"
    assert result.plan.entity_id == "light.flur"
    assert result.frame.parameters["locations"] == (
        {"text": "Küche", "area_id": "kueche", "floor_id": None},
        {"text": "Flur", "area_id": "flur", "floor_id": None},
    ) or result.frame.parameters["locations"] == (
        {"text": "Flur", "area_id": "flur", "floor_id": None},
        {"text": "Küche", "area_id": "kueche", "floor_id": None},
    )


def test_multiple_exclusions_are_composed_without_sentence_template(engine):
    entities = HOUSE + [
        EntitySnapshot(
            "light.kueche", "Küchenlicht", "light", "on",
            area_id="kueche", area_name="Küche",
            floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.wohnzimmer", "Wohnzimmerlicht", "light", "on",
            area_id="wohnzimmer", area_name="Wohnzimmer",
            floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
    ]

    result = engine.match(
        "Im Erdgeschoss alle Lichter aus, mit Ausnahme von Küchenlicht und Flurlicht",
        entities,
    )

    assert result is not None
    assert result.plan.entity_id == "light.wohnzimmer"
    assert result.frame.quantity.kind.name == "EXCLUDE"
    assert result.frame.quantity.excluded == ("Küchenlicht", "Flurlicht")


@pytest.mark.parametrize(
    "sentence",
    (
        "Mach alle Lichter aus außer Unbekanntes Licht",
        "Mach beide Lichter aus außer Flurlicht",
        "Mach alle Lichter aus außer Flurlicht und Flurlicht",
    ),
)
def test_ambiguous_or_invalid_exclusions_never_execute(engine, sentence):
    assert engine.match(sentence, HOUSE) is None


@pytest.mark.parametrize(
    "sentence",
    (
        "Fahre sämtliche Rollläden im Erdgeschoss nicht hoch",
        "Fahre vielleicht sämtliche Rollläden im Erdgeschoss hoch",
        "Fahre sämtliche Rollläden im Erdgeschoss normalerweise hoch",
        "Fahre sämtliche Rollläden im Erdgeschoss gestern hoch",
    ),
)
def test_unexplained_modifiers_can_never_create_a_service_plan(engine, sentence):
    result = engine.match(sentence, HOUSE)

    assert result is None or result.plan is None
