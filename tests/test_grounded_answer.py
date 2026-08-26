from ha_nlu.nlu.grounded_answer import TruthValue, join_german, render_state_answer
from ha_nlu.nlu.german_morphology import analyse_german_morphology


def test_unknown_evidence_never_becomes_a_negative_answer():
    answer = render_state_answer("Radio Atlas", "meldet unavailable", None)

    assert answer.truth is TruthValue.UNKNOWN
    assert not answer.speech.startswith("Nein")
    assert "nicht sicher" in answer.speech


def test_negated_true_question_uses_doch():
    answer = render_state_answer(
        "Radio Atlas", "spielt", True, negated_question=True
    )

    assert answer.truth is TruthValue.TRUE
    assert answer.speech.startswith("Doch")


def test_german_enumeration_has_a_natural_final_conjunction():
    assert join_german(["Küche", "Flur", "Büro"]) == "Küche, Flur und Büro"


def test_morphology_marks_cases_and_separable_particles():
    tokens = analyse_german_morphology("Fahre den Rollladen im Büro runter")

    rollladen = next(token for token in tokens if token.normalized == "rollladen")
    runter = next(token for token in tokens if token.normalized == "runter")
    assert rollladen.grammatical_case == "accusative"
    assert "separable_particle" in runter.roles
    assert tokens[0].lemma == "fahr"
