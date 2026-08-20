"""HomeIntent V5 Teil 7/10 + Teil 8/10 (V5.26, V5.30-V5.32, V5.35, V5.36):
automation_executor.py's AutomationExecutor - the sole HA-persistence path
for a confirmed AutomationModel (read-modify-write automations.yaml, then
``automation.reload``, then record identity/metadata in the sidecar store -
all as one transaction, rolled back on any failure).

Needs the real ``homeassistant.core``/``homeassistant.util`` module names to
exist for this module's own top-level imports to succeed - installs
``tests/_ha_stub.py`` first, same reason every ``conversation.py``-importing
test file already does (see that stub's own docstring). Unlike those tests,
every actual file/service touchpoint here is mocked directly
(``yaml_util.load_yaml``/``dump``, both modules' own
``write_utf8_file_atomic`` bindings, ``hass.services.async_call``) so no
test in this file ever touches a real file or calls a real HA service -
task #70's explicit requirement for the executor's tests.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.automation_executor as automation_executor  # noqa: E402
import ha_nlu.automation_metadata_store as automation_metadata_store  # noqa: E402
from ha_nlu.automation_executor import AutomationExecutor  # noqa: E402

SAMPLE_CONFIG = {
    "alias": "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.",
    "triggers": [{"trigger": "state", "entity_id": "binary_sensor.kueche_fenster", "to": "on"}],
    "actions": [{"action": "homeassistant.turn_on", "target": {"entity_id": "light.kueche_licht"}}],
}


def _make_hass(config_dir: str = "/config") -> MagicMock:
    hass = MagicMock()
    # Joins parts like the real ``hass.config.path()`` - automations.yaml
    # and the metadata sidecar file must resolve to distinct paths, same as
    # in a real HA config dir.
    hass.config.path.side_effect = lambda *parts: "/".join([config_dir, *parts])

    async def _run_in_executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_run_in_executor)
    hass.services.async_call = AsyncMock()
    return hass


def _patch_metadata_write():
    """Every test in this file mocks the metadata sidecar's own write too -
    its read side already degrades to an empty dict on ``FileNotFoundError``
    (see ``AutomationMetadataStore._read``), so a real, harmless failed open()
    against the mocked hass's fake path needs no separate patch."""
    return patch.object(automation_metadata_store, "write_utf8_file_atomic")


def test_create_automation_appends_to_an_empty_file_and_returns_the_new_id():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]) as load_mock,
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml") as dump_mock,
        patch.object(automation_executor, "write_utf8_file_atomic") as write_mock,
        _patch_metadata_write(),
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
        _patch_metadata_write(),
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
        _patch_metadata_write(),
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
        _patch_metadata_write(),
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
        _patch_metadata_write(),
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
        _patch_metadata_write(),
    ):
        executor = AutomationExecutor(hass)
        asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    # 2 for automations.yaml (read+write) + 2 for the metadata sidecar
    # (read+write, V5.30/V5.31) - all four still off-event-loop.
    assert hass.async_add_executor_job.await_count == 4


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
        _patch_metadata_write(),
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


# --- V5.30/V5.31/V5.32: identity/metadata sidecar ---------------------------


def test_a_successful_creation_records_metadata_keyed_by_the_automation_id():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml"),
        patch.object(automation_executor, "write_utf8_file_atomic"),
        patch.object(automation_metadata_store, "write_utf8_file_atomic") as metadata_write_mock,
    ):
        executor = AutomationExecutor(hass)
        automation_id = asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    metadata_write_mock.assert_called_once()
    written_path, written_json = metadata_write_mock.call_args.args
    assert written_path == "/config/ha_nlu_automation_metadata.json"
    entries = json.loads(written_json)
    assert set(entries) == {automation_id}
    entry = entries[automation_id]
    assert entry["automation_id"] == automation_id
    assert entry["source_text"] == SAMPLE_CONFIG["alias"]
    assert entry["created_by"] == "homeintent"
    assert entry["version"] == 1
    assert entry["source_language"] == "de"
    assert "created_at" in entry and entry["created_at"]


# --- V5.35/V5.36: transactional creation with rollback -----------------------


def test_a_reload_failure_rolls_back_the_automations_yaml_write():
    hass = _make_hass()
    hass.services.async_call = AsyncMock(side_effect=RuntimeError("reload failed"))
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml") as dump_mock,
        patch.object(automation_executor, "write_utf8_file_atomic"),
        patch.object(automation_metadata_store, "write_utf8_file_atomic") as metadata_write_mock,
    ):
        executor = AutomationExecutor(hass)
        with pytest.raises(RuntimeError, match="reload failed"):
            asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    # First dump appended the new automation, second dump rolled back to the
    # empty list that was there before this call - the file must end up
    # exactly as if the call had never happened.
    assert [call.args[0] for call in dump_mock.call_args_list] == [
        [{"id": dump_mock.call_args_list[0].args[0][0]["id"], **SAMPLE_CONFIG}],
        [],
    ]
    # Metadata is only recorded after a successful reload - a failed reload
    # must never leave an orphaned metadata entry either.
    metadata_write_mock.assert_not_called()


def test_a_metadata_save_failure_rolls_back_the_yaml_write_and_reloads_again():
    hass = _make_hass()
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml") as dump_mock,
        patch.object(automation_executor, "write_utf8_file_atomic"),
        patch.object(
            automation_metadata_store, "write_utf8_file_atomic", side_effect=OSError("disk full")
        ),
    ):
        executor = AutomationExecutor(hass)
        with pytest.raises(OSError, match="disk full"):
            asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))

    # Rolled back to the empty list, same as the reload-failure case.
    assert [call.args[0] for call in dump_mock.call_args_list] == [
        [{"id": dump_mock.call_args_list[0].args[0][0]["id"], **SAMPLE_CONFIG}],
        [],
    ]
    # Reloaded once for the (now rolled-back) append, and a second time so
    # HA's live config matches the restored file - "no half-created
    # automations" (V5.36) applies to HA's in-memory state too, not just
    # the file on disk.
    assert hass.services.async_call.await_count == 2


def test_a_second_reload_failure_during_rollback_still_surfaces_the_original_error():
    hass = _make_hass()
    hass.services.async_call = AsyncMock(side_effect=[None, RuntimeError("reload #2 also failed")])
    with (
        patch.object(automation_executor.yaml_util, "load_yaml", return_value=[]),
        patch.object(automation_executor.yaml_util, "dump", return_value="dumped-yaml"),
        patch.object(automation_executor, "write_utf8_file_atomic"),
        patch.object(
            automation_metadata_store, "write_utf8_file_atomic", side_effect=OSError("disk full")
        ),
    ):
        executor = AutomationExecutor(hass)
        # The metadata failure is what the caller actually needs to see and
        # speak back to the user - a second, unrelated reload failure while
        # rolling back must not mask it.
        with pytest.raises(OSError, match="disk full"):
            asyncio.run(executor.async_create_automation(SAMPLE_CONFIG))
