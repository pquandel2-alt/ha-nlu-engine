"""Emit real Learning Center WebSocket responses for the mobile UI check.

Drives the REAL backend (ModelRegistry, LearningManager, V12 stores) through
the test harness dispatcher and writes ``{command: response}`` as JSON, so
the browser check renders exactly the backend's typed contract.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from learning_center_harness import (  # noqa: E402
    ADMIN, NOW, USER_A, habit_model, learn_reliability, make_env, preference_model,
    standing_permission, thermal_model,
)
from homeintent.model_registry import ModelHealth  # noqa: E402
from homeintent.proactive_model import (  # noqa: E402
    CommunicationChannel, HistoryRecord, OpportunityOutcome, PriorityLevel, PrivacyLevel,
    SituationKind,
)


async def main(target: Path) -> None:
    tmp = Path(tempfile.mkdtemp())
    env = await make_env(tmp)
    await learn_reliability(env, successes=18, failures=1)
    await env.registry.async_upsert(thermal_model(health=ModelHealth.DRIFT_DETECTED))
    await env.registry.async_upsert(preference_model(ADMIN))
    await env.registry.async_upsert(habit_model(ADMIN))
    await env.registry.async_upsert(habit_model(USER_A, suffix="other"))
    long_entity = "light." + "sehr_langer_technischer_entitaetsname_" * 3
    env.hass.states._states.pop(long_entity, None)
    await learn_reliability(env, successes=3, failures=0, entity_id=long_entity)
    env.engine.permissions.add(standing_permission(ADMIN, expires_in=timedelta(days=5)))
    env.engine.attention_state.mute(ADMIN, SituationKind.ENTRY_LEFT_OPEN, NOW)
    for index in range(45):
        env.engine.history.append(HistoryRecord(
            f"h{index}", f"s{index}", SituationKind.ENTRY_LEFT_OPEN, "Garagentor",
            OpportunityOutcome.COMMUNICATE, ADMIN, CommunicationChannel.PUSH,
            NOW - timedelta(minutes=index * 7), PriorityLevel.IMPORTANT, PrivacyLevel.HOUSEHOLD,
            "delivered", ("attention_budget_exhausted",), None, None,
        ))
    out: dict[str, object] = {}
    for command in ("entries", "summary", "models/list", "permissions/list", "mutes/list",
                    "history/list", "tombstones/list"):
        result, error = await env.call(ADMIN, command)
        assert error is None, (command, error)
        out[command] = result
    for model in out["models/list"]["models"]:  # type: ignore[index]
        ref = model["ref"]
        detail, _ = await env.call(ADMIN, "models/get", ref=ref)
        out[f"models/get:{ref}"] = detail
        evidence, error = await env.call(ADMIN, "models/evidence", ref=ref)
        if error is None:
            out[f"models/evidence:{ref}"] = evidence
        preview, error = await env.call(ADMIN, "habits/preview", ref=ref)
        if error is None:
            out[f"habits/preview:{ref}"] = preview
    target.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
