from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.house_graph import FactProvenance  # noqa: E402
from ha_nlu.memory import MemoryKind, MemoryStore  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


LIGHTS = [
    EntitySnapshot(
        "light.living", "Wohnzimmerlicht", "light", "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.hall", "Flurlicht", "light", "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]


def test_prepare_night_materializes_preview_without_action(monkeypatch):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: LIGHTS)

    async def turn(text: str):
        return await entity._async_handle_message(
            ConversationInput(
                text=text,
                conversation_id="night-plan",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )

    preview = asyncio.run(turn("Bereite das Haus für die Nacht vor."))
    assert "Planvorschau" in preview.response.speech
    assert "2 geprüfte Aktion" in preview.response.speech
    entity.hass.services.async_call.assert_not_awaited()

    cancelled = asyncio.run(turn("Nein"))
    assert "nicht ausgeführt" in cancelled.response.speech
    entity.hass.services.async_call.assert_not_awaited()


def test_read_only_goal_fails_before_preview(monkeypatch):
    entity = NluConversationEntity(
        ConfigEntry(options={"read_only_entities": ["light.living"]})
    )
    entity.hass = HomeAssistant()
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: LIGHTS)
    result = asyncio.run(
        entity._async_handle_message(
            ConversationInput(
                text="Bereite das Haus für die Nacht vor.",
                conversation_id="denied-night-plan",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )
    )
    assert "keinen sicheren Plan" in result.response.speech
    entity.hass.services.async_call.assert_not_awaited()


def test_named_procedure_is_confirmed_stored_and_rematerialized(monkeypatch, tmp_path):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    store = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    entity._runtime_data.memory = store
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: LIGHTS)
    monkeypatch.setattr(ha_conversation, "build_device_snapshots", lambda *_: [])

    async def turn(text: str):
        return await entity._async_handle_message(
            ConversationInput(
                text=text,
                conversation_id="named-procedure",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )

    asyncio.run(turn("Bereite das Haus für die Nacht vor."))
    save = asyncio.run(turn("Speichere diesen Plan als Abendrunde"))
    assert "dauerhaft speichern" in save.response.speech
    assert asyncio.run(store.async_list()) == ()

    confirmed = asyncio.run(turn("Ja"))
    records = asyncio.run(
        store.async_list(person_id="owner", kinds=(MemoryKind.PROCEDURE,))
    )
    assert confirmed.response.speech.startswith("Gespeichert")
    assert len(records) == 1
    assert records[0].content["goal_kind"] == "prepare_night"

    listed = asyncio.run(turn("Welche Prozeduren kennst du?"))
    assert "abendrunde" in listed.response.speech.casefold()

    rerun = asyncio.run(turn("Führe die Prozedur Abendrunde aus"))
    assert "frisch" not in rerun.response.speech.casefold()
    assert "Soll ich sie ausführen" in rerun.response.speech
    entity.hass.services.async_call.assert_not_awaited()

    cancelled = asyncio.run(turn("Nein"))
    assert "nicht ausgeführt" in cancelled.response.speech
    entity.hass.services.async_call.assert_not_awaited()


def test_movie_goal_uses_one_confirmed_preference_as_preview(monkeypatch, tmp_path):
    movie_light = EntitySnapshot(
        "light.movie", "Filmlicht", "light", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    )
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    store = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    entity._runtime_data.memory = store
    asyncio.run(
        store.async_remember(
            MemoryKind.PREFERENCE,
            {
                "activity": "television",
                "entity_id": movie_light.entity_id,
                "brightness_percent": 30,
            },
            provenance=FactProvenance.CONFIRMED_MEMORY,
            confirmed=True,
            person_id="owner",
        )
    )
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda *_: [movie_light]
    )
    monkeypatch.setattr(ha_conversation, "build_device_snapshots", lambda *_: [])

    result = asyncio.run(
        entity._async_handle_message(
            ConversationInput(
                text="Bereite den Filmabend vor",
                conversation_id="movie-plan",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )
    )
    active = entity._runtime_data.dialog_manager.active("movie-plan")
    assert "Planvorschau" in result.response.speech
    assert active is not None
    stored_plan = active.slots["plan"]
    action = next(step.action for step in stored_plan.steps if step.action is not None)
    assert action.data == {"brightness_pct": 30}
    entity.hass.services.async_call.assert_not_awaited()
