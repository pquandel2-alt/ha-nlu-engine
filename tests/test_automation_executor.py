"""HomeIntent V5 Teil 7/10 (V5.26): automation_executor.py's
AutomationExecutor - the sole HA-persistence path for a confirmed
AutomationModel (read-modify-write automations.yaml, then
``automation.reload``).

Needs the real ``homeassistant.core``/``homeassistant.util`` module names to
exist for this module's own top-level imports to succeed - installs
``tests/_ha_stub.py`` first, same reason every ``conversation.py``-importing
test file already does (see that stub's own docstring). Unlike those tests,
every actual file/service touchpoint here is mocked directly
(``yaml_util.load_yaml``/``dump``, ``write_utf8_file_atomic``,
``hass.services.async_call``) so no test in this file ever touches a real
file or calls a real HA service - task #70's explicit requirement for the
executor's tests.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.automation_executor as automation_executor  # noqa: E402
from ha_nlu.automation_executor import AutomationExecutor  # noqa: E402

SAMPLE_CONFIG = {
    "alias": "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.",
    "triggers": [{"trigger": "state", "entity_id": "binary_sensor.kueche_fenster", "to": "on"}],
    "actions": [{"action": "homeassistant.turn_on", "target": {"entity_id": "light.kueche_licht"}}],
}


def _make_hass(config_path: str = "/config/automations.yaml") -> MagicMock:
    hass = MagicMock()
    hass.config.path.return_value = config_path

    async def _run_in_executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_run_in_executor)
    hass.services.async_call = AsyncMock()
    return hass


def test_create_automation_appends_to_an_empty_file_and_returns_the_new_id():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]) as load_mock,
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml") as dump_mock,
        patch.object(automation_executor, "write_utf8_file_atomic") as write_mock,
    ):
        executor = AutomationExecutor(hass)
        automation_id = asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    assert isinstance(automation_id, str) and automation_id
    load_mock.assert_called_once_with("/config/automations.yaml")
    dump_mock.assert_called_once()
    written_automations = dump_mock.call_args.args[0]
    assert written_automations == [{"id": automation_id, **SAMPLE_CONFIG}]
    write_mock.assert_called_once_with("/config/automations.yaml", "dumped-yaml")


def test_create_automation_appends_to_an_existing_non_empty_file():
    hass = _make_hass()
    existing = [{"id": "abc123", "alias": "Bestehende Automation", "triggers": [], "actions": []}]
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=list(existing)),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml") as dump_mock,
        patch.object(automation_executor, "write_utf8_file_atomic"),
    ):
        executor = AutomationExecutor(hass)
        automation_id = asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    written_automations = dump_mock.call_args.args[0]
    assert len(written_automations) == 2
    assert written_automations[0] == existing[0]
    assert written_automations[1] == {"id": automation_id, **SAMPLE_CONFIG}


def test_a_missing_automations_yaml_is_treated_as_an_empty_list_not_an_error():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", side_effect=FileNotFoundError),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml") as dump_mock,
        patch.object(automation_executor, "write_utf8_file_atomic"),
    ):
        executor = AutomationExecutor(hass)
        asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    written_automations = dump_mock.call_args.args[0]
    assert len(written_automations) == 1


def test_create_automation_calls_automation_reload_with_no_arguments():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml"),
        patch.object(automation_executor, "write_utf8_file_atomic"),
    ):
        executor = AutomationExecutor(hass)
        asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    hass.services.async_call.assert_awaited_once_with("automation", "reload", {}, blocking=True)


def test_each_created_automation_gets_a_distinct_id():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml"),
        patch.object(automation_executor, "write_utf8_file_atomic"),
    ):
        executor = AutomationExecutor(hass)
        first_id = asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))
        second_id = asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    assert first_id != second_id


def test_file_io_runs_via_async_add_executor_job_not_directly_on_the_event_loop():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml"),
        patch.object(automation_executor, "write_utf8_file_atomic"),
    ):
        executor = AutomationExecutor(hass)
        asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    assert hass.async_add_executor_job.await_count == 2


def test_two_concurrent_creations_are_serialized_by_the_instance_lock():
    hass = _make_hass()
    call_order: list[str] = []
    state: list[dict] = []

    def fake_load(path):
        call_order.append("read")
        return list(state)

    def fake_write(automations):
        call_order.append("write")
        state[:] = automations
        return "dumped-yaml"

    async def _run_in_executor_with_a_real_suspension_point(func, *args):
        # A plain synchronous side_effect never actually yields to the event
        # loop, so both tasks would run start-to-finish back to back even
        # without the lock - this ``asyncio.sleep(0)`` forces a genuine
        # task switch after the read, so the test can actually distinguish
        # "the lock serializes read+write" from "asyncio just happened not
        # to interleave them".
        await asyncio.sleep(0)
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_run_in_executor_with_a_real_suspension_point)

    with (
        patch.object(automation_executor.yaml_util, "load_yaml", side_effect=fake_load),
        patch.object(automation_executor.yaml_util, "dump", side_effect=fake_write),
        patch.object(automation_executor, "write_utf8_file_atomic"),
    ):
        executor = AutomationExecutor(hass)

        async def _run_both():
            await asyncio.gather(
                executor.async_create_automation(SAMPLE_CONFIG),
                executor.async_create_automation(SAMPLE_CONFIG),
            )

        asyncio.run(_run_both())

    # Each creation's read must be immediately followed by its own write -
    # a race (both reads before either write) would produce ["read", "read",
    # "write", "write"] and silently drop one automation.
    assert call_order == ["read", "write", "read", "write"]
    assert len(state) == 2
