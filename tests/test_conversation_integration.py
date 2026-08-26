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
from ha_nlu.automation_management import (  # noqa: E402
    AutomationManagementKind,
    AutomationManagementRequest,
)
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.nlu.context import PendingAutomationManagement  # noqa: E402
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
KUECHE_FENSTER = EntitySnapshot(
    "binary_sensor.kueche_fenster", "Küchenfenster", "binary_sensor", "off",
    area_id="kueche", area_name="Küche", device_class="window",
)
KUECHE_LICHT = EntitySnapshot(
    "light.kueche", "Küchenlicht", "light", "off",
    area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
RADIO_ATLAS = EntitySnapshot(
    "media_player.atlas", "Radio Atlas", "media_player", "playing"
)
SAUGROBOTER_ATLAS = EntitySnapshot(
    "vacuum.atlas", "Saugroboter Atlas", "vacuum", "cleaning"
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


def test_multi_command_applies_policy_before_any_service_call(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF, KUECHE_LICHT])
    entity.entry.options["read_only_entities"] = ["light.kueche"]

    result = _run(
        entity,
        "Schalte das Flurlicht ein und schalte das Küchenlicht aus",
    )

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code == intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    assert "Lesen" in result.response.speech


def test_state_query_returns_query_answer_and_does_not_call_service(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_ON])

    result = _run(entity, "Ist das Flurlicht an?")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert "Flurlicht" in result.response.speech


@pytest.mark.parametrize(
    ("entity_snapshot", "question", "expected"),
    (
        (RADIO_ATLAS, "Spielt das Radio Atlas?", "Ja,"),
        (RADIO_ATLAS, "Pausiert das Radio Atlas?", "Nein,"),
        (SAUGROBOTER_ATLAS, "Startet der Saugroboter Atlas?", "nicht sicher"),
        (SAUGROBOTER_ATLAS, "Stoppt der Saugroboter Atlas?", "nicht sicher"),
    ),
)
def test_verb_first_state_question_is_live_and_never_calls_service(
    monkeypatch, entity_snapshot, question, expected
):
    entity = _make_entity(monkeypatch, [entity_snapshot])

    result = _run(entity, question)

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code is None
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert expected in result.response.speech


def test_verb_question_keeps_focus_for_pronoun_and_explanation(monkeypatch):
    entity = _make_entity(monkeypatch, [RADIO_ATLAS])

    first = _run(entity, "Spielt das Radio Atlas?", "verb-context")
    followup = _run(entity, "Läuft es noch?", "verb-context")
    explanation = _run(entity, "Woher weißt du das?", "verb-context")

    entity.hass.services.async_call.assert_not_awaited()
    assert first.response.speech.startswith("Ja,")
    assert followup.response.speech.startswith("Ja,")
    assert "Home-Assistant-Zustand" in explanation.response.speech
    assert "kein Dienst" in explanation.response.speech


def test_elliptical_query_reuses_predicate_for_new_explicit_target(monkeypatch):
    second_radio = EntitySnapshot(
        "media_player.birke", "Radio Birke", "media_player", "paused"
    )
    entity = _make_entity(monkeypatch, [RADIO_ATLAS, second_radio])

    _run(entity, "Spielt das Radio Atlas?", "verb-new-target")
    followup = _run(entity, "Und das Radio Birke?", "verb-new-target")

    entity.hass.services.async_call.assert_not_awaited()
    assert followup.response.speech.startswith("Nein,")
    assert "Radio Birke" in followup.response.speech
    assert followup.response.response_type == intent.IntentResponseType.QUERY_ANSWER


def test_other_reference_uses_remaining_device_in_same_area(monkeypatch):
    first = EntitySnapshot(
        "media_player.atlas", "Radio Atlas", "media_player", "playing",
        area_id="wohnzimmer", area_name="Wohnzimmer",
    )
    second = EntitySnapshot(
        "media_player.birke", "Radio Birke", "media_player", "paused",
        area_id="wohnzimmer", area_name="Wohnzimmer",
    )
    entity = _make_entity(monkeypatch, [first, second])

    _run(entity, "Spielt das Radio Atlas?", "verb-other")
    followup = _run(entity, "Und der andere?", "verb-other")

    entity.hass.services.async_call.assert_not_awaited()
    assert followup.response.speech.startswith("Nein,")
    assert "Radio Birke" in followup.response.speech


