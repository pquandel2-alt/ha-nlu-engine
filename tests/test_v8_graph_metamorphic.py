import pytest

from ha_nlu.engine import NluEngine
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_graph import SemanticNodeKind, build_semantic_graph
from ha_nlu.nlu.understanding import UnderstandingKind
from ha_nlu.world_model import build_world_model


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
    entities = [
        EntitySnapshot(
            "light.living", "Wohnzimmerlicht", "light", "on",
            area_id="living", area_name="Wohnzimmer",
        ),
        EntitySnapshot(
            "light.kitchen", "Küchenlicht", "light", "on",
            area_id="kitchen", area_name="Küche",
        ),
    ]
    world = build_world_model(entities, [])
    engine = NluEngine()

    located = engine.understand("Mach das Licht im Wohnzimmer aus.", entities, world)
    unlocated = engine.understand("Mach das Licht aus.", entities, world)

    assert located.kind is UnderstandingKind.COMMAND
    assert located.payload is not None
    assert tuple(entity.entity_id for entity in located.payload.command.entities) == (
        "light.living",
    )
    assert unlocated.kind in {UnderstandingKind.AMBIGUOUS, UnderstandingKind.UNSUPPORTED}
    assert not unlocated.actionable
    assert unlocated.payload is None
    assert located.payload.frame is not None
    assert located.payload.frame.target is not None
    assert located.payload.frame.target.entity_id == "light.living"
