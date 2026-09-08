from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_graph import SemanticNodeKind, build_semantic_graph
from ha_nlu.nlu.temporal_semantics import TemporalKind


def test_delay_and_duration_are_distinct_meanings():
    delay = analyse_language("Mach das Licht in zehn Minuten aus.")
    duration = analyse_language("Mach das Licht für zehn Minuten an.")

    assert [(item.kind, item.seconds) for item in delay.temporal] == [
        (TemporalKind.RELATIVE_DELAY, 600)
    ]
    assert [(item.kind, item.seconds) for item in duration.temporal] == [
        (TemporalKind.DURATION, 600)
    ]


def test_since_and_sun_event_are_structural_even_when_not_executable():
    document = analyse_language(
        "Wenn die Tür seit fünf Minuten offen ist, mach das Licht nach Sonnenuntergang an."
    )
    kinds = {item.kind for item in document.temporal}
    assert {TemporalKind.SINCE, TemporalKind.AFTER, TemporalKind.SUN_EVENT} <= kinds
    graph = build_semantic_graph(
        document.source_text,
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )
    assert len(graph.nodes_of_kind(SemanticNodeKind.TEMPORAL)) >= 3


def test_absolute_time_and_weekday_are_typed():
    document = analyse_language("Mach das Licht Montag um 22 Uhr aus.")
    assert {(item.kind, item.value) for item in document.temporal} == {
        (TemporalKind.WEEKDAY, "montag"),
        (TemporalKind.ABSOLUTE_TIME, "22:00"),
    }
