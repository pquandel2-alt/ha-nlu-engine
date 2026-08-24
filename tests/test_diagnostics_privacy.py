from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from ha_nlu.diagnostics import async_get_config_entry_diagnostics  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


def test_diagnostics_expose_policy_facts_but_no_entity_ids_or_text():
    entry = ConfigEntry(
        options={
            "selected_entities": ["light.secret", "sensor.private"],
            "read_only_entities": ["sensor.private"],
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
    assert diagnostics["confirmation_level"] == "medium"
    assert diagnostics["max_action_targets"] == 12
    assert diagnostics["context_ttl_seconds"] == 90
    serialized = repr(diagnostics)
    assert "light.secret" not in serialized
    assert "sensor.private" not in serialized
