import json
from pathlib import Path

import pytest

from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_graph import build_semantic_graph
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.semantic_interpreter import SemanticInterpreter
from ha_nlu.nlu.understanding import UnderstandingKind
from ha_nlu.world_model import build_world_model


CORPUS = json.loads(
    (Path(__file__).parent / "data" / "v8_ood_de.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CORPUS, ids=lambda case: case["id"])
def test_handwritten_ood_corpus_retains_expected_relations(case):
    document = analyse_language(case["text"])
    observed = {relation.kind.name.lower() for relation in document.structure.relations}
    graph = build_semantic_graph(
        case["text"],
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )
    semantic_nodes = {
        (node.kind.name.lower(), node.value) for node in graph.nodes
    }
    semantic_edges = {edge.kind.name.lower() for edge in graph.edges}

    assert set(case["relations"]) <= observed
    assert case.get("speech_act", document.utterance.speech_act.name.lower()) == (
        document.utterance.speech_act.name.lower()
    )
    assert {
        (kind, value) for kind, value in case.get("semantic_nodes", ())
    } <= semantic_nodes
    assert set(case.get("semantic_edges", ())) <= semantic_edges
    assert document.structure.clauses
    assert all(clause.char_start < clause.char_end for clause in document.structure.clauses)


def test_unknown_meaning_bearing_predicate_is_not_silently_executable(engine):
    outcome = engine.understand("Mach das Küchenlicht flauschig.", [])

    assert not outcome.actionable
    assert "flauschig" in outcome.unexplained_tokens


PIPELINE_ENTITIES = [
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "on",
        area_id="kitchen", area_name="Küche",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    ),
    EntitySnapshot(
        "light.wohnzimmer", "Wohnzimmerlicht", "light", "on",
        area_id="living", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    ),
    EntitySnapshot(
        "light.stehlampe", "Stehlampe", "light", "on",
        area_id="living", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "binary_sensor.kuechenfenster", "Küchenfenster", "binary_sensor", "on",
        area_id="kitchen", area_name="Küche", device_class="window",
    ),
]


@pytest.mark.parametrize(
    ("text", "expected", "actionable"),
    [
        ("Im Wohnzimmer bitte das Licht ausmachen.", UnderstandingKind.COMMAND, True),
        ("Mach äh das Küchenlicht aus.", UnderstandingKind.COMMAND, True),
        (
            "Mach das Küchenlicht an, äh nein, das Wohnzimmerlicht.",
            UnderstandingKind.COMMAND,
            True,
        ),
        ("Mach alle Lampen aus, die noch an sind.", UnderstandingKind.COMMAND, True),
        (
            "Mach alle Lampen außer der Stehlampe aus.",
            UnderstandingKind.COMMAND,
            True,
        ),
        (
            "Mach das Küchenlicht für zehn Minuten an.",
            UnderstandingKind.UNSUPPORTED,
            False,
        ),
        (
            "Was würde passieren, wenn ich das Küchenlicht ausschalte?",
            UnderstandingKind.QUERY,
            False,
        ),
        (
            "Das Wohnzimmerlicht ist mir zu hell.",
            UnderstandingKind.CLARIFICATION,
            False,
        ),
        (
            "Mach das Küchenlicht flauschig aus.",
            UnderstandingKind.UNSUPPORTED,
            False,
        ),
        (
            "Mach entweder das Küchenlicht oder das Wohnzimmerlicht an.",
            UnderstandingKind.AMBIGUOUS,
            False,
        ),
        ("Welche Fenster sind offen?", UnderstandingKind.QUERY, False),
    ],
)
def test_handwritten_ood_cases_reach_the_complete_understanding_boundary(
    engine, text, expected, actionable
):
    world = build_world_model(PIPELINE_ENTITIES, [])
    document = analyse_language(text, PIPELINE_ENTITIES)
    interpreted = SemanticInterpreter.interpret(
        document, PIPELINE_ENTITIES, world, resolve_registry=False
    )
    outcome = engine.understand(
        text, PIPELINE_ENTITIES, world, document=document
    )

    assert document.structure.clauses
    assert interpreted.candidates
    assert all(candidate.graph is not None for candidate in interpreted.candidates)
    assert outcome.kind is expected
    assert outcome.actionable is actionable
    if outcome.payload is not None:
        assert outcome.payload.plan is None or expected is UnderstandingKind.COMMAND