def test_ambiguous_verb_question_names_candidates_and_accepts_short_reply(monkeypatch):
    second_radio = EntitySnapshot(
        "media_player.birke", "Radio Birke", "media_player", "paused"
    )
    entity = _make_entity(monkeypatch, [RADIO_ATLAS, second_radio])

    question = _run(entity, "Spielt das Radio?", "verb-clarification")
    answer = _run(entity, "Radio Birke", "verb-clarification")

    entity.hass.services.async_call.assert_not_awaited()
    assert "Radio Atlas oder Radio Birke" in question.response.speech
    assert answer.response.speech.startswith("Nein,")
    assert "Radio Birke" in answer.response.speech


def test_location_only_followup_reuses_verb_predicate(monkeypatch):
    kitchen_radio = EntitySnapshot(
        "media_player.atlas", "Radio Atlas", "media_player", "playing",
        area_id="kueche", area_name="Küche",
    )
    living_radio = EntitySnapshot(
        "media_player.birke", "Radio Birke", "media_player", "paused",
        area_id="wohnzimmer", area_name="Wohnzimmer",
    )
    entity = _make_entity(monkeypatch, [kitchen_radio, living_radio])

    _run(entity, "Spielt das Radio Atlas?", "verb-location")
    followup = _run(entity, "Und im Wohnzimmer?", "verb-location")

    entity.hass.services.async_call.assert_not_awaited()
    assert followup.response.speech.startswith("Nein,")
    assert "Radio Birke" in followup.response.speech
    assert followup.response.response_type == intent.IntentResponseType.QUERY_ANSWER


def test_household_presence_query_is_live_and_strictly_read_only(monkeypatch):
    philipp = EntitySnapshot("person.philipp", "Philipp", "person", "home")
    entity = _make_entity(monkeypatch, [philipp])

    result = _run(entity, "Wer ist zuhause?")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert "Zuhause: Philipp" in result.response.speech


def test_capability_readiness_audit_is_live_and_strictly_read_only(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF, EG_TEMPERATUR])

    result = _run(entity, "Ist HomeIntent bereit?")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert "2 freigegebene Entities" in result.response.speech


def test_cover_group_without_floor_assignment_returns_actionable_error(monkeypatch):
    cover = EntitySnapshot(
        "cover.buero", "Rollladen Büro", "cover", "closed",
        area_id="buero", area_name="Büro",
        capabilities=frozenset({"POSITION"}),
    )
    entity = _make_entity(monkeypatch, [cover])

    result = _run(entity, "Fahre alle Rolladen im Erdgeschoss halb runter")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code == intent.IntentResponseErrorCode.NO_INTENT_MATCH
    assert result.response.speech == (
        "Ich kenne den Bereich oder die Etage „Erdgeschoss“ nicht. "
        "Bitte ordne die Geräte in Home Assistant einem Bereich und den Bereich einer Etage zu."
    )


def test_complete_group_command_supersedes_pending_cover_clarification(monkeypatch):
    covers = [
        EntitySnapshot(
            "cover.links", "Rollladen Esszimmer", "cover", "closed",
            area_id="esszimmer", area_name="Esszimmer",
        ),
        EntitySnapshot(
            "cover.rechts", "Rollladen Esszimmer", "cover", "closed",
            area_id="esszimmer", area_name="Esszimmer",
        ),
    ]
    entity = _make_entity(monkeypatch, covers)

    ambiguous = _run(
        entity,
        "Fahre den Rollladen im Esszimmer hoch",
        conversation_id="cover-replacement",
    )
    replacement = _run(
        entity,
        "Fahre alle Rolladen im Esszimmer hoch",
        conversation_id="cover-replacement",
    )

    assert ambiguous.response.speech == "Welche Rollläden meinst du?"
    assert replacement.response.speech == "2 Rollläden geöffnet."
    entity.hass.services.async_call.assert_awaited_once_with(
        "cover",
        "open_cover",
        {"entity_id": ["cover.links", "cover.rechts"]},
        blocking=True,
    )


