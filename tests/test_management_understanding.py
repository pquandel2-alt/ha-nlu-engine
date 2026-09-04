"""Calendar and productivity share one non-first-match outcome boundary."""

from datetime import datetime, timezone

from ha_nlu.calendar_management import CalendarManagementRequest
from ha_nlu.entities import EntitySnapshot
from ha_nlu.management_understanding import understand_management
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.understanding import UnderstandingKind
from ha_nlu.productivity import TodoRequest


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
CALENDAR = EntitySnapshot("calendar.familie", "Familienkalender", "calendar", "on")
TODO = EntitySnapshot("todo.einkauf", "Einkaufsliste", "todo", "0")


def _understand(text: str):
    entities = [CALENDAR, TODO]
    return understand_management(
        analyse_language(text, entities), entities, (CALENDAR,), NOW
    )


def test_calendar_query_has_typed_query_outcome():
    outcome = _understand("Was steht morgen im Kalender?")

    assert outcome is not None
    assert outcome.kind is UnderstandingKind.QUERY
    assert isinstance(outcome.payload, CalendarManagementRequest)
    assert outcome.route == "management:calendar"


def test_todo_mutation_has_typed_management_outcome():
    outcome = _understand("Füge Milch zur Einkaufsliste hinzu")

    assert outcome is not None
    assert outcome.kind is UnderstandingKind.MANAGEMENT
    assert isinstance(outcome.payload, TodoRequest)
    assert outcome.route == "management:productivity"


def test_explicit_list_noun_resolves_cross_parser_delete_overlap():
    outcome = _understand("Alle erledigten Einträge aus der Einkaufsliste löschen")

    assert outcome is not None
    assert outcome.kind is UnderstandingKind.MANAGEMENT
    assert isinstance(outcome.payload, TodoRequest)


def test_conflicting_calendar_and_list_cues_never_use_first_match():
    outcome = _understand(
        "Lösche den Eintrag Termin aus der Einkaufsliste im Kalender"
    )

    assert outcome is not None
    assert outcome.kind is UnderstandingKind.AMBIGUOUS
    assert outcome.payload is None
