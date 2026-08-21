"""Automation management vocabulary and deterministic selection."""

from __future__ import annotations

from datetime import datetime, timezone

from ha_nlu.automation_management import (
    AutomationManagementKind,
    parse_automation_management,
    select_automation_management,
)
from ha_nlu.automation_summary import AutomationSummary
from ha_nlu.entities import EntitySnapshot

ROLLLADE = EntitySnapshot(
    "cover.buero_rollladen", "Büro Rollladen", "cover", "closed"
)
SCHEDULED = AutomationSummary(
    "scheduled",
    "Rolllade später",
    created_by="homeintent",
    referenced_entity_ids=frozenset({ROLLLADE.entity_id}),
    scheduled_for="2026-08-22T08:00:00+00:00",
    once=True,
)
MANUAL = AutomationSummary("manual", "Von Hand")
PERSISTENT = AutomationSummary(
    "persistent",
    "Küche dauerhaft",
    created_by="homeintent",
    referenced_entity_ids=frozenset({ROLLLADE.entity_id}),
)


def test_management_phrases_are_classified():
    assert parse_automation_management(
        "Zeige nur HomeIntent-Automationen"
    ).kind is AutomationManagementKind.LIST_HOMEINTENT
    assert parse_automation_management(
        "Welche einmaligen Aufträge sind noch geplant?"
    ).kind is AutomationManagementKind.LIST_SCHEDULED
    assert parse_automation_management(
        "Wann wird Büro Rollladen gefahren?"
    ).kind is AutomationManagementKind.WHEN
    move = parse_automation_management(
        "Verschiebe den Auftrag für Büro Rollladen auf 20:15 Uhr"
    )
    assert (move.kind, move.hour, move.minute) == (
        AutomationManagementKind.RESCHEDULE,
        20,
        15,
    )
    assert parse_automation_management(
        "Lösche alle abgelaufenen HomeIntent-Automationen"
    ).kind is AutomationManagementKind.CLEAN_EXPIRED
    repeat = parse_automation_management("Wiederhole die Automation nur dreimal")
    assert (repeat.kind, repeat.max_runs) == (
        AutomationManagementKind.SET_MAX_RUNS,
        3,
    )


def test_repeat_management_uses_persistent_homeintent_automations_only():
    request = parse_automation_management(
        "Wiederhole die Automation für Büro Rollladen nur 4 mal"
    )
    selection = select_automation_management(
        request,
        [ROLLLADE],
        (SCHEDULED, PERSISTENT, MANUAL),
    )
    assert selection.automations == (PERSISTENT,)


def test_homeintent_and_scheduled_filters_never_include_manual_automations():
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    home_request = parse_automation_management("Zeige nur HomeIntent-Automationen")
    scheduled_request = parse_automation_management(
        "Welche einmaligen Aufträge sind noch geplant?"
    )
    assert select_automation_management(
        home_request, [ROLLLADE], (SCHEDULED, MANUAL), now
    ).automations == (SCHEDULED,)
    assert select_automation_management(
        scheduled_request, [ROLLLADE], (SCHEDULED, MANUAL), now
    ).automations == (SCHEDULED,)


def test_when_query_resolves_the_entity_before_filtering():
    request = parse_automation_management("Wann wird Büro Rollladen gefahren?")
    selection = select_automation_management(
        request,
        [ROLLLADE],
        (SCHEDULED, MANUAL),
        datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
    )
    assert selection.entity == ROLLLADE
    assert selection.automations == (SCHEDULED,)
