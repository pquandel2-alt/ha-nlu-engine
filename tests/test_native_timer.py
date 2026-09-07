"""Native Assist timer routing and audible fallback remain deterministic."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import _ha_stub
import pytest

_ha_stub.install()

from ha_nlu.const import (
    CONF_AGENT_MEDIA_PLAYERS,
    CONF_AGENT_TTS_ENTITY,
    CONF_TIMER_CHIME_MEDIA_ID,
)
from ha_nlu.native_timer import NativeTimerRuntime, NativeTimerUnavailableError
from ha_nlu.productivity import TimerOperation, TimerRequest
from homeassistant.components.conversation import ConversationInput
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent


def _runtime(options: dict | None = None) -> tuple[NativeTimerRuntime, HomeAssistant]:
    hass = HomeAssistant()
    return NativeTimerRuntime(hass, ConfigEntry(options=options)), hass


def test_named_start_is_delegated_to_native_ha_intent(monkeypatch):
    runtime, _ = _runtime()
    monkeypatch.setattr(runtime, "_route_device", AsyncMock(return_value="voice-device"))
    handle = AsyncMock()
    monkeypatch.setattr(intent, "async_handle", handle, raising=False)
    monkeypatch.setattr(intent, "INTENT_START_TIMER", "HassStartTimer", raising=False)

    speech = asyncio.run(runtime.async_execute(
        TimerRequest(TimerOperation.START, duration_seconds=330, name="Nudeln"),
        ConversationInput(
            text="Stelle einen Timer", conversation_id="timer", device_id="phone"
        ),
    ))

    assert speech == "Timer „Nudeln“ für 5 Minuten und 30 Sekunden gestartet."
    assert handle.await_args.args[:4] == (
        runtime._hass,
        "ha_nlu",
        "HassStartTimer",
        {
            "minutes": {"value": 5},
            "seconds": {"value": 30},
            "name": {"value": "Nudeln"},
        },
    )
    assert handle.await_args.kwargs["device_id"] == "voice-device"


def test_finished_fallback_speaks_timer_information_once():
    runtime, hass = _runtime({
        CONF_AGENT_TTS_ENTITY: "tts.piper",
        CONF_AGENT_MEDIA_PLAYERS: ["media_player.assist"],
    })

    async def run() -> None:
        runtime._handle_timer_event("updated", SimpleNamespace(name="Nudeln"))
        runtime._handle_timer_event("finished", SimpleNamespace(name="Nudeln"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(run())

    hass.services.async_call.assert_awaited_once_with(
        "tts",
        "speak",
        {
            "entity_id": "tts.piper",
            "media_player_entity_id": ["media_player.assist"],
            "message": "Nudeln: Der Timer ist abgelaufen.",
        },
        blocking=True,
    )


def test_finished_fallback_plays_configured_local_chime_before_information():
    runtime, hass = _runtime({
        CONF_AGENT_TTS_ENTITY: "tts.piper",
        CONF_AGENT_MEDIA_PLAYERS: ["media_player.assist"],
        CONF_TIMER_CHIME_MEDIA_ID: "media-source://media_source/local/timer.wav",
    })

    asyncio.run(runtime._async_announce("Nudeln: Der Timer ist abgelaufen."))

    assert hass.services.async_call.await_args_list[0].args[:2] == (
        "media_player", "play_media"
    )
    assert hass.services.async_call.await_args_list[0].args[2]["media_content_id"] == (
        "media-source://media_source/local/timer.wav"
    )
    assert hass.services.async_call.await_args_list[1].args[:2] == ("tts", "speak")


def test_timer_chime_rejects_arbitrary_remote_url_but_still_speaks():
    runtime, hass = _runtime({
        CONF_AGENT_TTS_ENTITY: "tts.piper",
        CONF_AGENT_MEDIA_PLAYERS: ["media_player.assist"],
        CONF_TIMER_CHIME_MEDIA_ID: "https://example.invalid/chime.mp3",
    })

    asyncio.run(runtime._async_announce("Timer abgelaufen."))

    hass.services.async_call.assert_awaited_once()
    assert hass.services.async_call.await_args.args[:2] == ("tts", "speak")


def test_silent_fallback_is_rejected(monkeypatch):
    runtime, _ = _runtime()
    runtime._unregister = lambda: None

    import homeassistant.components as components

    fake_intent_component = SimpleNamespace(
        async_device_supports_timers=lambda hass, device_id: False
    )
    monkeypatch.setattr(components, "intent", fake_intent_component, raising=False)
    monkeypatch.setitem(sys.modules, "homeassistant.components.intent", fake_intent_component)

    async def run() -> None:
        try:
            await runtime._route_device("phone")
        except NativeTimerUnavailableError as err:
            assert "keinen hörbaren Timer" in str(err)
        else:
            raise AssertionError("silent timer route was accepted")

    asyncio.run(run())


def test_start_registers_and_unload_removes_synthetic_handler(monkeypatch):
    runtime, hass = _runtime()
    unregister = Mock()
    captured: dict[str, object] = {}

    def register(received_hass, device_id, handler):
        captured.update(hass=received_hass, device_id=device_id, handler=handler)
        return unregister

    fake_intent_component = SimpleNamespace(async_register_timer_handler=register)
    monkeypatch.setitem(sys.modules, "homeassistant.components.intent", fake_intent_component)

    stop = runtime.async_start()
    stop()

    assert captured["hass"] is hass
    assert captured["device_id"] == "ha_nlu:test-entry"
    assert callable(captured["handler"])
    unregister.assert_called_once_with()


def _install_timer_intents(monkeypatch, response=None):
    names = {
        "INTENT_START_TIMER": "HassStartTimer",
        "INTENT_INCREASE_TIMER": "HassIncreaseTimer",
        "INTENT_DECREASE_TIMER": "HassDecreaseTimer",
        "INTENT_PAUSE_TIMER": "HassPauseTimer",
        "INTENT_UNPAUSE_TIMER": "HassUnpauseTimer",
        "INTENT_CANCEL_TIMER": "HassCancelTimer",
        "INTENT_TIMER_STATUS": "HassTimerStatus",
    }
    for attribute, value in names.items():
        monkeypatch.setattr(intent, attribute, value, raising=False)
    handle = AsyncMock(return_value=response or SimpleNamespace(speech_slots={}))
    monkeypatch.setattr(intent, "async_handle", handle, raising=False)
    return handle


@pytest.mark.parametrize(
    ("timer_request", "intent_name", "expected"),
    (
        (TimerRequest(TimerOperation.CHANGE, change_seconds=120, name="Nudeln"), "HassIncreaseTimer", "verlängert"),
        (TimerRequest(TimerOperation.CHANGE, change_seconds=-60, name="Nudeln"), "HassDecreaseTimer", "verkürzt"),
        (TimerRequest(TimerOperation.PAUSE, name="Nudeln"), "HassPauseTimer", "pausiert"),
        (TimerRequest(TimerOperation.RESUME, name="Nudeln"), "HassUnpauseTimer", "fortgesetzt"),
        (TimerRequest(TimerOperation.CANCEL, name="Nudeln"), "HassCancelTimer", "abgebrochen"),
        (TimerRequest(TimerOperation.FINISH, name="Nudeln"), "HassCancelTimer", "beendet"),
    ),
)
def test_native_timer_operations_use_only_registered_ha_intents(
    monkeypatch, timer_request, intent_name, expected
):
    runtime, _ = _runtime()
    monkeypatch.setattr(runtime, "_route_device", AsyncMock(return_value="voice"))
    handle = _install_timer_intents(monkeypatch)

    speech = asyncio.run(runtime.async_execute(
        timer_request, ConversationInput(text="Timer", conversation_id="operations")
    ))

    assert handle.await_args.args[2] == intent_name
    assert expected in speech


def test_native_status_uses_structured_speech_slots(monkeypatch):
    response = SimpleNamespace(speech_slots={"timers": [
        {"name": "Nudeln", "total_seconds_left": 75, "is_active": True},
        {"name": "Tee", "total_seconds_left": 30, "is_active": False},
    ]})
    runtime, _ = _runtime()
    monkeypatch.setattr(runtime, "_route_device", AsyncMock(return_value="voice"))
    _install_timer_intents(monkeypatch, response)

    speech = asyncio.run(runtime.async_execute(
        TimerRequest(TimerOperation.STATUS),
        ConversationInput(text="Timerstatus", conversation_id="status"),
    ))

    assert speech == (
        "Nudeln: verbleiben 1 Minute und 15 Sekunden; "
        "Tee: pausiert, verbleibend 30 Sekunden."
    )


def test_route_prefers_native_source_and_can_use_configured_fallback(monkeypatch):
    runtime, hass = _runtime({
        CONF_AGENT_TTS_ENTITY: "tts.piper",
        CONF_AGENT_MEDIA_PLAYERS: ["media_player.assist"],
    })
    runtime._unregister = Mock()
    supported = {"native": True, "phone": False}
    fake_intent_component = SimpleNamespace(
        async_device_supports_timers=lambda received_hass, device: (
            received_hass is hass and supported[device]
        )
    )
    monkeypatch.setitem(sys.modules, "homeassistant.components.intent", fake_intent_component)

    assert asyncio.run(runtime._route_device("native")) == "native"
    assert asyncio.run(runtime._route_device("phone")) == "ha_nlu:test-entry"


def test_zero_duration_is_rejected_before_native_intent(monkeypatch):
    runtime, _ = _runtime()
    monkeypatch.setattr(runtime, "_route_device", AsyncMock(return_value="voice"))
    handle = _install_timer_intents(monkeypatch)

    with pytest.raises(ValueError, match="gültige Dauer"):
        asyncio.run(runtime.async_execute(
            TimerRequest(TimerOperation.START, duration_seconds=0),
            ConversationInput(text="Timer", conversation_id="zero"),
        ))

    handle.assert_not_awaited()
