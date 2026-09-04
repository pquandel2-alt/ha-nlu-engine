from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from ha_nlu.effect_monitor import EffectMonitor  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.service_call import ServiceCallPlan  # noqa: E402
from ha_nlu.service_executor import async_execute_service_plan  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


def test_observed_effect_cancels_deadline():
    async def scenario():
        handler = AsyncMock()
        monitor = EffectMonitor(timeout=timedelta(milliseconds=10))
        monitor.set_expired_handler(handler)
        monitor.register(ServiceCallPlan("light", "turn_off", "light.office"))
        assert monitor.observe("light.office", "off")
        await asyncio.sleep(0.02)
        assert monitor.pending == ()
        handler.assert_not_awaited()
        await monitor.async_close()

    asyncio.run(scenario())


def test_expired_effect_is_reported_exactly_once():
    async def scenario():
        handler = AsyncMock()
        monitor = EffectMonitor(timeout=timedelta(milliseconds=5))
        monitor.set_expired_handler(handler)
        monitor.register(ServiceCallPlan("light", "turn_on", "light.office"))
        await asyncio.sleep(0.02)
        handler.assert_awaited_once()
        assert monitor.pending == ()
        await monitor.async_close()

    asyncio.run(scenario())


def test_new_expectation_replaces_previous_one_per_entity():
    async def scenario():
        monitor = EffectMonitor(timeout=timedelta(seconds=1))
        monitor.register(ServiceCallPlan("light", "turn_on", "light.office"))
        monitor.register(ServiceCallPlan("light", "turn_off", "light.office"))
        assert len(monitor.pending) == 1
        assert monitor.pending[0].expected_state == "off"
        await monitor.async_close()
        assert monitor.pending == ()

    asyncio.run(scenario())


def test_executor_registers_only_successful_known_effect():
    async def scenario():
        hass = HomeAssistant()
        monitor = EffectMonitor(timeout=timedelta(seconds=1))
        entity = EntitySnapshot("light.office", "Bürolicht", "light", "on")
        successful = await async_execute_service_plan(
            hass,
            ServiceCallPlan("light", "turn_off", entity.entity_id),
            [entity],
            {},
            is_admin=False,
            user_id=None,
            confirmed=True,
            effect_monitor=monitor,
        )
        assert successful.executed
        assert len(monitor.pending) == 1
        hass.services.async_call.side_effect = RuntimeError("offline")
        failed = await async_execute_service_plan(
            hass,
            ServiceCallPlan("light", "turn_on", entity.entity_id),
            [entity],
            {},
            is_admin=False,
            user_id=None,
            confirmed=True,
            effect_monitor=monitor,
        )
        assert not failed.executed
        assert monitor.pending[0].expected_state == "off"
        await monitor.async_close()

    asyncio.run(scenario())
