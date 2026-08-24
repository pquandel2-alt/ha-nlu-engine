"""Deterministic calendar queries and capability-safe mutation requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum, auto
from typing import Any, Mapping

from .calendar_event import select_calendar
from .entities import EntitySnapshot, normalize_for_compare


class CalendarManagementKind(Enum):
    LIST = auto()
    FIND = auto()
    DELETE = auto()
    RESCHEDULE = auto()
    AVAILABILITY = auto()
    UPDATE = auto()


@dataclass(frozen=True)
class CalendarManagementRequest:
    kind: CalendarManagementKind
    start: datetime
    end: datetime
    title_filter: str | None = None
    calendar_entity_ids: tuple[str, ...] = ()
    new_start_time: time | None = None
    new_date: date | None = None
    new_title: str | None = None
    new_duration_minutes: int | None = None


@dataclass(frozen=True)
class CalendarEventSummary:
    calendar_entity_id: str
    summary: str
    start: str
    end: str
    description: str | None = None
    location: str | None = None
    uid: str | None = None
    recurrence_id: str | None = None


_CALENDAR_CUE_RE = re.compile(r"\b(?:kalender|\w*termin\w*)\b", re.I)
_LIST_RE = re.compile(
    r"\b(?:was\s+(?:steht|ist)|welche\s+termine|was\s+habe\s+ich|"
    r"zeig\w*\s+(?:mir\s+)?(?:meine\s+)?termine|wann\s+ist)\b",
    re.I,
)
_DELETE_RE = re.compile(r"\b(?:lösch\w*|loesch\w*|entfern\w*|sag\w*\s+.*\bab)\b", re.I)
_RESCHEDULE_RE = re.compile(r"\b(?:verschieb\w*|verleg\w*)\b", re.I)
_WEEKEND_RE = re.compile(r"\b(?:am|dieses|kommendes|nächstes|naechstes)?\s*wochenende\b", re.I)
_WEEK_RE = re.compile(r"\b(?:diese|kommende|nächste|naechste)\s+woche\b", re.I)
_TITLE_RE = re.compile(
    r"\bwann\s+ist\s+(?:mein(?:e|en|er|es)?\s+)?(.+?)(?:termin)?\s*[?!.,]*$",
    re.I,
)
_NEW_TIME_RE = re.compile(r"\bauf\s+(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?\b", re.I)
_AVAILABILITY_RE = re.compile(
    r"\b(?:habe|hab)\s+ich\b.*\b(?:zeit|frei)\b|\bbin\s+ich\b.*\bfrei\b",
    re.I,
)
_TIME_WINDOW_RE = re.compile(
    r"\b(?:von|zwischen)\s+(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?\s+"
    r"(?:bis|und)\s+(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?\b",
    re.I,
)
_RENAME_RE = re.compile(
    r"\bbenenn\w*\s+(?:den\s+)?termin\s+(?P<old>.+?)\s+(?:in|zu)\s+(?P<new>.+?)\s+um\b",
    re.I,
)
_CHANGE_DURATION_RE = re.compile(
    r"\b(?:aender\w*|änder\w*)\s+(?:die\s+)?dauer\s+(?:vom|von dem)\s+termin\s+"
    r"(?P<title>.+?)\s+auf\s+(?P<count>\d+)\s*(?P<unit>minuten?|stunden?)\b",
    re.I,
)
_TARGET_DATE_RE = re.compile(
    r"\bauf\s+(?P<date>heute|morgen|übermorgen|uebermorgen|am\s+\d{1,2}\.\d{1,2}\.(?:\d{2,4})?)\b",
    re.I,
)
_MOVE_TITLE_RE = re.compile(
    r"\b(?:verschieb\w*|verleg\w*)\s+(?:den\s+)?(?:kalender)?termin\s+(.+?)\s+auf\b",
    re.I,
)
_ANY_NEW_TIME_RE = re.compile(r"\b(?:auf|um)\s+(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?\b", re.I)


def _day_range(value: date, now: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(value, time.min, tzinfo=now.tzinfo)
    return start, start + timedelta(days=1)


def _date_from_text(text: str, now: datetime) -> date | None:
    from .calendar_event import parse_calendar_date

    return parse_calendar_date(text, now)


def _range_from_text(text: str, now: datetime) -> tuple[datetime, datetime]:
    if _WEEKEND_RE.search(text):
        days_to_saturday = (5 - now.date().weekday()) % 7
        saturday = now.date() + timedelta(days=days_to_saturday)
        start = datetime.combine(saturday, time.min, tzinfo=now.tzinfo)
        return start, start + timedelta(days=2)
    if _WEEK_RE.search(text):
        start_date = now.date()
        end_date = start_date + timedelta(days=7 - start_date.weekday())
        return (
            datetime.combine(start_date, time.min, tzinfo=now.tzinfo),
            datetime.combine(end_date, time.min, tzinfo=now.tzinfo),
        )
    requested_date = _date_from_text(text, now)
    if requested_date is not None:
        return _day_range(requested_date, now)
    return now, now + timedelta(days=366)


def _title_filter(text: str) -> str | None:
    match = _TITLE_RE.search(text.strip())
    if match is None:
        return None
    title = re.sub(r"\btermin\b$", "", match.group(1), flags=re.I).strip(" .,!?:;")
    return title or None


def _mutation_title_filter(text: str) -> str | None:
    value = _DELETE_RE.sub(" ", text, count=1)
    value = _RESCHEDULE_RE.sub(" ", value, count=1)
    value = _NEW_TIME_RE.sub(" ", value)
    value = re.sub(
        r"\b(?:den|die|das|meinen?|meine|kalender|termin|heute|morgen|übermorgen|uebermorgen)\b",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(r"\b(?:am|um|auf)\s+\d{1,2}(?::\d{2})?\s*(?:uhr)?\b", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" .,!?:;")
    return value or None


def parse_calendar_management(
    text: str,
    calendars: tuple[EntitySnapshot, ...],
    now: datetime,
) -> CalendarManagementRequest | None:
    """Parse bounded calendar management language without stealing device commands."""
    if re.search(r"\b(?:auftrag|automation)\b", text, re.I):
        return None
    rename_match = _RENAME_RE.search(text)
    duration_match = _CHANGE_DURATION_RE.search(text)
    has_mutation = (
        _DELETE_RE.search(text) is not None
        or _RESCHEDULE_RE.search(text) is not None
        or rename_match is not None
        or duration_match is not None
    )
    availability = _AVAILABILITY_RE.search(text) is not None
    if _CALENDAR_CUE_RE.search(text) is None and not has_mutation and not availability:
        return None
    kind: CalendarManagementKind | None = None
    if availability:
        kind = CalendarManagementKind.AVAILABILITY
    elif rename_match is not None or duration_match is not None:
        kind = CalendarManagementKind.UPDATE
    elif _DELETE_RE.search(text):
        kind = CalendarManagementKind.DELETE
    elif _RESCHEDULE_RE.search(text):
        kind = CalendarManagementKind.RESCHEDULE
    elif _LIST_RE.search(text):
        kind = CalendarManagementKind.FIND if re.search(r"\bwann\s+ist\b", text, re.I) else CalendarManagementKind.LIST
    if kind is None:
        return None

    selected = select_calendar(text, calendars)
    calendar_ids = tuple(item.entity_id for item in selected) or tuple(
        item.entity_id for item in calendars
    )
    start, end = _range_from_text(text, now)
    target_date_match = _TARGET_DATE_RE.search(text) if kind is CalendarManagementKind.RESCHEDULE else None
    new_date = _date_from_text(target_date_match.group("date"), now) if target_date_match else None
    if new_date is not None:
        # The date after "auf" is the destination, not a lookup constraint.
        start, end = now, now + timedelta(days=366)
    if kind is CalendarManagementKind.AVAILABILITY:
        window = _TIME_WINDOW_RE.search(text)
        if window is not None:
            start_hour, start_minute = int(window.group(1)), int(window.group(2) or 0)
            end_hour, end_minute = int(window.group(3)), int(window.group(4) or 0)
            if 0 <= start_hour <= 23 and 0 <= end_hour <= 23 and start_minute < 60 and end_minute < 60:
                requested_date = _date_from_text(text, now) or now.date()
                start = datetime.combine(requested_date, time(start_hour, start_minute), tzinfo=now.tzinfo)
                end = datetime.combine(requested_date, time(end_hour, end_minute), tzinfo=now.tzinfo)
    new_start: time | None = None
    if kind is CalendarManagementKind.RESCHEDULE:
        match = _NEW_TIME_RE.search(text) or _ANY_NEW_TIME_RE.search(text)
        if match is not None:
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                new_start = time(hour, minute)
    move_match = _MOVE_TITLE_RE.search(text)
    if rename_match is not None:
        title_filter = rename_match.group("old").strip()
    elif duration_match is not None:
        title_filter = duration_match.group("title").strip()
    elif kind in {CalendarManagementKind.DELETE, CalendarManagementKind.RESCHEDULE}:
        title_filter = (
            move_match.group(1).strip()
            if move_match is not None
            else _mutation_title_filter(text)
        )
    else:
        title_filter = _title_filter(text)
    return CalendarManagementRequest(
        kind=kind,
        start=start,
        end=end,
        title_filter=title_filter,
        calendar_entity_ids=calendar_ids,
        new_start_time=new_start,
        new_date=new_date,
        new_title=rename_match.group("new").strip(" .!?;") if rename_match else None,
        new_duration_minutes=(
            int(duration_match.group("count"))
            * (60 if duration_match.group("unit").casefold().startswith("st") else 1)
            if duration_match else None
        ),
    )


def flatten_calendar_response(
    response: Mapping[str, Any] | None,
    title_filter: str | None = None,
) -> tuple[CalendarEventSummary, ...]:
    """Normalize HA's calendar-keyed service response and apply title search."""
    wanted = normalize_for_compare(title_filter) if title_filter else None
    result: list[CalendarEventSummary] = []
    for calendar_id, payload in (response or {}).items():
        if not isinstance(payload, Mapping):
            continue
        events = payload.get("events", ())
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, Mapping):
                continue
            summary = str(event.get("summary") or "Termin")
            if wanted and wanted not in normalize_for_compare(summary):
                continue
            start, end = event.get("start"), event.get("end")
            if not isinstance(start, str) or not isinstance(end, str):
                continue
            result.append(
                CalendarEventSummary(
                    calendar_entity_id=str(calendar_id),
                    summary=summary,
                    start=start,
                    end=end,
                    description=event.get("description"),
                    location=event.get("location"),
                    uid=event.get("uid"),
                    recurrence_id=event.get("recurrence_id"),
                )
            )
    return tuple(sorted(result, key=lambda item: item.start))


