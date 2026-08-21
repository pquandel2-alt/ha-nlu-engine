"""Phase 3 (HomeIntent v4.2.1 plan, Sections 3/23-26): exercises the real
``NluConversationEntity._async_handle_message()`` orchestration end-to-end -
pending-clarification / follow-up / reference / query-followup / fresh-match
try-chain, ``ConversationContextStore`` set/clear, the ``QUERY_ANSWER`` vs
``ACTION_DONE`` response-type gate, and the actual
``hass.services.async_call`` call site - not a second reimplementation of
``engine.match()`` (every other test file in this suite only calls that
directly).

Uses ``tests/_ha_stub.py`` to inject a minimal fake ``homeassistant`` module
tree, since the real package isn't installed anywhere in this project's test
environment (see that module's docstring). ``build_entity_snapshots`` (pure
HA-registry glue, out of scope for this plan) is monkeypatched per test
instead of stubbed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

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
from homeassistant.helpers import intent  # noqa: E402

FLUR_LICHT_OFF = EntitySnapshot(
    "light.flur_licht", "Flurlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
FLUR_LICHT_ON = EntitySnapshot(
    "light.flur_licht", "Flurlicht", "light", "on",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
EG_TEMPERATUR = EntitySnapshot(
    "sensor.kueche_temperatur",
    "Küche Temperatur",
    "sensor",
    "22.4",
    area_id="kueche",
    area_name="Küche",
    floor_id="eg",
    floor_name="Erdgeschoss",
    floor_level=0,
    unit="°C",
    device_class="temperature",
)


def _make_entity(monkeypatch, entities: list[EntitySnapshot]) -> NluConversationEntity:
    entry = ConfigEntry()
    entity = NluConversationEntity(entry)
    entity.hass = HomeAssistant()
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda hass, entry: entities
    )
    return entity


def _run(entity: NluConversationEntity, text: str, conversation_id: str = "conv-1"):
    user_input = ConversationInput(text=text, conversation_id=conversation_id)
    return asyncio.run(entity._async_handle_message(user_input, chat_log=None))


def test_turn_on_command_calls_service_and_responds_action_done(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF])

    result = _run(entity, "Schalte das Flurlicht ein")

    entity.hass.services.async_call.assert_awaited_once()
    call_args = entity.hass.services.async_call.await_args
    # HassTurnOn deliberately calls the generic cross-domain
    # ``homeassistant.turn_on`` service, not ``light.turn_on``
    # (service_call.py:57) - matches production behavior.
    assert call_args.args[0] == "homeassistant"
    assert call_args.args[1] == "turn_on"
    assert call_args.args[2]["entity_id"] == "light.flur_licht"
    assert call_args.kwargs == {"blocking": True}

    assert result.response.error_code is None
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert result.response.speech


def test_state_query_returns_query_answer_and_does_not_call_service(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_ON])

    result = _run(entity, "Ist das Flurlicht an?")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert "Flurlicht" in result.response.speech


@pytest.mark.parametrize(
    "sentence",
    (
        "Wie warm ist es im Erdgeschoss?",
        "Wie hoch ist die Temperatur im Erdgeschoss?",
        "Welche Temperatur hat das Erdgeschoss?",
    ),
)
def test_floor_temperature_question_reaches_live_conversation_query(
    monkeypatch, sentence
):
    entity = _make_entity(monkeypatch, [EG_TEMPERATUR])

    result = _run(entity, sentence)

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code is None
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert result.response.speech == "22.4 Grad."


def test_floor_temperature_question_clarifies_multiple_sensors(monkeypatch):
    second = EntitySnapshot(
        "sensor.wohnzimmer_temperatur",
        "Wohnzimmer Temperatur",
        "sensor",
        "21.8",
        area_id="wohnzimmer",
        area_name="Wohnzimmer",
        floor_id="eg",
        floor_name="Erdgeschoss",
        floor_level=0,
        unit="°C",
        device_class="temperature",
    )
    entity = _make_entity(monkeypatch, [EG_TEMPERATUR, second])

    question = _run(
        entity,
        "Welche Temperatur hat das Erdgeschoss?",
        conversation_id="floor-temp",
    )
    answer = _run(entity, "Küche Temperatur", conversation_id="floor-temp")

    assert question.response.speech == "Welchen Sensor meinst du?"
    assert answer.response.error_code is None
    assert answer.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert answer.response.speech == "22.4 Grad."


def test_unmatched_sentence_returns_not_understood(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF])

    result = _run(entity, "Erzähl mir bitte einen Witz")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code == intent.IntentResponseErrorCode.NO_INTENT_MATCH


def test_service_call_exception_produces_clean_failed_to_handle_response(monkeypatch):
    """Milestone 0 regression: a service-call failure must produce a clean
    FAILED_TO_HANDLE response, not propagate as "Unexpected error during
    intent recognition" (the broadened ``except Exception`` in
    conversation.py's two service-call sites)."""
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF])
    entity.hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))

    result = _run(entity, "Schalte das Flurlicht ein")

    assert result.response.error_code == intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    assert "boom" in result.response.speech


def test_pronoun_follow_up_reuses_context_from_previous_command(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF])

    _run(entity, "Schalte das Flurlicht ein", conversation_id="conv-followup")
    entity.hass.services.async_call.reset_mock()

    result = _run(entity, "Mach es aus", conversation_id="conv-followup")

    entity.hass.services.async_call.assert_awaited_once()
    call_args = entity.hass.services.async_call.await_args
    assert call_args.args[0] == "homeassistant"
    assert call_args.args[1] == "turn_off"
    assert call_args.args[2]["entity_id"] == "light.flur_licht"
    assert result.response.error_code is None
