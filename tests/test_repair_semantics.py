from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.repair_semantics import repair_sequences
from ha_nlu.nlu.semantic_graph import SemanticEdgeKind, build_semantic_graph
from ha_nlu.entities import EntitySnapshot


KITCHEN = EntitySnapshot(
    "light.kitchen", "Küchenlicht", "light", "on",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
LIVING = EntitySnapshot(
    "light.living", "Wohnzimmerlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)


def test_repair_retains_original_marker_and_replacement():
    document = analyse_language("Stell die Heizung auf 22, nein 21 Grad.")
    repairs = repair_sequences(document.structure)

    assert len(repairs) == 1
    assert repairs[0].marker == "nein"
    graph = build_semantic_graph(
        document.source_text,
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )
    assert any(edge.kind is SemanticEdgeKind.REPLACES for edge in graph.edges)


def test_unambiguous_target_repair_executes_only_replacement(engine):
    outcome = engine.understand(
        "Mach das Küchenlicht an, äh nein, das Wohnzimmerlicht.",
        [KITCHEN, LIVING],
    )

    assert outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is not None
    assert outcome.payload.plan.entity_id == LIVING.entity_id
    assert outcome.payload.frame is not None
    assert outcome.payload.frame.semantic_graph is not None
    assert any(
        edge.kind is SemanticEdgeKind.REPLACES
        for edge in outcome.payload.frame.semantic_graph.edges
    )


def test_value_repair_is_parsed_but_not_silently_simplified(engine):
    climate = EntitySnapshot(
        "climate.living", "Wohnzimmerheizung", "climate", "heat",
        attributes={"temperature": 20},
        capabilities=frozenset({"SET_TEMPERATURE"}),
    )

    outcome = engine.understand(
        "Stell die Wohnzimmerheizung auf 22 Grad, nein 21 Grad.", [climate]
    )

    assert not outcome.actionable
