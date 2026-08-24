import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ha_nlu.calendar_management import CalendarEventSummary
from ha_nlu.calendar_runtime import async_delete_calendar_event, async_reschedule_calendar_event


EVENT = CalendarEventSummary(
    "calendar.family", "Training", "2026-08-25T18:00:00+00:00",
    "2026-08-25T19:00:00+00:00", uid="series", recurrence_id="20260825T180000Z",
)


def _hass():
    entity = SimpleNamespace(async_delete_event=AsyncMock(), async_update_event=AsyncMock())
    component = SimpleNamespace(get_entity=lambda _entity_id: entity)
    return SimpleNamespace(data={"calendar": component}), entity


def test_delete_future_uses_rfc5545_range(monkeypatch):
    import ha_nlu.calendar_runtime as runtime
    hass, entity = _hass()
    monkeypatch.setattr(runtime, "_component", lambda _hass: hass.data["calendar"])
    asyncio.run(async_delete_calendar_event(hass, EVENT, "future"))
    entity.async_delete_event.assert_awaited_once_with(
        "series", recurrence_id="20260825T180000Z", recurrence_range="THISANDFUTURE"
    )


def test_reschedule_all_omits_recurrence_instance(monkeypatch):
    import ha_nlu.calendar_runtime as runtime
    from datetime import time
    hass, entity = _hass()
    monkeypatch.setattr(runtime, "_component", lambda _hass: hass.data["calendar"])
    asyncio.run(async_reschedule_calendar_event(hass, EVENT, time(20), "all"))
    assert entity.async_update_event.await_args.kwargs == {"recurrence_id": None, "recurrence_range": None}
