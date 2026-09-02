from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from ha_nlu.diagnostics import async_get_config_entry_diagnostics  # noqa: E402
from ha_nlu.house_graph import FactProvenance  # noqa: E402
from ha_nlu.memory import MemoryKind, MemoryStore  # noqa: E402
from ha_nlu.runtime_data import HaNluRuntimeData  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


def test_diagnostics_expose_policy_facts_but_no_entity_ids_or_text():
    entry = ConfigEntry(
        options={
            "selected_entities": ["light.secret", "sensor.private"],
            "read_only_entities": ["sensor.private"],
            "admin_only_entities": ["light.secret"],
            "control_user_ids": ["private-user-id"],
            "custom_aliases": "Geheimlicht = light.secret",
            "confirmation_level": "medium",
            "max_action_targets": 12,
            "allow_non_admin_critical": False,
            "allow_non_admin_automations": False,
            "context_ttl_seconds": 90,
        }
    )
    entry.version = 1

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(HomeAssistant(), entry)
    )

    assert diagnostics["selected_entity_count"] == 2
    assert diagnostics["read_only_entity_count"] == 1
    assert diagnostics["admin_only_entity_count"] == 1
    assert diagnostics["control_user_count"] == 1
    assert diagnostics["custom_alias_count"] == 1
    assert diagnostics["confirmation_level"] == "medium"
    assert diagnostics["max_action_targets"] == 12
    assert diagnostics["context_ttl_seconds"] == 90
    serialized = repr(diagnostics)
    assert "light.secret" not in serialized
    assert "sensor.private" not in serialized
    assert "private-user-id" not in serialized
    assert "Geheimlicht" not in serialized


def test_diagnostics_show_only_redacted_learned_counts(tmp_path):
    entry = ConfigEntry(options={"memory_enabled": True})
    entry.version = 1
    memory = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    asyncio.run(
        memory.async_remember(
            MemoryKind.PREFERENCE,
            {"entity_id": "light.secret", "brightness_percent": 30},
            provenance=FactProvenance.CONFIRMED_MEMORY,
            confirmed=True,
            person_id="private-user",
        )
    )
    entry.runtime_data = HaNluRuntimeData(memory=memory)
    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(HomeAssistant(), entry)
    )
    assert diagnostics["learned_memory"]["record_counts"] == {"preference": 1}
    serialized = repr(diagnostics)
    assert "light.secret" not in serialized
    assert "private-user" not in serialized
    assert "brightness_percent" not in serialized
