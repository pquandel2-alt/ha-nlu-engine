from datetime import datetime, timezone

from ha_nlu.calendar_management import (
    CalendarEventSummary,
    CalendarManagementKind,
    parse_calendar_management,
    render_calendar_events,
)
from ha_nlu.entities import EntitySnapshot


CALENDAR = EntitySnapshot("calendar.personal", "Privat", "calendar", "on")
NOW = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


def test_availability_understands_date_and_time_window():
    request = parse_calendar_management(
        "Habe ich morgen zwischen 14 und 16 Uhr Zeit?", (CALENDAR,), NOW
    )
    assert request is not None
    assert request.kind is CalendarManagementKind.AVAILABILITY
    assert request.start.day == 25 and request.start.hour == 14
    assert request.end.hour == 16


def test_availability_response_names_conflict():
    request = parse_calendar_management(
        "Bin ich morgen von 14 bis 16 Uhr frei?", (CALENDAR,), NOW
    )
    event = CalendarEventSummary(
        CALENDAR.entity_id, "Arzt", "2026-08-25T14:30:00+00:00", "2026-08-25T15:00:00+00:00"
    )
    assert "Arzt" in render_calendar_events((event,), request)
