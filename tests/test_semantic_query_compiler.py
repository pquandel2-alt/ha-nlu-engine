"""Compositional state-query tests without sentence-template enumeration."""

from __future__ import annotations

from itertools import permutations

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.semantic_compiler import SemanticQueryCompiler
from ha_nlu.nlu.understanding import UnderstandingAuthority


WINDOWS = [
    EntitySnapshot(
        "binary_sensor.wohnzimmer", "Wohnzimmerfenster", "binary_sensor", "on",
        area_id="wohnzimmer", area_name="Wohnzimmer",
        floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
        device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.kueche", "Küchenfenster", "binary_sensor", "off",
        area_id="kueche", area_name="Küche",
        floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
        device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.buero", "Bürofenster", "binary_sensor", "on",
        area_id="buero", area_name="Büro",
        floor_id="dg", floor_name="Dachgeschoss", floor_level=1,
        device_class="window",
    ),
]


@pytest.mark.parametrize(
    "sentence",
    (
        "Sind im Erdgeschoss offene Fenster?",
        "Sind Fenster offen im Erdgeschoss?",
        "Im Erdgeschoss offene Fenster?",
        "Fenster offen Erdgeschoss?",
        "Offene Fenster, gibt es die im Erdgeschoss?",
        "Im Erdgeschoss, sind davon irgendwelche Fenster offen?",
    ),
)
def test_state_query_components_have_free_order(engine, sentence):
    result = engine.match(sentence, WINDOWS)

    assert result is not None
    assert result.plan is None
    assert [entity.entity_id for entity in result.command.entities] == [
        "binary_sensor.wohnzimmer"
    ]
    assert "Wohnzimmerfenster" in result.response_text or result.response_text.startswith("Ja")

    outcome = engine.understand(sentence, WINDOWS)
    assert outcome.authority is UnderstandingAuthority.V7_MIGRATED
    assert outcome.payload is not None
    assert outcome.payload.plan is None


@pytest.mark.parametrize(
    "sentence",
    (
        "Gibt es im Erdgeschoss noch ein offenes Fenster?",
        "Welche Fenster stehen im Erdgeschoss noch offen?",
        "Sind im Erdgeschoss offene Fenster vorhanden?",
        "Sag mir bitte, ob im Erdgeschoss Fenster offen sind",
    ),
)
def test_natural_state_query_shells_share_one_semantic_query_path(engine, sentence):
    result = engine.match(sentence, WINDOWS)

    assert result is not None
    assert result.plan is None
    assert [entity.entity_id for entity in result.command.entities] == [
        "binary_sensor.wohnzimmer"
    ]


def test_every_order_of_the_same_semantic_components_compiles(engine):
    """24 arrangements, one meaning; no arrangement-specific templates."""
    for parts in permutations(("Sind", "im Erdgeschoss", "offene", "Fenster")):
        result = engine.match(" ".join(parts) + "?", WINDOWS)

        assert result is not None, parts
        assert result.plan is None
        assert [entity.entity_id for entity in result.command.entities] == [
            "binary_sensor.wohnzimmer"
        ]


def test_closed_state_uses_same_composition_without_new_sentence_rule(engine):
    result = engine.match("Im Erdgeschoss: geschlossen, welche Fenster sind das?", WINDOWS)

    assert result is not None
    assert result.plan is None
    assert [entity.entity_id for entity in result.command.entities] == ["binary_sensor.kueche"]


def test_count_scope_is_composed_independently(engine):
    result = engine.match("Offene Fenster im ganzen Erdgeschoss, wie viele sind es?", WINDOWS)

    assert result is not None
    assert result.response_text == "1 Fenster ist geöffnet."


def test_no_matching_state_is_a_valid_answer(engine):
    result = engine.match("Gibt es im Dachgeschoss geschlossene Fenster?", WINDOWS)

    assert result is not None
    assert result.plan is None
    assert result.response_text == "Nein, es gibt keine Fenster."


@pytest.mark.parametrize(
    "sentence",
    (
        "Sind Fenster offen und geschlossen?",
        "Sind Fenster und Türen im Erdgeschoss offen?",
        "Fahre die Fenster im Erdgeschoss auf?",
    ),
)
def test_query_compiler_refuses_semantic_conflicts_and_commands(sentence):
    assert SemanticQueryCompiler.compile(sentence, WINDOWS) is None


def test_query_frame_marks_read_only_semantics(engine):
    result = engine.match("Sind im Erdgeschoss offene Fenster?", WINDOWS)

    assert result.frame.action.name == "QUERY"
    assert result.frame.quantity.kind.name == "ALL"


@pytest.mark.parametrize(
    ("sentence", "expected_ids"),
    (
        (
            "Welche Fenster sind im Erdgeschoss?",
            ["binary_sensor.wohnzimmer", "binary_sensor.kueche"],
        ),
        (
            "Im Erdgeschoss, welche Fenster gibt es dort?",
            ["binary_sensor.wohnzimmer", "binary_sensor.kueche"],
        ),
        ("Gibt es Fenster im Dachgeschoss?", ["binary_sensor.buero"]),
    ),
)
def test_stateless_plural_queries_use_the_same_composition(engine, sentence, expected_ids):
    result = engine.match(sentence, WINDOWS)

    assert result is not None
    assert result.plan is None
    assert {entity.entity_id for entity in result.command.entities} == set(expected_ids)


def test_every_bare_query_permutation_is_read_only(engine):
    for parts in permutations(("Welche", "Fenster", "im Erdgeschoss")):
        result = engine.match(" ".join(parts) + "?", WINDOWS)

        assert result is not None, parts
        assert result.plan is None
        assert {entity.entity_id for entity in result.command.entities} == {
            "binary_sensor.wohnzimmer",
            "binary_sensor.kueche",
        }


@pytest.mark.parametrize(
    "sentence",
    (
        "Welche Fenster sind in Küche und Büro offen?",
        "In Büro und Küche: welche offenen Fenster gibt es?",
        "Offene Fenster in der Küche und im Büro, wo sind sie?",
    ),
)
def test_coordinated_query_locations_are_one_read_only_union(engine, sentence):
    result = engine.match(sentence, WINDOWS)

    assert result is not None
    assert result.plan is None
    assert {entity.entity_id for entity in result.command.entities} == {
        "binary_sensor.buero",
    }
    assert len(result.frame.parameters["locations"]) == 2


def test_or_connected_locations_remain_ambiguous(engine):
    assert engine.match("Sind in Küche oder Büro Fenster offen?", WINDOWS) is None
