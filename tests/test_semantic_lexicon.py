"""Safety and composition tests for the shared span-based lexicon."""

from __future__ import annotations

from itertools import permutations

from ha_nlu.nlu.semantic_lexicon import SemanticKind, analyse_semantics
from ha_nlu.nlu.semantic_state import SemanticState


def test_multiword_meanings_keep_exact_source_spans():
    text = "Wie viele offene Fenster gibt es?"
    analysis = analyse_semantics(text)

    count = analysis.matching(SemanticKind.QUERY_SCOPE)[0]
    assert (count.text, count.start, count.end) == ("Wie viele", 0, 9)
    assert ("binary_sensor", "window") in analysis.values(SemanticKind.DEVICE_CLASS)
    assert SemanticState.OPEN in analysis.values(SemanticKind.STATE)


def test_lexicon_detects_conflicting_meaning_without_word_order_rules():
    analysis = analyse_semantics("Fahre alle Rollläden hoch und runter")

    assert analysis.conflicts(SemanticKind.ACTION)
    assert analysis.values(SemanticKind.ACTION) == frozenset({"open", "close"})


def test_every_permutation_produces_the_same_semantic_facts():
    parts = ("sind", "im Erdgeschoss", "offene", "Fenster")
    expected = None
    for order in permutations(parts):
        analysis = analyse_semantics(" ".join(order))
        facts = (
            analysis.values(SemanticKind.DEVICE_CLASS),
            analysis.values(SemanticKind.STATE),
        )
        expected = facts if expected is None else expected
        assert facts == expected


def test_unknown_meaningful_words_are_reported_but_fillers_are_not():
    analysis = analyse_semantics("Kannst du bitte alle unbekannten Sensoren kalibrieren?")

    assert "unbekannten" in analysis.unexplained_tokens
    assert "Sensoren" in analysis.unexplained_tokens
    assert "kalibrieren" in analysis.unexplained_tokens
    assert "Kannst" not in analysis.unexplained_tokens
    assert "bitte" not in analysis.unexplained_tokens
