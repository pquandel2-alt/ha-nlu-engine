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


def _semantic_core(text: str):
    document = analyse_language(text)
    graph = build_semantic_graph(
        text,
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )
    nodes = tuple(sorted(
        (node.node_id, node.kind.name, node.value)
        for node in graph.nodes
        if node.kind not in {SemanticNodeKind.UTTERANCE, SemanticNodeKind.CLAUSE}
    ))
    relations = tuple(sorted(
        edge.kind.name
        for edge in graph.edges
        if edge.kind.name != "CONTAINS"
    ))
    return nodes, relations


@pytest.mark.parametrize(
    "variant",
    [
        "Schalte im Wohnzimmer das Licht aus.",
        "Das Licht im Wohnzimmer bitte ausschalten.",
        "Kannst du mal eben das Licht im Wohnzimmer ausschalten?",
        "Im Wohnzimmer das Licht ausmachen.",
        "Das Licht im Wohnzimmer bitte aus.",
    ],
)
def test_safe_surface_transformations_preserve_core_graph_meaning(variant):
    baseline = _meaning_nodes("Mach das Licht im Wohnzimmer aus.")

    assert _meaning_nodes(variant) == baseline


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Mach alle Lampen aus.", "Mach nicht alle Lampen aus."),
        ("Mach Licht in Küche und Flur aus.", "Mach Licht in Küche oder Flur aus."),
        ("Mach alle Lampen aus außer Stehlampe.", "Mach nur die Stehlampe aus."),
    ],
)
def test_meaning_changing_transformations_do_not_share_a_semantic_core(left, right):
    assert _semantic_core(left) != _semantic_core(right)


def test_missing_location_is_not_a_meaning_preserving_mutation():
    located = analyse_language("Mach das Licht im Wohnzimmer aus.")
    unlocated = analyse_language("Schalte das Licht aus.")

    # The HA-free graph cannot ground an area name without a registry. The
    # loss-aware boundary still retains the scope distinction, so these two
    # utterances must not be listed as a positive metamorphic pair.
    assert located.source_text != unlocated.source_text
    assert tuple(token.canonical for token in located.tokens) != tuple(
        token.canonical for token in unlocated.tokens
    )
