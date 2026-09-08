from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.repair_semantics import repair_sequences
from ha_nlu.nlu.semantic_graph import SemanticEdgeKind, build_semantic_graph


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
