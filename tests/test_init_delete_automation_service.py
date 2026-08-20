"""Wave 12 ("Einmalige Automation"): ``ha_nlu/__init__.py``'s
``ha_nlu.delete_automation`` custom service registration - the action step
a self-deleting generated automation calls on itself after it fires (see
``nlu/ha_automation_generator.py``'s ``generate_ha_automation_config()``
docstring).

Uses ``tests/_ha_stub.py``'s fake ``HomeAssistant``/``ConfigEntry`` the same
way ``tests/test_conversation_automation_toggle.py`` etc. already do -
registers the service through the real ``async_setup_entry()``, then
invokes the stored handler directly (mirroring how HA itself would dispatch
a real ``ha_nlu.delete_automation`` service call), asserting against the
real ``AutomationExecutor``/``automations.yaml`` round trip rather than a
second reimplementation of ``async_delete_automation()`` (already covered
in isolation by ``tests/test_automation_executor.py``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import yaml as pyyaml

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu as ha_nlu_init  # noqa: E402
from ha_nlu.const import DOMAIN  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant, ServiceCall  # noqa: E402


def _make_hass(tmp_path: Path) -> HomeAssistant:
    hass = HomeAssistant()
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    hass.config_entries = type(
        "FakeConfigEntries", (), {
            "async_forward_entry_setups": AsyncMock(),
            "async_unload_platforms": AsyncMock(return_value=True),
            "async_reload": AsyncMock(),
        },
    )()
    return hass


def _automations_yaml(tmp_path: Path) -> list[dict]:
    path = tmp_path / "automations.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as handle:
        return pyyaml.safe_load(handle) or []


def _write_automations_yaml(tmp_path: Path, automations: list[dict]) -> None:
    with open(tmp_path / "automations.yaml", "w", encoding="utf-8") as handle:
        pyyaml.safe_dump(automations, handle)


def test_async_setup_entry_registers_the_delete_automation_service(tmp_path):
    hass = _make_hass(tmp_path)
    entry = ConfigEntry()

    asyncio.run(ha_nlu_init.async_setup_entry(hass, entry))

    assert hass.services.has_service(DOMAIN, "delete_automation") is True


def test_async_setup_entry_does_not_double_register_the_service(tmp_path):
    hass = _make_hass(tmp_path)
    entry = ConfigEntry()

    asyncio.run(ha_nlu_init.async_setup_entry(hass, entry))
    handler_after_first = hass.services._handlers[(DOMAIN, "delete_automation")]
    asyncio.run(ha_nlu_init.async_setup_entry(hass, entry))
    handler_after_second = hass.services._handlers[(DOMAIN, "delete_automation")]

    assert handler_after_first is handler_after_second


def test_async_unload_entry_removes_the_service(tmp_path):
    hass = _make_hass(tmp_path)
    entry = ConfigEntry()
    asyncio.run(ha_nlu_init.async_setup_entry(hass, entry))
    assert hass.services.has_service(DOMAIN, "delete_automation") is True

    asyncio.run(ha_nlu_init.async_unload_entry(hass, entry))

    assert hass.services.has_service(DOMAIN, "delete_automation") is False


def test_calling_the_service_deletes_the_matching_automation(tmp_path):
    hass = _make_hass(tmp_path)
    entry = ConfigEntry()
    asyncio.run(ha_nlu_init.async_setup_entry(hass, entry))
    _write_automations_yaml(
        tmp_path,
        [
            {"id": "keep-me", "alias": "Bleibt", "triggers": [], "actions": []},
            {"id": "delete-me", "alias": "Wird gelöscht", "triggers": [], "actions": []},
        ],
    )

    handler = hass.services._handlers[(DOMAIN, "delete_automation")]
    asyncio.run(handler(ServiceCall({"automation_id": "delete-me"})))

    remaining = _automations_yaml(tmp_path)
    assert [a["id"] for a in remaining] == ["keep-me"]
    hass.services.async_call.assert_awaited_once_with("automation", "reload", {}, blocking=True)


def test_calling_the_service_for_an_already_gone_automation_id_does_not_raise(tmp_path):
    hass = _make_hass(tmp_path)
    entry = ConfigEntry()
    asyncio.run(ha_nlu_init.async_setup_entry(hass, entry))
    _write_automations_yaml(tmp_path, [{"id": "still-here", "alias": "x", "triggers": [], "actions": []}])

    handler = hass.services._handlers[(DOMAIN, "delete_automation")]
    # Must not raise even though "already-gone" was never in the file -
    # the documented ValueError race is swallowed (see __init__.py's
    # _async_delete_automation docstring).
    asyncio.run(handler(ServiceCall({"automation_id": "already-gone"})))

    remaining = _automations_yaml(tmp_path)
    assert [a["id"] for a in remaining] == ["still-here"]


def test_calling_the_service_without_an_automation_id_is_a_no_op(tmp_path):
    hass = _make_hass(tmp_path)
    entry = ConfigEntry()
    asyncio.run(ha_nlu_init.async_setup_entry(hass, entry))
    _write_automations_yaml(tmp_path, [{"id": "still-here", "alias": "x", "triggers": [], "actions": []}])

    handler = hass.services._handlers[(DOMAIN, "delete_automation")]
    asyncio.run(handler(ServiceCall({})))

    remaining = _automations_yaml(tmp_path)
    assert [a["id"] for a in remaining] == ["still-here"]
