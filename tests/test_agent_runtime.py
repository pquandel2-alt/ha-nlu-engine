from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub

_ha_stub.install()

from ha_nlu.agent_event import AgentEventState  # noqa: E402
from ha_nlu.agent_runtime import ProactiveAgentRuntime  # noqa: E402
from ha_nlu.const import (  # noqa: E402
    CONF_AGENT_DELIVERY_CHANNELS,
    CONF_AGENT_ENABLED,
    CONF_AGENT_MEDIA_PLAYERS,
    CONF_AGENT_NOTIFY_TARGETS,
    CONF_AGENT_TTS_ENTITY,
)
from ha_nlu.runtime_data import HaNluRuntimeData  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant, State  # noqa: E402


def _runtime(tmp_path: Path, options: dict | None = None):
    hass = HomeAssistant()
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    entry = ConfigEntry(options=options or {})
    runtime = ProactiveAgentRuntime(hass, entry, HaNluRuntimeData())
    return hass, runtime


def test_disabled_agent_is_a_strict_no_op(tmp_path):
    hass, runtime = _runtime(tmp_path, {CONF_AGENT_ENABLED: False})
    result = asyncio.run(runtime.async_signal({"rule_id": "r", "message": "m"}))
    assert result is None
    hass.services.async_call.assert_not_awaited()


def test_signal_delivers_push_and_deduplicates(tmp_path):
    hass, runtime = _runtime(
        tmp_path,
        {
            CONF_AGENT_NOTIFY_TARGETS: ["notify.mobile_app_phone"],
            CONF_AGENT_DELIVERY_CHANNELS: ["push"],
        },
    )

    async def scenario():
        first = await runtime.async_signal(
            {"rule_id": "temperature-rule", "message": "Grenzwert erreicht"}
        )
        second = await runtime.async_signal(
            {"rule_id": "temperature-rule", "message": "Grenzwert erreicht"}
        )
        return first, second

    first, second = asyncio.run(scenario())
    assert first is not None and first.state is AgentEventState.NOTIFIED
    assert second is not None and second.event_id == first.event_id
    hass.services.async_call.assert_awaited_once()
    call = hass.services.async_call.await_args
    assert call.args[:2] == ("notify", "send_message")
    assert call.args[2]["entity_id"] == ["notify.mobile_app_phone"]


def test_multi_channel_delivery_uses_tts_and_push(tmp_path):
    hass, runtime = _runtime(
        tmp_path,
        {
            CONF_AGENT_NOTIFY_TARGETS: ["notify.mobile_app_phone"],
            CONF_AGENT_DELIVERY_CHANNELS: ["push", "tts"],
            CONF_AGENT_TTS_ENTITY: "tts.piper",
            CONF_AGENT_MEDIA_PLAYERS: ["media_player.kueche"],
        },
    )
    event = asyncio.run(
        runtime.async_signal({"rule_id": "door", "message": "Die Tür ist offen"})
    )
    assert event is not None
    assert event.delivered_channels == ("push", "tts")
    assert hass.services.async_call.await_count == 2
    assert hass.services.async_call.await_args_list[1].args[:2] == ("tts", "speak")


def test_notification_ignore_acknowledges_event(tmp_path):
    _hass, runtime = _runtime(tmp_path)

    async def scenario():
        created = await runtime.async_signal({"rule_id": "door", "message": "Offen"})
        assert created is not None
        await runtime.async_handle_notification_action(
            SimpleNamespace(data={"action": f"HA_NLU_IGNORE_{created.event_id}"})
        )
        return (await runtime._store.async_load_all())[created.event_id]

    stored = asyncio.run(scenario())
    assert stored.state is AgentEventState.ACKNOWLEDGED


def test_stale_source_is_resolved_without_delivery(tmp_path):
    hass, runtime = _runtime(tmp_path)
    hass.states._states["binary_sensor.door"] = State("binary_sensor.door", "off")
    event = asyncio.run(runtime.async_signal({
        "rule_id": "door",
        "message": "Offen",
        "source_entity_id": "binary_sensor.door",
        "expected_source_state": "on",
    }))
    assert event is not None and event.state is AgentEventState.RESOLVED
    hass.services.async_call.assert_not_awaited()


def test_numeric_source_is_rechecked_before_delivery(tmp_path):
    hass, runtime = _runtime(tmp_path)
    hass.states._states["sensor.temperature"] = State("sensor.temperature", "25")
    event = asyncio.run(runtime.async_signal({
        "rule_id": "heat",
        "message": "Zu warm",
        "source_entity_id": "sensor.temperature",
        "source_comparator": "above",
        "source_threshold": 28,
    }))
    assert event is not None and event.state is AgentEventState.RESOLVED
    hass.services.async_call.assert_not_awaited()


