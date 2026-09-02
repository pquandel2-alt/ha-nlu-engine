from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.service_call import ServiceCallPlan  # noqa: E402
from ha_nlu.service_executor import async_execute_service_plan  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


def test_service_executor_never_allows_data_to_replace_validated_target():
    hass = HomeAssistant()
    entity = EntitySnapshot("switch.allowed", "Freigegeben", "switch", "on")
    plan = ServiceCallPlan(
        "homeassistant",
        "turn_off",
        entity.entity_id,
        {"entity_id": "switch.hidden"},
    )

    result = asyncio.run(
        async_execute_service_plan(
            hass,
            plan,
            [entity],
            {},
            is_admin=False,
            user_id=None,
            confirmed=True,
        )
    )

    assert result.executed is False
    assert "validierte Ziel" in (result.error or "")
    hass.services.async_call.assert_not_awaited()


def test_service_executor_keeps_the_validated_target_authoritative():
    hass = HomeAssistant()
    entity = EntitySnapshot("switch.allowed", "Freigegeben", "switch", "on")
    plan = ServiceCallPlan("homeassistant", "turn_off", entity.entity_id)

    result = asyncio.run(
        async_execute_service_plan(
            hass,
            plan,
            [entity],
            {},
            is_admin=False,
            user_id=None,
            confirmed=True,
        )
    )

    assert result.executed is True
    hass.services.async_call.assert_awaited_once_with(
        "homeassistant", "turn_off", {"entity_id": "switch.allowed"}, blocking=True
    )


def test_service_executor_rejects_unavailable_fresh_snapshot():
    hass = HomeAssistant()
    entity = EntitySnapshot("switch.allowed", "Freigegeben", "switch", "unavailable")
    result = asyncio.run(
        async_execute_service_plan(
            hass,
            ServiceCallPlan("homeassistant", "turn_off", entity.entity_id),
            [entity],
            {},
            is_admin=False,
            user_id=None,
            confirmed=True,
        )
    )
    assert not result.executed
    hass.services.async_call.assert_not_awaited()


def test_service_executor_rechecks_capability_when_snapshot_reports_it():
    hass = HomeAssistant()
    entity = EntitySnapshot(
        "switch.allowed", "Freigegeben", "switch", "on",
        capabilities=frozenset({"TURN_ON"}),
    )
    result = asyncio.run(
        async_execute_service_plan(
            hass,
            ServiceCallPlan("homeassistant", "turn_off", entity.entity_id),
            [entity],
            {},
            is_admin=False,
            user_id=None,
            confirmed=True,
        )
    )
    assert not result.executed
    assert "nicht mehr" in (result.error or "")
    hass.services.async_call.assert_not_awaited()


def test_brightness_rechecks_turn_on_and_brightness_capabilities():
    hass = HomeAssistant()
    entity = EntitySnapshot(
        "light.allowed", "Lampe", "light", "off",
        capabilities=frozenset({"TURN_ON"}),
    )
    result = asyncio.run(
        async_execute_service_plan(
            hass,
            ServiceCallPlan(
                "light", "turn_on", entity.entity_id, {"brightness_pct": 30}
            ),
            [entity],
            {},
            is_admin=False,
            user_id=None,
            confirmed=True,
        )
    )
    assert not result.executed
    hass.services.async_call.assert_not_awaited()
