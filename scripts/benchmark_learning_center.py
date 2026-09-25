#!/usr/bin/env python3
"""7.1 Learning Center latency budgets near the configured model limit.

Builds a REAL ``ModelRegistry`` filled to ``model_limit`` (1000 models of
every productive kind, personal ones spread over several users) and a full
``ExperienceStore`` (5000 records), then measures the read paths the panel
uses: summary, list, detail and (explicitly requested, bounded) evidence.

It also proves summary/list never touch the ExperienceStore.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from homeintent.experience import (  # noqa: E402
    ExperienceAction,
    ExperienceContext,
    ExperienceEffect,
    ExperienceProvenance,
    ExperienceQuality,
    ExperienceRecord,
)
from homeintent.experience_store import ExperienceStore  # noqa: E402
from homeintent.goal_run import EffectEvidenceState  # noqa: E402
from homeintent.learning_center import (  # noqa: E402
    LearningCenterService,
    LearningCenterSources,
    StaticLabels,
    Viewer,
    model_ref,
)
from homeintent.learning_policy import KnowledgeState, LearningMode, LearningPolicy  # noqa: E402
from homeintent.model_registry import LearnedKind, LearnedModel, ModelHealth, ModelRegistry  # noqa: E402

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
USERS = tuple(f"user_{index}" for index in range(6))


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


class _CountingStore(ExperienceStore):
    reads = 0

    def _read(self):  # type: ignore[override]
        type(self).reads += 1
        return super()._read()


async def _build(root: Path, policy: LearningPolicy) -> tuple[ModelRegistry, _CountingStore, StaticLabels]:
    registry = ModelRegistry(root / "models.json", policy)
    experiences = _CountingStore(root / "experiences.json", policy)
    entities = {f"light.l{index}": f"Licht {index}" for index in range(400)}
    records = []
    for index in range(policy.experience_limit):
        entity_id = f"light.l{index % 400}"
        records.append(ExperienceRecord(
            f"exp{index}", NOW - timedelta(minutes=index), f"g{index}", f"r{index}",
            ExperienceContext(entity_id=entity_id, domain="light"),
            ExperienceAction("LIGHT_TURN_ON", entity_id), {}, {},
            ExperienceEffect("on", "on", 1.5, True, EffectEvidenceState.VERIFIED_SUCCESS),
            (), ExperienceProvenance.GOAL_RUN, ExperienceQuality.COMPLETE,
        ))
    await asyncio.to_thread(experiences._write, records)
    models = []
    for index in range(policy.model_limit):
        entity_id = f"light.l{index % 400}"
        kind = (LearnedKind.RELIABILITY, LearnedKind.EFFECT_TIMING, LearnedKind.PREFERENCE,
                LearnedKind.HABIT, LearnedKind.THERMAL_MODEL)[index % 5]
        owner = USERS[index % len(USERS)]
        parameters: dict[str, str | float | int | bool] = {
            LearnedKind.RELIABILITY: {"success_rate": 0.9},
            LearnedKind.EFFECT_TIMING: {"median_seconds": 1.5, "p90_seconds": 2.0, "p95_seconds": 2.5, "mad_seconds": 0.2},
            LearnedKind.PREFERENCE: {"entity_id": entity_id, f"count:{entity_id}": 9, "support_count": 9, "suggestion_status": "new"},
            LearnedKind.HABIT: {"sequence": f"LIGHT_TURN_ON@{entity_id}=on|LIGHT_TURN_OFF@light.l1=off", "opportunity_count": 12, "support": 0.8, "suggestion_status": "new"},
            LearnedKind.THERMAL_MODEL: {"climate_entity_id": "climate.x", "temperature_entity_id": "sensor.x"},
        }[kind]
        context: dict[str, str | float | int | bool] = (
            {"operator_id": "LIGHT_TURN_ON"} if kind in {LearnedKind.RELIABILITY, LearnedKind.EFFECT_TIMING}
            else {"user_id": owner, "area_id": "living"} if kind is LearnedKind.PREFERENCE
            else {"time_band": "morning"} if kind is LearnedKind.HABIT
            else {"area_id": f"area{index}"}
        )
        subject = owner if kind is LearnedKind.HABIT else entity_id if kind in {
            LearnedKind.RELIABILITY, LearnedKind.EFFECT_TIMING} else "lampe"
        models.append(LearnedModel(
            f"{kind.value}:{index}", kind, subject, context, parameters,
            KnowledgeState.INFERRED if kind in {LearnedKind.PREFERENCE, LearnedKind.HABIT} else KnowledgeState.OBSERVED,
            0.8, 20, NOW - timedelta(days=30), NOW - timedelta(minutes=index),
            tuple(f"exp{item}" for item in range(index, index + 100)),
            health=ModelHealth.VALID,
        ))
    await registry.async_upsert_many(models)
    return registry, experiences, StaticLabels(entities, {"living": "Wohnzimmer"}, {user: user for user in USERS})


async def _measure(iterations: int) -> dict[str, float]:
    policy = LearningPolicy(learning_mode=LearningMode.ASK, predictive_models_enabled=True,
                            habit_discovery_enabled=True)
    with tempfile.TemporaryDirectory() as directory:
        registry, experiences, labels = await _build(Path(directory), policy)
        assert len(await registry.async_list()) == policy.model_limit
        sources = LearningCenterSources(registry, policy, experiences, None, None)
        viewer = Viewer(USERS[0], False)
        admin = Viewer("admin", True)
        target = next(model for model in await registry.async_list() if model.kind is LearnedKind.RELIABILITY)
        ref = model_ref(target.model_id)
        timings: dict[str, list[float]] = {"summary": [], "list": [], "detail": [], "evidence": []}
        reads_before = _CountingStore.reads
        for index in range(iterations):
            who = admin if index % 2 else viewer
            service = LearningCenterService("entry", sources, labels, now=NOW)
            start = time.perf_counter()
            (await service.async_summary(who)).to_dict()
            timings["summary"].append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            items, _total, _next = await service.async_list(who, limit=250)
            [item.to_dict() for item in items]
            timings["list"].append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            model = await service.async_resolve(ref, who)
            service.detail(model, who).to_dict()
            timings["detail"].append((time.perf_counter() - start) * 1000)
        if _CountingStore.reads != reads_before:
            raise SystemExit("summary/list/detail read the ExperienceStore")
        for _ in range(max(5, iterations // 10)):
            service = LearningCenterService("entry", sources, labels, now=NOW)
            start = time.perf_counter()
            model = await service.async_resolve(ref, admin)
            evidence = await service.async_evidence(model, admin, limit=50)
            timings["evidence"].append((time.perf_counter() - start) * 1000)
            assert len(evidence.rows) <= 50
        return {name: _p95(values) for name, values in timings.items()} | {
            f"{name}_median": statistics.median(values) for name, values in timings.items()
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--max-summary-ms", type=float, default=100.0)
    parser.add_argument("--max-list-ms", type=float, default=150.0)
    parser.add_argument("--max-detail-ms", type=float, default=150.0)
    parser.add_argument("--max-evidence-ms", type=float, default=400.0)
    args = parser.parse_args()
    result = asyncio.run(_measure(args.iterations))
    for name in ("summary", "list", "detail", "evidence"):
        print(f"{name:9s} p95 {result[name]:7.2f} ms   median {result[name + '_median']:7.2f} ms")
    budgets = {
        "summary": args.max_summary_ms, "list": args.max_list_ms,
        "detail": args.max_detail_ms, "evidence": args.max_evidence_ms,
    }
    failed = [name for name, budget in budgets.items() if result[name] > budget]
    if failed:
        print(f"Budget exceeded: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
