from ha_nlu.nlu.semantic_utterance import (
    PragmaticDisposition,
    analyse_utterance,
)


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
