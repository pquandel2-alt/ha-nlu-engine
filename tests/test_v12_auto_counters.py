"""7.0.1: auto-execution counters tell the truth.

Every automatic V10 run is an *attempt*; only a verified effect is an
*execution*.  The daily safety budget (``max_executions_per_day``, stored name
kept for compatibility) conservatively counts attempts, so rejected,
unverified, stale or conflicting runs can never retry without bound.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from v12_harness import NOW
from test_v12_behavior import _leave_with_light_on, _leaving_world, _permission

from homeintent.proactive_execution import ProactiveExecutionStatus
from homeintent.standing_permission import StandingPermissionStore


def _world(tmp_path, **permission):
    world = _leaving_world(tmp_path)
    world.engine.permissions.add(_permission(**permission))
    return world


def _counts(world, at):
    permissions = world.engine.permissions
    return (
        world.engine.counters.auto_attempts,
        world.engine.counters.auto_verified_executions,
        permissions.attempts_today("perm_1", at),
        permissions.verified_executions_today("perm_1", at),
    )


def _auto_outcomes(world) -> list[str]:
    return [item.result for item in world.engine.history.records() if item.result.startswith("auto_")]


def test_verified_success_counts_one_attempt_and_one_execution(tmp_path):
    world = _world(tmp_path)

    async def scenario():
        await _leave_with_light_on(world)
        assert len(world.sink.device_calls) == 1
        assert _counts(world, world.ports.clock) == (1, 1, 1, 1)
        assert _auto_outcomes(world) == ["auto_executed"]

    asyncio.run(scenario())


def test_service_rejection_is_an_attempt_not_an_execution(tmp_path):
    world = _world(tmp_path)
    world.sink.fail_entities.add("light.living")

    async def scenario():
        await _leave_with_light_on(world)
        assert len(world.sink.device_calls) == 1
        assert world.ports.states["light.living"].state == "on"
        assert _counts(world, world.ports.clock) == (1, 0, 1, 0)
        assert _auto_outcomes(world)[-1] in {"auto_failed", "auto_blocked"}

    asyncio.run(scenario())


def test_effect_verification_failure_is_an_attempt_not_an_execution(tmp_path):
    world = _world(tmp_path)
    world.sink.no_effect_entities.add("light.living")

    async def scenario():
        await _leave_with_light_on(world)
        assert len(world.sink.device_calls) == 1
        assert _counts(world, world.ports.clock) == (1, 0, 1, 0)
        assert _auto_outcomes(world)[-1] == "auto_failed"

    asyncio.run(scenario())


def test_stale_state_is_an_attempt_not_an_execution(tmp_path):
    world = _world(tmp_path)
    runner = world.engine.runner
    original = runner.async_execute

    async def raced(*args, **kwargs):
        # Someone switches the light off between the engine's check and V10.
        world.ports.states["light.living"] = replace(world.ports.states["light.living"], state="off")
        return await original(*args, **kwargs)

    runner.async_execute = raced  # type: ignore[method-assign]

    async def scenario():
        await _leave_with_light_on(world)
        assert world.sink.device_calls == []
        assert _counts(world, world.ports.clock) == (1, 0, 1, 0)
        assert _auto_outcomes(world)[-1] == f"auto_{ProactiveExecutionStatus.STALE.value}"

    asyncio.run(scenario())


def test_conflict_is_an_attempt_not_an_execution(tmp_path):
    world = _world(tmp_path)
    # Another V10 run currently owns the target.
    world.engine.runner._coordinator._owners["light.living"] = "run_other"

    async def scenario():
        await _leave_with_light_on(world)
        assert world.sink.device_calls == []
        assert _counts(world, world.ports.clock) == (1, 0, 1, 0)
        assert _auto_outcomes(world)[-1] == f"auto_{ProactiveExecutionStatus.CONFLICT.value}"

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["fail_entities", "no_effect_entities"])
def test_failed_attempts_consume_the_daily_budget(tmp_path, failure):
    world = _world(tmp_path, max_executions_per_day=2)
    getattr(world.sink, failure).add("light.living")

    async def scenario():
        for _ in range(4):
            await world.person("person.philipp", "home")
            await world.change("light.living", "off")
            await _leave_with_light_on(world)
        # Two attempts, then the budget refuses; never an unbounded retry.
        assert len(world.sink.device_calls) == 2
        assert _counts(world, world.ports.clock) == (2, 0, 2, 0)
        assert any("daily_attempt_limit" in item.reasons for item in world.engine.history.records())

    asyncio.run(scenario())


def test_legacy_executions_are_read_as_attempts_and_round_trip():
    legacy = StandingPermissionStore()
    legacy.add(_permission())
    document = legacy.to_dict()
    document["executions"] = {"perm_1": [NOW.isoformat(), (NOW + timedelta(minutes=1)).isoformat()]}
    document.pop("verified_executions")
    store = StandingPermissionStore.from_dict(document)
    at = NOW + timedelta(hours=1)
    assert store.attempts_today("perm_1", at) == 2
    assert store.verified_executions_today("perm_1", at) == 0
    store.record_attempt("perm_1", at, verified=True)
    again = StandingPermissionStore.from_dict(store.to_dict())
    assert (again.attempts_today("perm_1", at), again.verified_executions_today("perm_1", at)) == (3, 1)
    # A 7.0.0 reader sees every attempt under the key it already enforces.
    assert len(again.to_dict()["executions"]["perm_1"]) == 3  # type: ignore[index]
