from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from ha_nlu.const import (  # noqa: E402
    CONF_AGENT_EVENT_CATEGORIES,
    CONF_ROUTINE_DETECTION_ENABLED,
    CONF_ROUTINE_MIN_OBSERVATIONS,
)
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.event_runtime import SituationRuntime  # noqa: E402
from ha_nlu.runtime_data import HaNluRuntimeData  # noqa: E402
from ha_nlu.situation import RoutineStatistics, normalize_state_change  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


def test_state_event_is_normalized_and_signalled_at_most_once(monkeypatch):
    hass = HomeAssistant()
    agent = SimpleNamespace(async_signal=AsyncMock())
    runtime_data = HaNluRuntimeData(proactive_agent=agent)
    runtime = SituationRuntime(
        hass,
        ConfigEntry(options={CONF_AGENT_EVENT_CATEGORIES: "opening_while_away"}),
        runtime_data,
    )
    entity = EntitySnapshot(
        "binary_sensor.cellar_window",
        "Kellerfenster",
        "binary_sensor",
        "on",
        area_id="cellar",
        device_class="window",
    )
    monkeypatch.setattr(
        "ha_nlu.event_runtime.build_entity_snapshots", lambda *_: [entity]
    )
    raw = SimpleNamespace(
        data={
            "entity_id": entity.entity_id,
            "new_state": SimpleNamespace(state="on"),
            "old_state": SimpleNamespace(state="off"),
        },
        time_fired=datetime(2026, 9, 1, 23, tzinfo=timezone.utc),
    )

    async def scenario():
        await runtime.async_handle_state_changed(raw)
        await runtime.async_handle_state_changed(raw)

    asyncio.run(scenario())
    agent.async_signal.assert_awaited_once()
    payload = agent.async_signal.await_args.args[0]
    assert payload["mode"] == "inform"
    assert payload["source_entity_id"] == entity.entity_id


def test_listener_returns_unsubscribe_callback():
    hass = HomeAssistant()
    unsubscribe = object()
    listen = lambda event_type, callback: unsubscribe
    hass.bus = SimpleNamespace(async_listen=listen)
    runtime = SituationRuntime(hass, ConfigEntry(), HaNluRuntimeData())
    assert runtime.async_start() is unsubscribe


def test_night_opening_explains_presence_quality_and_history(monkeypatch):
    hass = HomeAssistant()
    agent = SimpleNamespace(async_signal=AsyncMock())
    runtime_data = HaNluRuntimeData(proactive_agent=agent)
    entry = ConfigEntry(
        options={
            CONF_AGENT_EVENT_CATEGORIES: "opening_while_away",
            CONF_ROUTINE_DETECTION_ENABLED: True,
            CONF_ROUTINE_MIN_OBSERVATIONS: 3,
        }
    )
    runtime = SituationRuntime(hass, entry, runtime_data)
    entity = EntitySnapshot(
        "binary_sensor.cellar_window",
        "Kellerfenster",
        "binary_sensor",
        "on",
        area_id="cellar",
        device_class="window",
    )
    monkeypatch.setattr("ha_nlu.event_runtime.build_entity_snapshots", lambda *_: [entity])
    stats = runtime_data.routine_statistics.setdefault(
        entity.entity_id,
        RoutineStatistics(minimum_observations=3),
    )
    for day in (1, 2, 3):
        stats.observe(
            normalize_state_change(
                entity,
                "off",
                occurred_at=datetime(2026, 8, day, 12, tzinfo=timezone.utc),
                occupied=True,
            )
        )
    raw = SimpleNamespace(
        data={
            "entity_id": entity.entity_id,
            "new_state": SimpleNamespace(state="on"),
            "old_state": SimpleNamespace(state="off"),
        },
        time_fired=datetime(2026, 9, 1, 23, tzinfo=timezone.utc),
    )
    asyncio.run(runtime.async_handle_state_changed(raw))
    payload = agent.async_signal.await_args.args[0]
    assert payload["mode"] == "inform"
    assert "Anwesenheit: niemand" in payload["message"]
    assert "Qualität: good" in payload["message"]
    assert "Historie:" in payload["message"]
    assert "Beobachtungen" in payload["message"]


def test_unoccupied_light_uses_central_decision_for_bounded_ask(monkeypatch):
    hass = HomeAssistant()
    agent = SimpleNamespace(async_signal=AsyncMock())
    runtime = SituationRuntime(
        hass,
        ConfigEntry(options={CONF_AGENT_EVENT_CATEGORIES: "light_unoccupied"}),
        HaNluRuntimeData(proactive_agent=agent),
    )
    light = EntitySnapshot(
        "light.cellar",
        "Kellerlicht",
        "light",
        "on",
        area_id="cellar",
        capabilities=frozenset({"TURN_OFF"}),
    )
    monkeypatch.setattr("ha_nlu.event_runtime.build_entity_snapshots", lambda *_: [light])
    raw = SimpleNamespace(
        data={
            "entity_id": light.entity_id,
            "new_state": SimpleNamespace(state="on"),
            "old_state": SimpleNamespace(state="off"),
        },
        time_fired=datetime(2026, 9, 1, 20, tzinfo=timezone.utc),
    )
    asyncio.run(runtime.async_handle_state_changed(raw))
    payload = agent.async_signal.await_args.args[0]
    assert payload["mode"] == "ask"
    assert payload["action_domain"] == "homeassistant"
    assert payload["action_service"] == "turn_off"
    assert payload["action_entity_id"] == light.entity_id
