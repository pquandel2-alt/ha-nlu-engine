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
from ha_nlu.automation_scenarios import interpret_downstairs_shutdown  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.nlu.action_model import ActionType  # noqa: E402
from ha_nlu.nlu.language_frontend import analyse_language  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


TEXT = (
    "Wenn niemand mehr unten ist, mach dort alles aus, aber lass das "
    "Flurlicht noch zehn Minuten an."
)
ENTITIES = [
    EntitySnapshot(
        "binary_sensor.downstairs_occupied",
        "Anwesenheit unten",
        "binary_sensor",
        "on",
        floor_id="ground",
        floor_name="Erdgeschoss",
        floor_level=0,
        device_class="occupancy",
    ),
    EntitySnapshot(
        "light.living",
        "Wohnzimmerlicht",
        "light",
        "on",
        floor_id="ground",
        floor_name="Erdgeschoss",
        floor_level=0,
        capabilities=frozenset({"TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.hall",
        "Flurlicht",
        "light",
        "on",
        floor_id="ground",
        floor_name="Erdgeschoss",
        floor_level=0,
        capabilities=frozenset({"TURN_OFF"}),
    ),
]


def test_downstairs_shutdown_materializes_exact_ids_and_delay():
    result = interpret_downstairs_shutdown(analyse_language(TEXT, ENTITIES), ENTITIES)
    assert result is not None and result.validation_error is None
    assert result.model.triggers[0].target.entity_id == "binary_sensor.downstairs_occupied"
    assert [step.type for step in result.model.actions] == [
        ActionType.TURN_OFF,
        ActionType.DELAY,
        ActionType.TURN_OFF,
    ]
    assert result.model.actions[0].target.entity_ids == ("light.living",)
    assert result.model.actions[1].delay_seconds == 600
    assert result.model.actions[2].target.entity_id == "light.hall"


def test_downstairs_shutdown_preview_requires_confirmation_and_does_not_act(monkeypatch):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda *_: ENTITIES)
    result = asyncio.run(
        entity._async_handle_message(
            ConversationInput(
                text=TEXT,
                conversation_id="downstairs-preview",
                context=SimpleNamespace(user_id="owner"),
            ),
            None,
        )
    )
    assert "Wenn" in result.response.speech
    assert "10 Minuten" in result.response.speech
    assert "Soll diese Automation erstellt werden" in result.response.speech
    entity.hass.services.async_call.assert_not_awaited()


def test_downstairs_shutdown_rejects_ambiguous_occupancy_sensor():
    ambiguous = ENTITIES + [
        EntitySnapshot(
            "binary_sensor.downstairs_occupied_2",
            "Anwesenheit unten zwei",
            "binary_sensor",
            "off",
            floor_id="ground",
            floor_level=0,
            device_class="occupancy",
        )
    ]
    result = interpret_downstairs_shutdown(analyse_language(TEXT, ambiguous), ambiguous)
    assert result is not None and result.validation_error is not None
    assert "eindeutig" in result.response_text
