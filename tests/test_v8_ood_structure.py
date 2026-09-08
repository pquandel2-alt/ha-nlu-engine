import json
from pathlib import Path

import pytest

from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_graph import build_semantic_graph


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