def test_trigger_and_action_can_be_spoken_in_two_turns(monkeypatch):
    entity = _make_entity(monkeypatch, [KUECHE_FENSTER, KUECHE_LICHT])

    question = _run(entity, "Wenn das Küchenfenster geöffnet wird")
    preview = _run(entity, "Schalte das Küchenlicht ein")

    entity.hass.services.async_call.assert_not_awaited()
    assert question.response.speech == "Was soll dann passieren?"
    assert "Fenster im Bereich Küche" in preview.response.speech
    assert "Licht im Bereich Küche" in preview.response.speech
    context = entity._context_store.get("conv-1")
    assert context.pending_automation_confirmation is not None


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


def test_floor_temperature_question_lists_multiple_sensors(monkeypatch):
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
    assert question.response.speech == (
        "Küche Temperatur: 22,4 Grad; Wohnzimmer Temperatur: 21,8 Grad."
    )


def test_temperature_query_then_contextual_setpoint_reaches_live_service(monkeypatch):
    thermostat = EntitySnapshot(
        "climate.erdgeschoss",
        "Erdgeschoss Heizung",
        "climate",
        "heat",
        area_id="kueche",
        area_name="Küche",
        floor_id="eg",
        floor_name="Erdgeschoss",
        floor_level=0,
        attributes={"temperature": 21},
        capabilities=frozenset({"TEMPERATURE"}),
    )
    entity = _make_entity(monkeypatch, [EG_TEMPERATUR, thermostat])

    query = _run(
        entity,
        "Wie hoch ist die Temperatur im Erdgeschoss?",
        conversation_id="logical-temperature",
    )
    command = _run(
        entity,
        "Kannst du die Temperatur auf 22 Grad erhöhen?",
        conversation_id="logical-temperature",
    )

    assert query.response.speech == "22.4 Grad."
    assert command.response.speech == "Erdgeschoss Heizung auf 22 Grad gestellt."
    entity.hass.services.async_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.erdgeschoss", "temperature": 22},
        blocking=True,
    )


def test_unmatched_sentence_returns_not_understood(monkeypatch):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF])

    result = _run(entity, "Erzähl mir bitte einen Witz")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code == intent.IntentResponseErrorCode.NO_INTENT_MATCH


def test_service_call_exception_produces_clean_failed_to_handle_response(monkeypatch, caplog):
    """Milestone 0 regression: a service-call failure must produce a clean
    FAILED_TO_HANDLE response, not propagate as "Unexpected error during
    intent recognition" (the broadened ``except Exception`` in
    conversation.py's two service-call sites)."""
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF])
    entity.hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))

    result = _run(entity, "Schalte das Flurlicht ein")

    assert result.response.error_code == intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    assert "boom" in result.response.speech
    assert "Service call homeassistant.turn_on" in caplog.text


def test_undo_service_failure_is_logged(monkeypatch, caplog):
    entity = _make_entity(monkeypatch, [FLUR_LICHT_OFF])
    _run(entity, "Schalte das Flurlicht ein", conversation_id="undo-failure")
    entity.hass.services.async_call.reset_mock()
    entity.hass.services.async_call.side_effect = RuntimeError("undo unavailable")

    result = _run(entity, "Mach das rückgängig", conversation_id="undo-failure")

    assert "undo unavailable" in result.response.speech
    assert "Undo service call failed" in caplog.text


def test_automation_management_failure_is_logged(monkeypatch, caplog):
    entity = _make_entity(monkeypatch, [])
    entity._automation_executor = AsyncMock()
    entity._automation_executor.async_cleanup_expired_scheduled_automations.side_effect = (
        RuntimeError("yaml unavailable")
    )
    response = intent.IntentResponse(language="de")
    user_input = ConversationInput(text="Ja", conversation_id="management-failure")
    pending = PendingAutomationManagement(
        AutomationManagementRequest(AutomationManagementKind.CLEAN_EXPIRED)
    )

    result = asyncio.run(
        entity._async_handle_automation_management_confirmation(
            user_input, response, pending
        )
    )

    assert "yaml unavailable" in result.response.speech
    assert "Automation management failed" in caplog.text


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
