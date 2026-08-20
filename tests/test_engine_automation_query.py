"""HomeIntent V5 Teil 9/10, V5.29 "Automation Query": direct unit tests for
``NluEngine.match_automation_query()`` itself - the ``_AUTOMATION_QUERY_RE``
regex gate, the bare-listing vs. entity-filtered shapes, the "never guess"
refusal on an unresolved/ambiguous ``{name}``, and the plain vs. causal
(HassAutomationQuery vs. HassAutomationWhyQuery) response wording. Same
"direct engine-method unit tests" style ``tests/test_engine_match_automation.py``
already established for ``match_automation()``.

``automations`` is always passed in directly here (a plain tuple of
``AutomationSummary``) - this method never reads ``automations.yaml`` itself,
that's ``AutomationExecutor.async_list_automations()``'s job (see
``tests/test_automation_executor.py``); ``conversation.py`` is what threads
the real, gated read into this method live (covered by
``tests/test_conversation_automation_query.py``).
"""

from __future__ import annotations

from ha_nlu.automation_summary import AutomationSummary
from ha_nlu.engine import MatchResult
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
UNRELATED_AUTOMATION = AutomationSummary(
    automation_id="a2",
    alias="Von Hand erstellte Automation",
    referenced_entity_ids=frozenset({"switch.garten_pumpe"}),
)


def test_non_automation_sentence_is_rejected_by_the_regex_gate(engine):
    result = engine.match_automation_query(
        "Schalte das Küchenlicht ein.", ENTITIES, None, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_bare_listing_with_no_automations_at_all(engine):
    result = engine.match_automation_query("Welche Automationen gibt es?", ENTITIES, None, ())
    assert isinstance(result, MatchResult)
    assert result.plan is None  # query, never calls a service (Regel 3)
    assert result.response_text == "Es sind keine Automationen vorhanden."


def test_bare_listing_lists_every_automation(engine):
    result = engine.match_automation_query(
        "Welche Automationen gibt es?", ENTITIES, None, (KUECHE_AUTOMATION, UNRELATED_AUTOMATION)
    )
    assert result is not None
    assert "Von Hand erstellte Automation" in result.response_text


def test_entity_filtered_query_resolves_the_name_and_filters_automations(engine):
    result = engine.match_automation_query(
        "Was schaltet Küchenlicht?", ENTITIES, None, (KUECHE_AUTOMATION, UNRELATED_AUTOMATION)
    )
    assert result is not None
    assert "Küchenlicht" in result.response_text
    assert "Von Hand erstellte Automation" not in result.response_text


def test_entity_filtered_query_with_no_matching_automation(engine):
    result = engine.match_automation_query(
        "Was schaltet Küchenlicht?", ENTITIES, None, (UNRELATED_AUTOMATION,)
    )
    assert result is not None
    assert result.response_text == "Ich habe keine Automation gefunden, die Küchenlicht steuert."


def test_causal_query_uses_hedged_wording(engine):
    result = engine.match_automation_query(
        "Warum ist Küchenlicht an?", ENTITIES, None, (KUECHE_AUTOMATION,)
    )
    assert result is not None
    assert "könnte" in result.response_text


def test_unresolved_entity_name_never_guesses(engine):
    result = engine.match_automation_query(
        "Was schaltet Nichtvorhandenesding?", ENTITIES, None, (KUECHE_AUTOMATION,)
    )
    assert result is None


def test_ambiguous_entity_name_never_guesses(engine):
    result = engine.match_automation_query(
        "Was schaltet Bürolicht?", ENTITIES, None, (KUECHE_AUTOMATION,)
    )
    assert result is None
