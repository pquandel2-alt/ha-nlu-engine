"""Automation clause boundaries come from GermanStructuralAnalysis."""

from ha_nlu.nlu.automation_sentence_split import (
    split_automation_document,
    structured_automation_condition_clauses,
)
from ha_nlu.nlu.language_frontend import analyse_language


def test_trigger_first_structure_selects_unchanged_source_spans():
    text = (
        "Wenn das Küchenfenster geöffnet wird und es nach 18 Uhr ist, "
        "schalte das Küchenlicht ein."
    )
    split = split_automation_document(analyse_language(text))

    assert split == (
        "Wenn das Küchenfenster geöffnet wird und es nach 18 Uhr ist",
        "schalte das Küchenlicht ein",
    )


def test_action_first_structure_selects_trigger_without_reparse_boundary():
    text = "Benachrichtige Philipp, wenn das Fenster offen ist."
    split = split_automation_document(analyse_language(text))

    assert split == ("wenn das Fenster offen ist", "Benachrichtige Philipp")


def test_document_split_refuses_text_without_unique_if_relation():
    assert split_automation_document(analyse_language("Schalte das Licht ein.")) is None


def test_trigger_condition_subclauses_use_structural_source_spans():
    text = (
        "Wenn das Küchenfenster geöffnet wird und es nach 18 Uhr ist, "
        "schalte das Küchenlicht ein."
    )

    assert structured_automation_condition_clauses(analyse_language(text)) == (
        "Wenn das Küchenfenster geöffnet wird",
        "es nach 18 Uhr ist",
    )
