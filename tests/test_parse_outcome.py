from ha_nlu.nlu.parse_outcome import ParseFailureReason, UnderstandingFeedback


def test_structured_feedback_is_non_actionable():
    feedback = UnderstandingFeedback(
        ParseFailureReason.UNSAFE_INFERENCE,
        "Diese Eigenschaft kann ich nur abfragen.",
        {"property": "battery"},
    )

    assert feedback.reason is ParseFailureReason.UNSAFE_INFERENCE
    assert feedback.details == {"property": "battery"}
