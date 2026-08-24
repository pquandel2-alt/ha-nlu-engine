from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from ha_nlu.calendar_management import (  # noqa: E402
    CalendarManagementKind,
    flatten_calendar_response,
    parse_calendar_management,
    render_calendar_events,
)
from ha_nlu.entities import EntitySnapshot  # noqa: E402


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=ZoneInfo("Europe/Berlin"))
PRIVATE = EntitySnapshot("calendar.privat", "Privat", "calendar", "off")


def test_tomorrow_agenda_builds_one_local_day_range():
    request = parse_calendar_management(
        "Was steht morgen in meinem Kalender?", (PRIVATE,), NOW
    )
    assert request is not None
    assert request.kind is CalendarManagementKind.LIST
    assert request.start.isoformat() == "2026-08-25T00:00:00+02:00"
    assert request.end.isoformat() == "2026-08-26T00:00:00+02:00"


def test_weekend_query_uses_saturday_to_monday():
    request = parse_calendar_management(
        "Welche Termine habe ich am Wochenende?", (PRIVATE,), NOW
    )
    assert request is not None
    assert request.start.date().isoformat() == "2026-08-29"
    assert request.end.date().isoformat() == "2026-08-31"


def test_named_event_query_extracts_compound_title():
    request = parse_calendar_management(
        "Wann ist mein Zahnarzttermin?", (PRIVATE,), NOW
    )
    assert request is not None
    assert request.kind is CalendarManagementKind.FIND
    assert request.title_filter == "Zahnarzt"


def test_reschedule_without_calendar_word_is_understood():
    request = parse_calendar_management(
        "Verschiebe Zahnarzt auf 11 Uhr", (PRIVATE,), NOW
    )
    assert request is not None
    assert request.kind is CalendarManagementKind.RESCHEDULE
    assert request.title_filter == "Zahnarzt"
    assert request.new_start_time.isoformat() == "11:00:00"


def test_response_is_filtered_sorted_and_rendered():
    request = parse_calendar_management(
        "Wann ist mein Zahnarzttermin?", (PRIVATE,), NOW
    )
    assert request is not None
    events = flatten_calendar_response(
        {
            "calendar.privat": {
                "events": [
                    {
                        "summary": "Zahnarzt Kontrolle",
                        "start": "2026-08-25T10:00:00+02:00",
                        "end": "2026-08-25T11:00:00+02:00",
                    },
                    {
                        "summary": "Einkaufen",
                        "start": "2026-08-24T18:00:00+02:00",
                        "end": "2026-08-24T19:00:00+02:00",
                    },
                ]
            }
        },
        request.title_filter,
    )
    assert len(events) == 1
    assert render_calendar_events(events, request) == (
        "„Zahnarzt Kontrolle“ ist am 25.8. um 10:00 Uhr."
    )
