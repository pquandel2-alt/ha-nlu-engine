from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from ha_nlu.calendar_event import (
    CalendarEventDraft,
    build_calendar_event_service_call,
    calendar_event_question,
    render_calendar_event_preview,
    start_calendar_event_draft,
    update_calendar_event_draft,
    writable_calendars,
)
from ha_nlu.entities import EntitySnapshot


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=ZoneInfo("Europe/Berlin"))
PRIVATE = EntitySnapshot(
    "calendar.privat", "Privat", "calendar", "off",
    aliases=("Mein Kalender",), capabilities=frozenset({"CREATE_EVENT"}),
)
FAMILY = EntitySnapshot(
    "calendar.familie", "Familie", "calendar", "off",
    capabilities=frozenset({"CREATE_EVENT"}),
)
READ_ONLY = EntitySnapshot("calendar.feiertage", "Feiertage", "calendar", "off")


@pytest.mark.parametrize(
    ("sentence", "title", "day", "start", "duration", "end", "all_day"),
    [
        (
            "Trag nächsten Dienstag um 10 Uhr für eine Stunde Zahnarzt ein",
            "Zahnarzt", date(2026, 8, 25), time(10), 60, None, False,
        ),
        (
            "Erstelle am 25. August um 18 Uhr bis 20 Uhr den Termin Geburtstag",
            "Geburtstag", date(2026, 8, 25), time(18), None, time(20), False,
        ),
        (
            "Schreibe Urlaub morgen ganztägig in meinen Kalender ein",
            "Urlaub", date(2026, 8, 23), None, None, None, True,
        ),
        (
            "Kannst du morgen von 10 Uhr bis 11 Uhr einen Termin mit dem Titel Zahnarzt erstellen?",
            "Zahnarzt", date(2026, 8, 23), time(10), None, time(11), False,
        ),
        (
            "Trag in zwei Tagen um halb acht für eine Stunde Zahnarzt ein",
            "Zahnarzt", date(2026, 8, 24), time(7, 30), 60, None, False,
        ),
        (
            "Schreib nächsten Samstag viertel vor neun für 30 Minuten Sport ein",
            "Sport", date(2026, 8, 29), time(8, 45), 30, None, False,
        ),
        (
            "Trag Dienstag um zehn Uhr für eine halbe Stunde Physiotherapie ein",
            "Physiotherapie", date(2026, 8, 25), time(10), 30, None, False,
        ),
    ],
)
def test_complete_calendar_phrases_are_composed_from_independent_parts(
    sentence, title, day, start, duration, end, all_day
):
    draft = start_calendar_event_draft(sentence, (PRIVATE,), NOW)
    assert draft == CalendarEventDraft(
        title=title,
        event_date=day,
        start_time=start,
        end_time=end,
        duration_minutes=duration,
        all_day=all_day,
        calendar_entity_id=PRIVATE.entity_id,
    )


def test_partial_draft_asks_only_for_the_next_missing_required_field():
    calendars = (PRIVATE,)
    draft = start_calendar_event_draft("Trag einen Termin ein", calendars, NOW)
    assert calendar_event_question(draft, calendars) == "Wie soll der Termin heißen?"

    draft = update_calendar_event_draft("Zahnarzt", draft, calendars, NOW).draft
    assert calendar_event_question(draft, calendars) == "An welchem Datum findet der Termin statt?"
    draft = update_calendar_event_draft("nächsten Dienstag", draft, calendars, NOW).draft
    assert calendar_event_question(draft, calendars).startswith("Um wie viel Uhr")
    draft = update_calendar_event_draft("10 Uhr", draft, calendars, NOW).draft
    assert calendar_event_question(draft, calendars) == "Wann endet der Termin oder wie lange dauert er?"
    draft = update_calendar_event_draft("eine Stunde", draft, calendars, NOW).draft
    assert calendar_event_question(draft, calendars) is None


def test_multiple_calendars_are_never_guessed_and_named_selection_is_resolved():
    calendars = (PRIVATE, FAMILY)
    draft = start_calendar_event_draft(
        "Trag morgen um 10 Uhr für eine Stunde Zahnarzt ein", calendars, NOW
    )
    question = calendar_event_question(draft, calendars)
    assert question is not None and "Privat" in question and "Familie" in question
    update = update_calendar_event_draft("In Familie", draft, calendars, NOW)
    assert update.draft.calendar_entity_id == FAMILY.entity_id


def test_calendar_name_must_be_a_real_name_reference_not_part_of_the_title():
    calendars = (PRIVATE, FAMILY)
    draft = start_calendar_event_draft(
        "Trag morgen um 10 Uhr für eine Stunde Familienberatung ein", calendars, NOW
    )
    assert draft.calendar_entity_id is None
    explicit = update_calendar_event_draft("In den Familienkalender", draft, calendars, NOW)
    assert explicit.draft.calendar_entity_id == FAMILY.entity_id


def test_read_only_calendars_are_excluded():
    assert writable_calendars([PRIVATE, READ_ONLY]) == (PRIVATE,)


def test_preview_and_service_call_use_local_time_and_exclusive_all_day_end():
    timed = CalendarEventDraft(
        "Zahnarzt", date(2026, 8, 25), time(10), duration_minutes=60,
        calendar_entity_id=PRIVATE.entity_id,
    )
    assert "10:00 bis 11:00 Uhr" in render_calendar_event_preview(timed, (PRIVATE,))
    call = build_calendar_event_service_call(timed, (PRIVATE,), NOW)
    assert call.entity_id == PRIVATE.entity_id
    assert call.data == {
        "summary": "Zahnarzt",
        "start_date_time": "2026-08-25T10:00:00+02:00",
        "end_date_time": "2026-08-25T11:00:00+02:00",
    }

    all_day = CalendarEventDraft(
        "Urlaub", date(2026, 8, 25), all_day=True,
        calendar_entity_id=PRIVATE.entity_id,
    )
    assert build_calendar_event_service_call(all_day, (PRIVATE,), NOW).data == {
        "summary": "Urlaub",
        "start_date": "2026-08-25",
        "end_date": "2026-08-26",
    }


def test_invalid_or_past_times_are_rejected_instead_of_guessed():
    past = CalendarEventDraft(
        "Vergangen", NOW.date(), time(10), duration_minutes=60,
        calendar_entity_id=PRIVATE.entity_id,
    )
    with pytest.raises(ValueError, match="Vergangenheit"):
        build_calendar_event_service_call(past, (PRIVATE,), NOW)

    backwards = CalendarEventDraft(
        "Unklar", date(2026, 8, 25), time(20), end_time=time(19),
        calendar_entity_id=PRIVATE.entity_id,
    )
    with pytest.raises(ValueError, match="Endzeit"):
        build_calendar_event_service_call(backwards, (PRIVATE,), NOW)


def test_ambiguous_dst_clock_time_is_rejected():
    ambiguous = CalendarEventDraft(
        "Zeitumstellung", date(2026, 10, 25), time(2, 30), duration_minutes=30,
        calendar_entity_id=PRIVATE.entity_id,
    )
    with pytest.raises(ValueError, match="nicht eindeutig"):
        build_calendar_event_service_call(ambiguous, (PRIVATE,), NOW)
