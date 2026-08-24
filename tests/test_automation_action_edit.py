from __future__ import annotations

from ha_nlu.automation_action_edit import (
    homeintent_candidates,
    is_action_edit_request,
    select_candidate_reply,
)
from ha_nlu.automation_summary import AutomationSummary


FIRST = AutomationSummary(
    "one", "Fenster öffnet Küchenlicht", created_by="homeintent"
)
SECOND = AutomationSummary(
    "two", "Abendliche Rollladen", created_by="homeintent"
)
MANUAL = AutomationSummary("manual", "Handarbeit")


def test_only_explicit_action_edit_language_opens_the_dialog():
    assert is_action_edit_request("Ändere nur die Aktion, behalte den Auslöser")
    assert is_action_edit_request("Ersetze bei der Automation nur die Aktion")
    assert not is_action_edit_request("Ändere die Temperatur auf 22 Grad")


def test_candidates_never_include_non_homeintent_automations():
    candidates = homeintent_candidates(
        (FIRST, SECOND, MANUAL), "Ändere nur die Aktion"
    )
    assert candidates == (FIRST, SECOND)
    assert select_candidate_reply("Fenster öffnet Küchenlicht", candidates) == FIRST
