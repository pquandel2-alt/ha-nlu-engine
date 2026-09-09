from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.composition import (
    build_compositional_plan,
    build_document_compositional_plan,
    independent_predicate_clauses,
    project_target,
)
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.meaning import analyse_turn
from ha_nlu.nlu.semantic_graph import build_semantic_graph
from ha_nlu.nlu.semantic_projection import project_independent_predicates
from ha_nlu.world_model import build_world_model


LIGHTS = [
    EntitySnapshot("light.kueche", "Küchenlicht", "light", "off"),
    EntitySnapshot("light.flur", "Flurlicht", "light", "off"),
]


def test_shared_predicate_becomes_one_atomic_compositional_plan():
    plan = build_compositional_plan(
        analyse_turn("Schalte Küchenlicht sowie Flurlicht aus"), LIGHTS
    )

    assert plan is not None and plan.atomic and plan.shared_predicate
    assert {item.entity_id for item in plan.targets} == {"light.kueche", "light.flur"}
    assert project_target(plan, LIGHTS[0]) == "Schalte Küchenlicht aus"


def test_alternative_or_multiple_commands_are_not_collapsed():
    assert build_compositional_plan(
        analyse_turn("Schalte Küchenlicht oder Flurlicht aus"), LIGHTS
    ) is None
    assert build_compositional_plan(
        analyse_turn("Schalte Küchenlicht aus und öffne Flurlicht"), LIGHTS
    ) is None


def test_production_composition_uses_the_existing_language_document():
    document = analyse_language(
        "Schalte Küchenlicht sowie Flurlicht aus", LIGHTS
    )

    plan = build_document_compositional_plan(document, LIGHTS)

    assert plan is not None
    assert plan.source_text == document.source_text
    assert plan.action == "turn_off"
    assert {entity.entity_id for entity in plan.targets} == {
        "light.kueche", "light.flur"
    }


def test_structural_and_distinguishes_targets_from_independent_predicates():
    shared = analyse_language("Schalte Küchenlicht und Flurlicht aus", LIGHTS)
    independent = analyse_language(
        "Schalte Küchenlicht an und Flurlicht aus", LIGHTS
    )

    assert independent_predicate_clauses(shared) == ()
    assert independent_predicate_clauses(independent) == (
        "Schalte Küchenlicht an",
        "Flurlicht aus",
    )


def test_independent_predicates_project_directly_without_language_reparse():
    document = analyse_language(
        "Schalte Küchenlicht an und Flurlicht aus", LIGHTS
    )
    graph = build_semantic_graph(
        document.source_text,
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )

    projected = project_independent_predicates(
        document, graph, LIGHTS, build_world_model(LIGHTS, [])
    )

    assert tuple(result.frame.intent for result in projected) == (
        "HassTurnOn",
        "HassTurnOff",
    )
    assert tuple(result.resolved_entities[0].entity_id for result in projected) == (
        "light.kueche",
        "light.flur",
    )
