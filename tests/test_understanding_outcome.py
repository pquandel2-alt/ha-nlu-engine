from ha_nlu.nlu.semantic_utterance import SpeechAct
from ha_nlu.nlu.understanding import UnderstandingKind, UnderstandingOutcome


def test_only_validated_writing_outcomes_are_actionable():
    command = UnderstandingOutcome(
        kind=UnderstandingKind.COMMAND,
        source_text="Licht an",
        normalized_text="Licht an",
        speech_act=SpeechAct.COMMAND,
        payload=object(),
    )
    unresolved = UnderstandingOutcome(
        kind=UnderstandingKind.COMMAND,
        source_text="Licht an",
        normalized_text="Licht an",
        speech_act=SpeechAct.COMMAND,
    )

    assert command.actionable
    assert not unresolved.actionable


def test_query_and_rejections_are_explicit_safe_non_actions():
    for kind in (
        UnderstandingKind.QUERY,
        UnderstandingKind.CLARIFICATION,
        UnderstandingKind.AMBIGUOUS,
        UnderstandingKind.UNSUPPORTED,
        UnderstandingKind.UNSAFE,
    ):
        outcome = UnderstandingOutcome(
            kind=kind,
            source_text="test",
            normalized_text="test",
            speech_act=SpeechAct.QUERY,
        )
        assert outcome.safe_non_action
        assert not outcome.actionable
