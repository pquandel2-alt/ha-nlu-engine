"""Home Assistant runtime bridge for calendar event mutation.

HA exposes event listing/creation as services, while event deletion and
updating are entity methods behind the Calendar websocket API.  Keeping this
small bridge separate makes that version-sensitive boundary explicit.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from .calendar_management import CalendarEventSummary


def _component(hass: Any) -> Any:
    from homeassistant.components.calendar.const import DATA_COMPONENT

    return hass.data.get(DATA_COMPONENT)


async def async_get_mutable_calendar_events(
    hass: Any,
    entity_ids: tuple[str, ...],
    start: datetime,
    end: datetime,
) -> tuple[CalendarEventSummary, ...]:
    """Fetch raw CalendarEvent objects, retaining UID for safe mutation."""
    component = _component(hass)
    if component is None:
        return ()
    result: list[CalendarEventSummary] = []
    for entity_id in entity_ids:
        entity = component.get_entity(entity_id)
        if entity is None:
            continue
        events = await entity.async_get_events(hass, start, end)
        for event in events:
            uid = getattr(event, "uid", None)
            result.append(
                CalendarEventSummary(
                    calendar_entity_id=entity_id,
                    summary=str(getattr(event, "summary", "Termin")),
                    start=getattr(event, "start").isoformat(),
                    end=getattr(event, "end").isoformat(),
                    description=getattr(event, "description", None),
                    location=getattr(event, "location", None),
                    uid=str(uid) if uid is not None else None,
                    recurrence_id=getattr(event, "recurrence_id", None),
                )
            )
    return tuple(sorted(result, key=lambda item: item.start))


def _recurrence_arguments(
    event: CalendarEventSummary, scope: str | None
) -> tuple[str | None, str | None]:
    if event.recurrence_id is None:
        return None, None
    if scope == "all":
        return None, None
    if scope == "future":
        return event.recurrence_id, "THISANDFUTURE"
    return event.recurrence_id, None


async def async_delete_calendar_event(
    hass: Any, event: CalendarEventSummary, recurrence_scope: str | None = None
) -> None:
    component = _component(hass)
    entity = component.get_entity(event.calendar_entity_id) if component is not None else None
    if entity is None or event.uid is None:
        raise ValueError("Der Kalendertermin besitzt keine löschbare Kennung")
    recurrence_id, recurrence_range = _recurrence_arguments(event, recurrence_scope)
    await entity.async_delete_event(
        event.uid,
        recurrence_id=recurrence_id,
        recurrence_range=recurrence_range,
    )


def _parse_temporal(value: str) -> date | datetime:
    return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)


async def async_reschedule_calendar_event(
    hass: Any,
    event: CalendarEventSummary,
    new_start_time: time,
    recurrence_scope: str | None = None,
    new_date: date | None = None,
) -> None:
    component = _component(hass)
    entity = component.get_entity(event.calendar_entity_id) if component is not None else None
    if entity is None or event.uid is None:
        raise ValueError("Der Kalendertermin besitzt keine änderbare Kennung")
    old_start = _parse_temporal(event.start)
    old_end = _parse_temporal(event.end)
    if not isinstance(old_start, datetime) or not isinstance(old_end, datetime):
        raise ValueError("Ganztägige Termine können nicht nur auf eine Uhrzeit verschoben werden")
    new_start = datetime.combine(new_date or old_start.date(), new_start_time, tzinfo=old_start.tzinfo)
    new_end = new_start + (old_end - old_start)
    payload: dict[str, Any] = {
        "dtstart": new_start,
        "dtend": new_end,
        "summary": event.summary,
    }
    if event.description:
        payload["description"] = event.description
    if event.location:
        payload["location"] = event.location
    recurrence_id, recurrence_range = _recurrence_arguments(event, recurrence_scope)
    await entity.async_update_event(
        event.uid,
        payload,
        recurrence_id=recurrence_id,
        recurrence_range=recurrence_range,
    )


async def async_update_calendar_event_details(
    hass: Any,
    event: CalendarEventSummary,
    *,
    new_title: str | None = None,
    new_duration_minutes: int | None = None,
    recurrence_scope: str | None = None,
) -> None:
    component = _component(hass)
    entity = component.get_entity(event.calendar_entity_id) if component is not None else None
    if entity is None or event.uid is None:
        raise ValueError("Der Kalendertermin besitzt keine änderbare Kennung")
    old_start = _parse_temporal(event.start)
    old_end = _parse_temporal(event.end)
    if new_duration_minutes is not None:
        if not isinstance(old_start, datetime) or not isinstance(old_end, datetime):
            raise ValueError("Die Dauer ganztägiger Termine kann so nicht geändert werden")
        if not 1 <= new_duration_minutes <= 7 * 24 * 60:
            raise ValueError("Die gewünschte Termindauer ist nicht gültig")
        old_end = old_start + timedelta(minutes=new_duration_minutes)
    payload: dict[str, Any] = {
        "dtstart": old_start,
        "dtend": old_end,
        "summary": new_title or event.summary,
    }
    if event.description:
        payload["description"] = event.description
    if event.location:
        payload["location"] = event.location
    recurrence_id, recurrence_range = _recurrence_arguments(event, recurrence_scope)
    await entity.async_update_event(
        event.uid,
        payload,
        recurrence_id=recurrence_id,
        recurrence_range=recurrence_range,
    )
