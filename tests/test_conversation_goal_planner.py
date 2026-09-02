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
