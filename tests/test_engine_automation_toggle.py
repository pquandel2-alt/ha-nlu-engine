"""HomeIntent V5 Teil 8/10 (Wave 11, "Automation Disable/Enable"): direct
unit tests for ``NluEngine.match_automation_disable()``/
``match_automation_enable()`` - the ``_AUTOMATION_DISABLE_RE``/
``_AUTOMATION_ENABLE_RE`` regex gates, the entity-filtered resolution, the
"never guess" refusal on an unresolved/ambiguous ``{name}``, and the two
distinct 0-match/2+-match refusal wordings vs. the single-match immediate
action. Same "direct engine-method unit tests" style
``tests/test_engine_automation_delete.py`` already established.

``automations`` is always passed in directly here (a plain tuple of
``AutomationSummary``) - this method never reads ``automations.yaml``
itself, that's ``AutomationExecutor.async_list_automations()``'s job (see
``tests/test_automation_executor.py``); ``conversation.py`` is what threads
the real, gated read and the resulting executor call into this method live
(covered by ``tests/test_conversation_automation_toggle.py``).
"""

from __future__ import annotations

from ha_nlu.automation_summary import AutomationSummary
from ha_nlu.engine import AutomationToggleMatchResult
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
KUECHE_AUTOMATION_2 = AutomationSummary(
    automation_id="a3",
    alias="Von Hand erstellte Küchen-Automation",
    referenced_entity_ids=frozenset({"light.kueche_licht"}),
)
UNRELATED_AUTOMATION = AutomationSummary(
    automation_id="a2",
    alias="Von Hand erstellte Automation",
    referenced_entity_ids=frozenset({"switch.garten_pumpe"}),
)


# --- disable -------------------------------------------------------------


def test_non_disable_sentence_is_rejected_by_the_regex_gate(engine):
    result = engine.match_automation_disable(
        "Schalte das Küchenlicht ein.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_a_single_disable_match_returns_an_immediate_result(engine):
    result = engine.match_automation_disable(
        "Deaktiviere die Automation für Küchenlicht.", ENTITIES, (KUECHE_AUTOMATION, UNRELATED_AUTOMATION)
    )
    assert isinstance(result, AutomationToggleMatchResult)
    assert result.automation == KUECHE_AUTOMATION
    assert result.enable is False
    assert result.response_text == "Automation wurde deaktiviert."


def test_no_matching_automation_refuses_disable_with_automation_none(engine):
    result = engine.match_automation_disable(
        "Deaktiviere die Automation für Küchenlicht.", ENTITIES, (UNRELATED_AUTOMATION,)
    )
    assert isinstance(result, AutomationToggleMatchResult)
    assert result.automation is None
    assert result.enable is False
    assert result.response_text == "Ich habe keine Automation gefunden, die Küchenlicht steuert."


def test_two_or_more_matches_refuse_disable_rather_than_pick_one(engine):
    result = engine.match_automation_disable(
        "Deaktiviere die Automation für Küchenlicht.",
        ENTITIES,
        (KUECHE_AUTOMATION, KUECHE_AUTOMATION_2),
    )
    assert isinstance(result, AutomationToggleMatchResult)
    assert result.automation is None
    assert result.response_text == (
        "Es gibt mehrere Automationen, die Küchenlicht steuern. "
        "Das kann ich nicht eindeutig deaktivieren."
    )


def test_unresolved_entity_name_never_guesses_disable(engine):
    result = engine.match_automation_disable(
        "Deaktiviere die Automation für Nichtvorhandenesding.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_ambiguous_entity_name_never_guesses_disable(engine):
    result = engine.match_automation_disable(
        "Deaktiviere die Automation für Bürolicht.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


# --- enable ----------------------------------------------------------------


def test_non_enable_sentence_is_rejected_by_the_regex_gate(engine):
    result = engine.match_automation_enable(
        "Schalte das Küchenlicht ein.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_a_single_enable_match_returns_an_immediate_result(engine):
    result = engine.match_automation_enable(
        "Aktiviere die Automation für Küchenlicht.", ENTITIES, (KUECHE_AUTOMATION, UNRELATED_AUTOMATION)
    )
    assert isinstance(result, AutomationToggleMatchResult)
    assert result.automation == KUECHE_AUTOMATION
    assert result.enable is True
    assert result.response_text == "Automation wurde aktiviert."


def test_no_matching_automation_refuses_enable_with_automation_none(engine):
    result = engine.match_automation_enable(
        "Aktiviere die Automation für Küchenlicht.", ENTITIES, (UNRELATED_AUTOMATION,)
    )
    assert isinstance(result, AutomationToggleMatchResult)
    assert result.automation is None
    assert result.enable is True
    assert result.response_text == "Ich habe keine Automation gefunden, die Küchenlicht steuert."


def test_two_or_more_matches_refuse_enable_rather_than_pick_one(engine):
    result = engine.match_automation_enable(
        "Aktiviere die Automation für Küchenlicht.",
        ENTITIES,
        (KUECHE_AUTOMATION, KUECHE_AUTOMATION_2),
    )
    assert isinstance(result, AutomationToggleMatchResult)
    assert result.automation is None
    assert result.response_text == (
        "Es gibt mehrere Automationen, die Küchenlicht steuern. "
        "Das kann ich nicht eindeutig aktivieren."
    )


def test_unresolved_entity_name_never_guesses_enable(engine):
    result = engine.match_automation_enable(
        "Aktiviere die Automation für Nichtvorhandenesding.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_ambiguous_entity_name_never_guesses_enable(engine):
    result = engine.match_automation_enable(
        "Aktiviere die Automation für Bürolicht.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None


# --- word-boundary safety: "deaktiviere" must not also trigger the enable
# gate (\bdeaktivier\w*\b vs. \baktivier\w*\b - no word boundary exists
# immediately before "aktivier" inside "deaktiviere") -------------------


def test_deaktiviere_does_not_also_match_the_enable_gate(engine):
    result = engine.match_automation_enable(
        "Deaktiviere die Automation für Küchenlicht.", ENTITIES, (KUECHE_AUTOMATION,)
    )
    assert result is None
