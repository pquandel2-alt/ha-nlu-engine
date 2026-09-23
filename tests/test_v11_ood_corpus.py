from pathlib import Path

from homeintent.learning_intent import LearningOperation, interpret_learning_request


CORPUS = Path(__file__).parent / "eval" / "v11_ood_cases.txt"


def test_v11_ood_corpus_has_200_handwritten_cases_and_required_categories():
    rows = [
        line.split("|", 2)
        for line in CORPUS.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(rows) >= 200
    categories = {row[0] for row in rows}
    assert {
        "learning_feedback", "preference_learning", "habit_suggestions",
        "prediction_queries", "thermal_goals", "confidence", "explainability",
        "forget_model", "multi_user", "anomalies", "reliability",
        "effect_latency", "insufficient_data", "model_health", "opt_in_out",
        "colloquial_german", "stt_like", "ambiguous_learning", "unsafe_inference",
        "provenance", "habit_rejection", "temporal_prediction", "energy_duration",
        "battery_prediction",
    } <= categories
    for _category, expected, utterance in rows:
        request = interpret_learning_request(utterance)
        if expected == "none":
            assert request is None
        else:
            assert request is not None
            assert request.operation is LearningOperation(expected)
