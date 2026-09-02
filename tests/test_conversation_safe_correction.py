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
        "light.living",
        "Wohnzimmerlicht",
        "light",
        "off",
        area_id="living",
        area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.floor",
        "Stehlampe",
        "light",
        "off",
        area_id="living",
        area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]


def test_correction_compensates_previous_action_before_retargeting(monkeypatch):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: LIGHTS)

    async def turn(text: str):
        return await entity._async_handle_message(
            ConversationInput(
                text=text,
                conversation_id="safe-correction",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )

    asyncio.run(turn("Mach das Wohnzimmerlicht an."))
    corrected = asyncio.run(turn("Nein, ich meinte nur die Stehlampe."))

    calls = entity.hass.services.async_call.await_args_list
    assert len(calls) == 3
    assert calls[0].args[:2] == ("homeassistant", "turn_on")
    assert calls[0].args[2]["entity_id"] == "light.living"
    assert calls[1].args[:2] == ("light", "turn_off")
    assert calls[1].args[2]["entity_id"] == "light.living"
    assert calls[2].args[:2] == ("homeassistant", "turn_on")
    assert calls[2].args[2]["entity_id"] == "light.floor"
    assert "Stehlampe" in corrected.response.speech


def test_correction_stops_when_compensation_effect_is_not_observed(monkeypatch):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    still_on = [
        EntitySnapshot(
            item.entity_id,
            item.friendly_name,
            item.domain,
            "on" if item.entity_id == "light.living" else item.state,
            area_id=item.area_id,
            area_name=item.area_name,
            capabilities=item.capabilities,
        )
        for item in LIGHTS
    ]
    snapshots = iter((LIGHTS, still_on, still_on, still_on))
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda *_: next(snapshots)
    )

    async def turn(text: str):
        return await entity._async_handle_message(
            ConversationInput(
                text=text,
                conversation_id="failed-correction",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )

    asyncio.run(turn("Mach das Wohnzimmerlicht an."))
    stopped = asyncio.run(turn("Nein, ich meinte nur die Stehlampe."))
    assert len(entity.hass.services.async_call.await_args_list) == 2
    assert "sicher gestoppt" in stopped.response.speech
