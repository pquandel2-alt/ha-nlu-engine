from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_graph import (
    SemanticEdgeKind,
    SemanticNodeKind,
    build_semantic_graph,
)
from ha_nlu.nlu.semantic_interpreter import SemanticInterpreter


def _graph(text: str):
    document = analyse_language(text)
    return build_semantic_graph(
        text,
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )


def test_graph_models_relative_state_as_filter_not_competing_root_action():
    graph = _graph("Mach alle Lampen aus, die noch an sind.")

    actions = graph.nodes_of_kind(SemanticNodeKind.ACTION)
    assert {node.value for node in actions} >= {"turn_off", "turn_on"}
    assert any(edge.kind is SemanticEdgeKind.FILTER for edge in graph.edges)


def test_graph_models_exclusion_relation():
    graph = _graph("Mach alle Lampen aus außer der Stehlampe.")

    assert any(edge.kind is SemanticEdgeKind.EXCLUDE for edge in graph.edges)


def test_candidate_and_compatibility_frame_share_grounded_graph():
    entities = [
        EntitySnapshot(
            "light.kueche", "Küchenlicht", "light", "on",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        )
    ]
    result = SemanticInterpreter.interpret(
        analyse_language("Mach das Küchenlicht aus", entities), entities
    )

    candidate = next(item for item in result.candidates if item.complete)
    assert candidate.graph is not None
    assert {
        node.value
        for node in candidate.graph.nodes_of_kind(SemanticNodeKind.ENTITY)
    } == {"light.kueche"}
    assert result.parse_result is not None
    assert result.parse_result.frame.semantic_graph == candidate.graph


def test_graph_snapshot_is_stable_and_source_spanned():
    graph = _graph("Mach das Licht aus.")

    snapshot = graph.canonical_snapshot()
    assert snapshot["source"] == "Mach das Licht aus."
    assert snapshot["nodes"] == graph.canonical_snapshot()["nodes"]


def test_existing_location_resolver_grounds_area_relation():
    entities = [
        EntitySnapshot(
            "light.wohnzimmer", "Deckenlampe", "light", "on",
            area_id="living_room", area_name="Wohnzimmer",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        )
    ]
    result = SemanticInterpreter.interpret(
        analyse_language("Mach im Wohnzimmer alle Lichter aus", entities),
        entities,
    )

    graph = result.candidates[0].graph
    assert graph is not None
    assert {node.value for node in graph.nodes_of_kind(SemanticNodeKind.AREA)} == {
        "living_room"
    }
    assert any(edge.kind is SemanticEdgeKind.LOCATED_IN for edge in graph.edges)


def test_negation_is_a_scoped_graph_operator():
    graph = _graph("Mach das Küchenlicht nicht aus.")

    negations = graph.nodes_of_kind(SemanticNodeKind.NEGATION)
    assert len(negations) == 1
    assert any(
        edge.source == negations[0].node_id and edge.kind is SemanticEdgeKind.NOT
        for edge in graph.edges
    )


def test_conditions_time_values_and_references_are_not_flattened():
    graph = _graph("Wenn es seit 5 Minuten offen ist, mach es zu.")

    assert graph.nodes_of_kind(SemanticNodeKind.CONDITION)
    assert graph.nodes_of_kind(SemanticNodeKind.VALUE)
    assert graph.nodes_of_kind(SemanticNodeKind.REFERENCE)
    assert any(edge.kind is SemanticEdgeKind.CONDITION for edge in graph.edges)
