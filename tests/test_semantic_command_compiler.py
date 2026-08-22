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
