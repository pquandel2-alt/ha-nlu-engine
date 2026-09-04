from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.memory import MemoryKind, MemoryStore  # noqa: E402
from ha_nlu.house_graph import FactProvenance  # noqa: E402
from ha_nlu.situation import (  # noqa: E402
    EventQuality,
    EventType,
    NormalizedEvent,
    RoutineStatistics,
)
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


LAMP = EntitySnapshot(
    "light.floor", "Stehlampe", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)


def test_preference_is_only_persisted_after_bound_confirmation(monkeypatch, tmp_path):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    entity._runtime_data.memory = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda *_: [LAMP]
    )

    async def turn(text: str, user_id: str = "owner"):
        return await entity._async_handle_message(
            ConversationInput(
                text=text,
                conversation_id="memory-conversation",
                context=SimpleNamespace(user_id=user_id),
            ),
            chat_log=None,
        )

    first = asyncio.run(
        turn("Merk dir, dass ich beim Fernsehen nur die Stehlampe auf 30 Prozent möchte.")
    )
    before = asyncio.run(entity._runtime_data.memory.async_list())
    wrong_user = asyncio.run(turn("Ja", "guest"))
    after_wrong_user = asyncio.run(entity._runtime_data.memory.async_list())
    confirmed = asyncio.run(turn("Ja"))
    stored = asyncio.run(entity._runtime_data.memory.async_list())

    assert "dauerhaft" in first.response.speech
    assert before == () and after_wrong_user == ()
    assert "anderen Benutzer" in wrong_user.response.speech
    assert confirmed.response.speech.startswith("Gespeichert")
    assert len(stored) == 1 and stored[0].kind is MemoryKind.PREFERENCE
    assert stored[0].content["entity_id"] == "light.floor"
    entity.hass.services.async_call.assert_not_awaited()


def test_complete_new_command_replaces_memory_confirmation(monkeypatch, tmp_path):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    entity._runtime_data.memory = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: [LAMP])

    async def scenario():
        context = SimpleNamespace(user_id="owner")
        await entity._async_handle_message(
            ConversationInput(
                text="Merk dir, dass ich beim Fernsehen nur die Stehlampe auf 30 Prozent möchte.",
                conversation_id="replace-memory",
                context=context,
            ),
            None,
        )
        return await entity._async_handle_message(
            ConversationInput(
                text="Schalte die Stehlampe ein",
                conversation_id="replace-memory",
                context=context,
            ),
            None,
        )

    result = asyncio.run(scenario())
    assert result.response.speech
    entity.hass.services.async_call.assert_awaited_once()
    assert asyncio.run(entity._runtime_data.memory.async_list()) == ()


def test_comfort_request_asks_from_confirmed_preference_before_action(monkeypatch, tmp_path):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    store = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    entity._runtime_data.memory = store
    asyncio.run(
        store.async_remember(
            MemoryKind.PREFERENCE,
            {
                "activity": "television",
                "brightness_percent": 30,
                "entity_id": LAMP.entity_id,
            },
            provenance=FactProvenance.CONFIRMED_MEMORY,
            confirmed=True,
            person_id="owner",
        )
    )
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: [LAMP])

    async def turn(text: str, user_id: str = "owner"):
        return await entity._async_handle_message(
            ConversationInput(
                text=text,
                conversation_id="comfort",
                context=SimpleNamespace(user_id=user_id),
            ),
            None,
        )

    proposed = asyncio.run(turn("Mach es hier gemütlicher."))
    assert "Stehlampe" in proposed.response.speech
    assert "30 Prozent" in proposed.response.speech
    entity.hass.services.async_call.assert_not_awaited()

    wrong_user = asyncio.run(turn("Ja", "guest"))
    assert "anderen Benutzer" in wrong_user.response.speech
    entity.hass.services.async_call.assert_not_awaited()

    confirmed = asyncio.run(turn("Ja"))
    assert "ausgeführt" in confirmed.response.speech
    entity.hass.services.async_call.assert_awaited_once_with(
        "light",
        "turn_on",
        {"brightness_pct": 30, "entity_id": LAMP.entity_id},
        blocking=True,
    )


def test_comfort_request_without_unique_preference_never_acts(monkeypatch, tmp_path):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    entity._runtime_data.memory = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: [LAMP])
    result = asyncio.run(
        entity._async_handle_message(
            ConversationInput(
                text="Mach es hier gemütlicher.",
                conversation_id="comfort-ambiguous",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )
    )
    assert "konkret" in result.response.speech
    assert "noch nichts ausgeführt" in result.response.speech
    entity.hass.services.async_call.assert_not_awaited()


def test_explicit_routine_feedback_is_bound_and_persisted(monkeypatch, tmp_path):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    store = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    entity._runtime_data.memory = store
    now = datetime.now(timezone.utc)
    stats = RoutineStatistics(minimum_observations=1, anomaly_threshold=0.5)
    stats.observe(
        NormalizedEvent(
            "old", EventType.ACTIVATED, LAMP.entity_id, "off", "on",
            now - timedelta(days=7, hours=3), "living", (), True, "normal",
            "home_assistant", EventQuality.GOOD,
        )
    )
    assessment = stats.assess(
        NormalizedEvent(
            "alert", EventType.ACTIVATED, LAMP.entity_id, "off", "on", now,
            "living", (), True, "normal", "home_assistant", EventQuality.GOOD,
        )
    )
    assert assessment.unusual
    entity._runtime_data.routine_statistics[LAMP.entity_id] = stats
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: [LAMP])
    monkeypatch.setattr(ha_conversation, "build_device_snapshots", lambda *_: [])
    monkeypatch.setattr(ha_conversation.dt_util, "utcnow", lambda: now)

    result = asyncio.run(
        entity._async_handle_message(
            ConversationInput(
                text="Das war hilfreich",
                conversation_id="routine-feedback",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )
    )
    records = asyncio.run(
        store.async_list(person_id="owner", kinds=(MemoryKind.DECISION,))
    )
    assert "hilfreich" in result.response.speech
    assert len(records) == 1
    assert records[0].content == {
        "feedback": "helpful",
        "routine_entity_id": LAMP.entity_id,
    }
    entity.hass.services.async_call.assert_not_awaited()
