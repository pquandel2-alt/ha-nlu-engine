"""Validate HomeIntent's critical one-shot YAML against real HA schemas."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from homeassistant.components.automation.config import PLATFORM_SCHEMA

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionModel, ActionType
from ha_nlu.nlu.automation_model import AutomationModel, TriggerModel, TriggerTarget, TriggerType
from ha_nlu.nlu.ha_automation_generator import generate_ha_automation_config


entity = EntitySnapshot(
    "cover.buero_rollladen",
    "Rollladen Büro",
    "cover",
    "closed",
    capabilities=frozenset({"POSITION"}),
)
model = AutomationModel(
    triggers=(
        TriggerModel(
            type=TriggerType.TIME,
            time_hour=12,
            time_minute=5,
            time_second=30,
        ),
    ),
    actions=(
        ActionModel(
            type=ActionType.SET_POSITION,
            target=TriggerTarget(entity_id=entity.entity_id),
            value=50,
        ),
    ),
    source_text="Fahre in 30 Sekunden die Rolllade im Büro auf 50 Prozent",
    once=True,
    scheduled_for=datetime(2026, 8, 21, 12, 5, 30, tzinfo=timezone.utc),
)
result = generate_ha_automation_config(
    model, [entity], automation_id="homeintent-schema-smoke"
)
if result.error is not None or result.config is None:
    raise RuntimeError(f"HomeIntent generation failed: {result.error}")


async def _validate() -> None:
    """Run schema validation in the event-loop context required by HA templates."""
    PLATFORM_SCHEMA({"id": "homeintent-schema-smoke", **result.config})


asyncio.run(_validate())
print("HOME_ASSISTANT_AUTOMATION_SCHEMA_OK")
