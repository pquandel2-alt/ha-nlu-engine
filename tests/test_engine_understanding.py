from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.parse_outcome import ParseFailureReason
from ha_nlu.nlu.understanding import (
    UnderstandingKind,
    UnderstandingOutcome,
    compare_outcomes,
)
from ha_nlu.nlu.semantic_utterance import SpeechAct


def test_understand_returns_explicit_command_with_legacy_payload(engine, entities):
    outcome = engine.understand("Mach das Flurlicht an", entities)

    assert outcome.kind is UnderstandingKind.COMMAND
    assert outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan.service == "turn_on"
    assert outcome.route == "HassTurnOn"


def test_understand_returns_explicit_unsupported_reason(engine, entities):
    outcome = engine.understand("Erzähle mir eine Geschichte", entities)

    assert outcome.kind is UnderstandingKind.UNSUPPORTED
    assert outcome.reason is ParseFailureReason.NO_GRAMMAR
    assert outcome.payload is None


def test_understand_marks_negated_command_unsafe(engine, entities):
    outcome = engine.understand("Mach das Flurlicht nicht an", entities)

    assert outcome.kind is UnderstandingKind.UNSAFE
    assert outcome.reason is ParseFailureReason.UNSAFE_INFERENCE
    assert not outcome.actionable


def test_understand_uses_unique_bounded_action_spelling_variant(engine, entities):
    outcome = engine.understand("Bitte Flurlicht einschallten", entities)

    assert outcome.kind is UnderstandingKind.COMMAND
    assert outcome.payload is not None
    assert outcome.payload.plan.entity_id == "light.flur_licht"
    assert outcome.payload.plan.service == "turn_on"
    assert outcome.corrections == ("lexical_spelling",)


def test_misspelled_unknown_negation_cannot_become_actionable(engine, entities):
    outcome = engine.understand("Mach Flurlicht nciht an", entities)

    assert not outcome.actionable
    assert outcome.payload is None


def test_shadow_comparison_reports_semantic_differences():
    authoritative = UnderstandingOutcome(
        UnderstandingKind.COMMAND,
        "Licht an",
        "Licht an",
        SpeechAct.COMMAND,
        payload="plan",
    )
    candidate = UnderstandingOutcome(
        UnderstandingKind.QUERY,
        "Licht an",
        "Licht an",
        SpeechAct.QUERY,
    )

    comparison = compare_outcomes(authoritative, candidate)

    assert not comparison.equivalent
    assert any(item.startswith("kind:") for item in comparison.differences)
    assert "payload" in comparison.differences


def test_understand_surfaces_ambiguous_candidates_explicitly(engine):
    entities = [
        EntitySnapshot("light.a", "Leselicht", "light", "off"),
        EntitySnapshot("light.b", "Leselicht", "light", "off"),
    ]

    outcome = engine.understand("Mach das Leselicht an", entities)

    assert outcome.kind is UnderstandingKind.AMBIGUOUS
    assert outcome.payload is not None
    assert outcome.payload.clarification is not None
    assert len(outcome.payload.clarification.candidates) == 2
