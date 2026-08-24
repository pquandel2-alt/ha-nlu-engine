"""Home Assistant runtime bridge for calendar event mutation.

HA exposes event listing/creation as services, while event deletion and
updating are entity methods behind the Calendar websocket API.  Keeping this
small bridge separate makes that version-sensitive boundary explicit.
"""

from __future__ import annotations

from datetime import date, datetime, time
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


async def async_delete_calendar_event(hass: Any, event: CalendarEventSummary) -> None:
    component = _component(hass)
    entity = component.get_entity(event.calendar_entity_id) if component is not None else None
    if entity is None or event.uid is None:
        raise ValueError("Der Kalendertermin besitzt keine löschbare Kennung")
    await entity.async_delete_event(event.uid, recurrence_id=event.recurrence_id)


def _parse_temporal(value: str) -> date | datetime:
    return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)


async def async_reschedule_calendar_event(
    hass: Any,
    event: CalendarEventSummary,
    new_start_time: time,
) -> None:
    component = _component(hass)
    entity = component.get_entity(event.calendar_entity_id) if component is not None else None
    if entity is None or event.uid is None:
        raise ValueError("Der Kalendertermin besitzt keine änderbare Kennung")
    old_start = _parse_temporal(event.start)
    old_end = _parse_temporal(event.end)
    if not isinstance(old_start, datetime) or not isinstance(old_end, datetime):
        raise ValueError("Ganztägige Termine können nicht nur auf eine Uhrzeit verschoben werden")
    new_start = datetime.combine(old_start.date(), new_start_time, tzinfo=old_start.tzinfo)
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
    await entity.async_update_event(
        event.uid,
        payload,
        recurrence_id=event.recurrence_id,
    )
