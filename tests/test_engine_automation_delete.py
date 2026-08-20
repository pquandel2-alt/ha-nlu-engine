"""HomeIntent V5 Teil 8/10, V5.28 "Automation Deletion": direct unit tests
for ``NluEngine.match_automation_delete()`` - the ``_AUTOMATION_DELETE_RE``
regex gate, the entity-filtered resolution, the "never guess" refusal on an
unresolved/ambiguous ``{name}``, and the two distinct 0-match/2+-match
refusal wordings vs. the single-match confirmation question. Same "direct
engine-method unit tests" style ``tests/test_engine_automation_query.py``
already established for ``match_automation_query()``.

``automations`` is always passed in directly here (a plain tuple of
``AutomationSummary``) - this method never reads ``automations.yaml``
itself, that's ``AutomationExecutor.async_list_automations()``'s job (see
``tests/test_automation_executor.py``); ``conversation.py`` is what threads
the real, gated read and the resulting confirmation dialog into this method
live (covered by ``tests/test_conversation_automation_delete.py``).
"""

from __future__ import annotations

from ha_nlu.automation_summary import AutomationSummary
from ha_nlu.engine import AutomationDeletionMatchResult
from ha_nlu.entities import EntitySnapshot

KUECHE_LICHT = EntitySnapshot(
    "light.kueche_licht", "Küchenlicht", "light", "on",
    area_id="kueche", area_name="Küche",
)
BUERO_LICHT_1 = EntitySnapshot(
    "light.buero_licht_1", "Bürolicht", "light", "off",
    area_id="buero_1", area_name="Büro 1",
)
BUERO_LICHT_2 = EntitySnapshot(
    "light.buero_licht_2", "Bürolicht", "light", "off",
    area_id="buero_2", area_name="Büro 2",
)

ENTITIES = [KUECHE_LICHT, BUERO_LICHT_1, BUERO_LICHT_2]

KUECHE_AUTOMATION = AutomationSummary(
    automation_id="a1",
    alias="ha_nlu_a1",
    source_text="Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.",
    referenced_entity_ids=frozenset({"light.kueche_licht"}),
)
KUECHE_AUTOMATION_NO_SOURCE_TEXT = AutomationSummary(
    automation_id="a3",
    alias="Von Hand erstellte Küchen-Automation",
    referenced_entity_ids=frozenset({"light.kueche_licht"}),
)
UNRELATED_AUTOMATION = AutomationSummary(
    automation_id="a2",
    alias="Von Hand erstellte Automation",
    referenced_entity_ids=frozenset({"switch.garten_pumpe"}),
)


def test_non_delete_sentence_is_rejected_by_the_regex_gate(engine):
    result = engine.match_automation_delete(
        "Schalte das Küchenlicht ein.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_a_single_match_returns_a_confirmation_question_naming_the_automation(engine):
    result = engine.match_automation_delete(
        "Lösche die Automation für Küchenlicht.", ENTITIES, (KUECHE_AUTOMATION, UNRELATED_AUTOMATION)
    )
    assert isinstance(result, AutomationDeletionMatchResult)
    assert result.automation == KUECHE_AUTOMATION
    assert result.response_text == (
        'Soll die Automation "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein." '
        "gelöscht werden?"
    )


def test_a_single_match_without_source_text_falls_back_to_the_alias(engine):
    result = engine.match_automation_delete(
        "Lösche die Automation für Küchenlicht.", ENTITIES, (KUECHE_AUTOMATION_NO_SOURCE_TEXT,)
    )
    assert isinstance(result, AutomationDeletionMatchResult)
    assert result.automation == KUECHE_AUTOMATION_NO_SOURCE_TEXT
    assert result.response_text == (
        'Soll die Automation "Von Hand erstellte Küchen-Automation" gelöscht werden?'
    )


def test_entferne_wording_is_also_recognized(engine):
    result = engine.match_automation_delete(
        "Entferne die Automation für Küchenlicht.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert isinstance(result, AutomationDeletionMatchResult)
    assert result.automation == KUECHE_AUTOMATION


def test_no_matching_automation_refuses_with_automation_none(engine):
    result = engine.match_automation_delete(
        "Lösche die Automation für Küchenlicht.", ENTITIES, (UNRELATED_AUTOMATION,)
    )
    assert isinstance(result, AutomationDeletionMatchResult)
    assert result.automation is None
    assert result.response_text == "Ich habe keine Automation gefunden, die Küchenlicht steuert."


def test_two_or_more_matches_refuse_rather_than_pick_one(engine):
    result = engine.match_automation_delete(
        "Lösche die Automation für Küchenlicht.",
        ENTITIES,
        (KUECHE_AUTOMATION, KUECHE_AUTOMATION_NO_SOURCE_TEXT),
    )
    assert isinstance(result, AutomationDeletionMatchResult)
    assert result.automation is None
    assert result.response_text == (
        "Es gibt mehrere Automationen, die Küchenlicht steuern. "
        "Das kann ich nicht eindeutig löschen."
    )


def test_unresolved_entity_name_never_guesses(engine):
    result = engine.match_automation_delete(
        "Lösche die Automation für Nichtvorhandenesding.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_ambiguous_entity_name_never_guesses(engine):
    result = engine.match_automation_delete(
        "Lösche die Automation für Bürolicht.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None