def _spoken_start(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            return value
        return f"am {parsed_date.day}.{parsed_date.month}."
    return f"am {parsed.day}.{parsed.month}. um {parsed.strftime('%H:%M')} Uhr"


def render_calendar_events(
    events: tuple[CalendarEventSummary, ...],
    request: CalendarManagementRequest,
) -> str:
    if request.kind is CalendarManagementKind.AVAILABILITY:
        if not events:
            return (
                f"Ja, zwischen {request.start.strftime('%H:%M')} und "
                f"{request.end.strftime('%H:%M')} Uhr ist kein Termin eingetragen."
            )
        names = ", ".join(f"„{event.summary}“" for event in events[:3])
        return f"Nein, in diesem Zeitraum liegt {names}."
    if not events:
        if request.title_filter:
            return f"Ich finde keinen Termin mit „{request.title_filter}“ im abgefragten Zeitraum."
        return "Im abgefragten Zeitraum stehen keine Termine im Kalender."
    if request.kind is CalendarManagementKind.FIND and len(events) == 1:
        event = events[0]
        return f"„{event.summary}“ ist {_spoken_start(event.start)}."
    rendered = [f"„{event.summary}“ {_spoken_start(event.start)}" for event in events[:8]]
    suffix = "" if len(events) <= 8 else f" Außerdem gibt es {len(events) - 8} weitere Termine."
    return f"Ich habe {len(events)} Termin{'e' if len(events) != 1 else ''} gefunden: " + "; ".join(rendered) + "." + suffix
