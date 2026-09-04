"""Canonical understanding boundary for calendar and productivity language."""

from __future__ import annotations

import re
from datetime import datetime

from .calendar_management import (
    CalendarManagementKind,
    CalendarManagementRequest,
    parse_calendar_management,
)
from .entities import EntitySnapshot
from .nlu.language_frontend import LanguageDocument
from .nlu.understanding import (
    UnderstandingAuthority,
    UnderstandingKind,
    UnderstandingOutcome,
)
from .productivity import (
    ProductivityRequest,
    TimerOperation,
    TimerRequest,
    TodoOperation,
    parse_productivity_request,
)


ManagementPayload = ProductivityRequest | CalendarManagementRequest

_PRODUCTIVITY_CUE_RE = re.compile(
    r"\b(?:\w*listen?|eintraege?|einträge|todos?|to-do|\w*timer|countdown)\b",
    re.IGNORECASE,
)
_CALENDAR_CUE_RE = re.compile(r"\b(?:kalender|\w*termine?)\b", re.IGNORECASE)


def _is_query(payload: ManagementPayload) -> bool:
    if isinstance(payload, CalendarManagementRequest):
        return payload.kind in {
            CalendarManagementKind.LIST,
            CalendarManagementKind.FIND,
            CalendarManagementKind.AVAILABILITY,
        }
    if isinstance(payload, TimerRequest):
        return payload.operation is TimerOperation.STATUS
    return payload.operation is TodoOperation.LIST


def understand_management(
    document: LanguageDocument,
    productivity_entities: list[EntitySnapshot],
    calendars: tuple[EntitySnapshot, ...],
    now: datetime,
) -> UnderstandingOutcome[ManagementPayload] | None:
    """Interpret bounded management language without first-match guessing."""
    productivity = parse_productivity_request(
        document.source_text,
        productivity_entities,
        now,
        document,
    )
    calendar = parse_calendar_management(
        document.source_text,
        calendars,
        now,
        document,
    )
    matches = tuple(item for item in (productivity, calendar) if item is not None)
    if not matches:
        return None
    if len(matches) != 1:
        explicit_productivity = _PRODUCTIVITY_CUE_RE.search(document.source_text) is not None
        explicit_calendar = _CALENDAR_CUE_RE.search(document.source_text) is not None
        if explicit_productivity and not explicit_calendar:
            matches = (productivity,) if productivity is not None else ()
        elif explicit_calendar and not explicit_productivity:
            matches = (calendar,) if calendar is not None else ()
    if len(matches) != 1:
        return UnderstandingOutcome(
            kind=UnderstandingKind.AMBIGUOUS,
            source_text=document.source_text,
            normalized_text=document.normalized_text,
            speech_act=document.utterance.speech_act,
            speech="Meinst du den Kalender oder eine Liste beziehungsweise einen Timer?",
            route="management:ambiguous",
            authority=UnderstandingAuthority.V7_MIGRATED,
        )
    payload = matches[0]
    return UnderstandingOutcome(
        kind=(UnderstandingKind.QUERY if _is_query(payload) else UnderstandingKind.MANAGEMENT),
        source_text=document.source_text,
        normalized_text=document.normalized_text,
        speech_act=document.utterance.speech_act,
        payload=payload,
        route=(
            "management:calendar"
            if isinstance(payload, CalendarManagementRequest)
            else "management:productivity"
        ),
        authority=UnderstandingAuthority.V7_MIGRATED,
    )