def test_ask_notification_action_revalidates_and_executes(monkeypatch, tmp_path):
    hass, runtime = _runtime(
        tmp_path,
        {
            CONF_AGENT_NOTIFY_TARGETS: ["notify.mobile_app_phone"],
            CONF_AGENT_DELIVERY_CHANNELS: ["push"],
        },
    )
    entities = [
        EntitySnapshot(
            "switch.pump",
            "Pumpe",
            "switch",
            "on",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        )
    ]
    monkeypatch.setattr("ha_nlu.agent_runtime.build_entity_snapshots", lambda *_: entities)

    async def scenario():
        created = await runtime.async_signal({
            "rule_id": "pump-rule",
            "message": "Soll ich die Pumpe ausschalten?",
            "mode": "ask",
            "action_domain": "homeassistant",
            "action_service": "turn_off",
            "action_entity_id": "switch.pump",
        })
        assert created is not None
        hass.services.async_call.reset_mock()
        await runtime.async_handle_notification_action(
            SimpleNamespace(data={"action": f"HA_NLU_EXECUTE_{created.event_id}"})
        )
        return (await runtime._store.async_load_all())[created.event_id]

    stored = asyncio.run(scenario())
    assert stored.state is AgentEventState.RESOLVED
    hass.services.async_call.assert_awaited_once_with(
        "homeassistant", "turn_off", {"entity_id": "switch.pump"}, blocking=True
    )


def test_auto_never_executes_medium_risk_cover_action(monkeypatch, tmp_path):
    hass, runtime = _runtime(tmp_path)
    entities = [EntitySnapshot("cover.blind", "Rollo", "cover", "open")]
    monkeypatch.setattr("ha_nlu.agent_runtime.build_entity_snapshots", lambda *_: entities)

    event = asyncio.run(runtime.async_signal({
        "rule_id": "blind-rule",
        "message": "Das Rollo ist noch offen.",
        "mode": "auto",
        "action_domain": "cover",
        "action_service": "close_cover",
        "action_entity_id": "cover.blind",
    }))

    assert event is not None
    assert event.mode.value == "ask"
    assert all(
        call.args[:2] != ("cover", "close_cover")
        for call in hass.services.async_call.await_args_list
    )


def test_low_risk_auto_executes_then_pushes_without_stale_buttons(monkeypatch, tmp_path):
    hass, runtime = _runtime(
        tmp_path,
        {
            CONF_AGENT_NOTIFY_TARGETS: ["notify.mobile_app_phone"],
            CONF_AGENT_DELIVERY_CHANNELS: ["push"],
        },
    )
    entities = [EntitySnapshot("switch.pump", "Pumpe", "switch", "on")]
    monkeypatch.setattr("ha_nlu.agent_runtime.build_entity_snapshots", lambda *_: entities)

    event = asyncio.run(runtime.async_signal({
        "rule_id": "auto-pump",
        "message": "Ich habe die Pumpe ausgeschaltet.",
        "mode": "auto",
        "action_domain": "homeassistant",
        "action_service": "turn_off",
        "action_entity_id": "switch.pump",
    }))

    assert event is not None and event.state is AgentEventState.RESOLVED
    assert hass.services.async_call.await_args_list[0].args[:2] == (
        "homeassistant", "turn_off"
    )
    push_data = hass.services.async_call.await_args_list[1].args[2]
    assert push_data["data"]["actions"] == []


def test_unique_tts_question_accepts_voice_confirmation(monkeypatch, tmp_path):
    hass, runtime = _runtime(
        tmp_path,
        {
            CONF_AGENT_DELIVERY_CHANNELS: ["tts"],
            CONF_AGENT_TTS_ENTITY: "tts.piper",
            CONF_AGENT_MEDIA_PLAYERS: ["media_player.kueche"],
        },
    )
    entities = [EntitySnapshot("switch.pump", "Pumpe", "switch", "on")]
    monkeypatch.setattr("ha_nlu.agent_runtime.build_entity_snapshots", lambda *_: entities)

    async def scenario():
        created = await runtime.async_signal({
            "rule_id": "voice-pump",
            "message": "Soll ich die Pumpe ausschalten?",
            "mode": "ask",
            "action_domain": "homeassistant",
            "action_service": "turn_off",
            "action_entity_id": "switch.pump",
        })
        assert created is not None
        hass.services.async_call.reset_mock()
        reply = await runtime.async_handle_voice_reply(
            "Ja", user_id=None, is_admin=False
        )
        return reply, (await runtime._store.async_load_all())[created.event_id]

    reply, stored = asyncio.run(scenario())
    assert reply == "Erledigt."
    assert stored.state is AgentEventState.RESOLVED
    hass.services.async_call.assert_awaited_once_with(
        "homeassistant", "turn_off", {"entity_id": "switch.pump"}, blocking=True
    )


def test_snooze_uses_durable_helper_and_rechecks_original_conditions(tmp_path):
    hass, runtime = _runtime(tmp_path)

    async def scenario():
        created = await runtime.async_signal({"rule_id": "door-rule", "message": "Offen"})
        assert created is not None
        hass.services.async_call.reset_mock()
        await runtime.async_handle_notification_action(
            SimpleNamespace(data={"action": f"HA_NLU_SNOOZE_{created.event_id}"})
        )
        snoozed = (await runtime._store.async_load_all())[created.event_id]
        hass.services.async_call.reset_mock()
        await runtime.async_recheck(created.event_id)
        rechecked = (await runtime._store.async_load_all())[created.event_id]
        return snoozed, rechecked

    snoozed, rechecked = asyncio.run(scenario())
    assert snoozed.state is AgentEventState.SNOOZED
    assert snoozed.reminder_automation_id is not None
    assert rechecked.state is AgentEventState.EXPIRED
    hass.services.async_call.assert_awaited_once_with(
        "automation",
        "trigger",
        {"entity_id": "automation.door-rule", "skip_condition": False},
        blocking=True,
    )
