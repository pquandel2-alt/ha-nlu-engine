from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub

_ha_stub.install()

from ha_nlu.agent_event import AgentEvent, AgentEventState, AgentMode, StoredServicePlan  # noqa: E402
from ha_nlu.agent_event_store import AgentEventStore  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


def _event() -> AgentEvent:
    now = datetime.now(timezone.utc).isoformat()
    return AgentEvent(
        event_id="a" * 32,
        rule_id="rule-1",
        dedupe_key="rule-1:sensor.test",
        title="Sensorwert",
        message="Der Grenzwert wurde erreicht.",
        mode=AgentMode.ASK,
        state=AgentEventState.NOTIFIED,
        created_at=now,
        updated_at=now,
        expires_at=now,
        proposed_action=StoredServicePlan(
            "homeassistant", "turn_off", ("switch.test",), {}
        ),
        delivered_channels=("push", "tts"),
        notification_device_ids=("phone-device",),
    )


def test_agent_event_round_trip_preserves_action_and_lifecycle():
    event = _event()
    restored = AgentEvent.from_dict(event.to_dict())
    assert restored == event
    assert restored.proposed_action is not None
    assert restored.proposed_action.to_plan().entity_id == "switch.test"


def test_agent_event_store_persists_atomically(tmp_path):
    hass = HomeAssistant()
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    store = AgentEventStore(hass)
    event = _event()

    async def scenario() -> None:
        await store.async_save(event)
        assert await store.async_load_all() == {event.event_id: event}
        await store.async_delete(event.event_id)
        assert await store.async_load_all() == {}

    asyncio.run(scenario())
