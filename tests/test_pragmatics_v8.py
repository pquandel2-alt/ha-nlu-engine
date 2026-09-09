from ha_nlu.nlu.semantic_utterance import (
    PragmaticDisposition,
    analyse_utterance,
)
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.understanding import UnderstandingKind


def test_direct_and_polite_explicit_requests_are_executable():
    assert analyse_utterance("Mach das Licht aus.").pragmatic_disposition is (
        PragmaticDisposition.EXECUTABLE_REQUEST
    )
    assert analyse_utterance("Kannst du das Licht ausschalten?").pragmatic_disposition is (
        PragmaticDisposition.EXECUTABLE_REQUEST
    )


def test_implicit_complaint_requires_question_instead_of_action():
    utterance = analyse_utterance("Das Licht ist mir zu hell.")
    assert utterance.pragmatic_disposition is PragmaticDisposition.ASK_BEFORE_ACTION
    assert not utterance.safe_to_execute_directly


def test_neutral_statement_and_hypothesis_are_non_actionable():
    assert analyse_utterance("Das Licht ist hell.").pragmatic_disposition is (
        PragmaticDisposition.NON_ACTION
    )
    assert analyse_utterance(
        "Was passiert, wenn ich das Licht ausschalte?"
    ).pragmatic_disposition is PragmaticDisposition.READ_ONLY


def test_complaint_reaches_clarification_not_query_or_action(engine):
    light = EntitySnapshot(
        "light.wohnzimmer",
        "Wohnzimmerlicht",
        "light",
        "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    )

    outcome = engine.understand("Das Wohnzimmerlicht ist mir zu hell.", [light])

    assert outcome.kind is UnderstandingKind.CLARIFICATION
    assert not outcome.actionable
    assert outcome.payload is None


def test_hypothetical_is_explicitly_read_only_end_to_end(engine):
    light = EntitySnapshot(
        "light.wohnzimmer",
        "Wohnzimmerlicht",
        "light",
        "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    )

    outcome = engine.understand(
        "Was würde passieren, wenn ich das Wohnzimmerlicht ausschalte?",
        [light],
    )

    assert outcome.kind is UnderstandingKind.QUERY
    assert not outcome.actionable
    assert outcome.payload is None
