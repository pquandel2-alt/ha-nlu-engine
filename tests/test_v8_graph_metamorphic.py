import pytest

from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_graph import SemanticNodeKind, build_semantic_graph


def _meaning_nodes(text: str):
    document = analyse_language(text)
    graph = build_semantic_graph(
        text,
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )
    return tuple(sorted(
        (node.kind.name, node.value)
        for node in graph.nodes
        if node.kind not in {SemanticNodeKind.UTTERANCE, SemanticNodeKind.CLAUSE}
    ))


@pytest.mark.parametrize(
    "variant",
    [
        "Schalte das Licht aus.",
        "Das Licht bitte ausschalten.",
        "Kannst du mal eben das Licht ausschalten?",
        "Im Wohnzimmer das Licht ausmachen.",
        "Das Licht im Wohnzimmer bitte aus.",
    ],
)
def test_safe_surface_transformations_preserve_core_graph_meaning(variant):
    baseline = _meaning_nodes("Mach das Licht im Wohnzimmer aus.")

    assert _meaning_nodes(variant) == baseline
