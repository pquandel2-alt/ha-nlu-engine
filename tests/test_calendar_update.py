from datetime import datetime, timezone

from ha_nlu.calendar_management import CalendarManagementKind, parse_calendar_management
from ha_nlu.entities import EntitySnapshot


CALENDAR = EntitySnapshot("calendar.family", "Familie", "calendar", "on")
NOW = datetime(2026, 8, 24, 9, tzinfo=timezone.utc)


def test_rename_event_keeps_old_and_new_title_separate():
    request = parse_calendar_management(
        "Benenne den Termin Zahnarzt in Kontrolltermin um", (CALENDAR,), NOW
    )
    assert request is not None and request.kind is CalendarManagementKind.UPDATE
    assert request.title_filter == "Zahnarzt"
    assert request.new_title == "Kontrolltermin"


def test_change_event_duration_parses_hours():
    request = parse_calendar_management(
        "Ändere die Dauer vom Termin Training auf 2 Stunden", (CALENDAR,), NOW
    )
    assert request is not None and request.kind is CalendarManagementKind.UPDATE
    assert request.title_filter == "Training"
    assert request.new_duration_minutes == 120


def test_move_event_to_new_date_and_time_does_not_use_target_as_lookup_day():
    request = parse_calendar_management(
        "Verschiebe den Termin Zahnarzt auf morgen um 11 Uhr", (CALENDAR,), NOW
    )
    assert request is not None and request.kind is CalendarManagementKind.RESCHEDULE
    assert request.title_filter == "Zahnarzt"
    assert request.new_date.isoformat() == "2026-08-25"
    assert request.new_start_time.hour == 11
    assert (request.end - request.start).days == 366
