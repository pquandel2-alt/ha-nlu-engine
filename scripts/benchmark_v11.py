#!/usr/bin/env python3
"""Deterministic V11 lookup/prediction microbenchmarks."""

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

from homeintent.learning_policy import LearningMode, LearningPolicy  # noqa: E402
from homeintent.learning_policy import KnowledgeState  # noqa: E402
from homeintent.model_registry import (  # noqa: E402
    LearnedKind,
    LearnedModel,
    ModelHealth,
    ModelRegistry,
    explain_learned_model,
)
from homeintent.experience import (  # noqa: E402
    ExperienceAction,
    ExperienceContext,
    ExperienceEffect,
    ExperienceProvenance,
    ExperienceQuality,
    ExperienceRecord,
)
from homeintent.experience_store import ExperienceStore  # noqa: E402
from homeintent.habit_discovery import (  # noqa: E402
    HabitSequenceObservation,
    discover_habit,
)
from homeintent.preferences import (  # noqa: E402
    PreferenceContext,
    infer_preference,
)
from homeintent.adaptive_planning import advise_deadline_goal  # noqa: E402
from homeintent.goal_model import (  # noqa: E402
    GoalKind,
    GoalModel,
    TemporalGoal,
)
from homeintent.predictive_house_model import PredictiveHouseModel  # noqa: E402
from homeintent.statistical_models import (  # noqa: E402
    evaluate_latency_anomaly,
    train_effect_timing,
    train_reliability,
)
from homeintent.thermal_model import (  # noqa: E402
    ThermalBinding,
    ThermalObservation,
    train_thermal_model,
)


def _p95(values: list[float]) -> float:
    return sorted(values)[max(0, int(len(values) * 0.95) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1_000)
    parser.add_argument("--max-p95-ms", type=float, default=100.0)
    args = parser.parse_args()
    policy = LearningPolicy(
        learning_mode=LearningMode.SILENT_LEARN,
        predictive_models_enabled=True,
        habit_discovery_enabled=True,
    )
    now = datetime.now(timezone.utc)
    observations = tuple(
        ThermalObservation(
            now - timedelta(days=index + 1),
            now - timedelta(days=index + 1, seconds=-(2_850 + index % 5 * 10)),
            "living", "sensor.living_temp", "climate.living", 19.0, 21.0,
            2_850 + index % 5 * 10, True,
        )
        for index in range(20)
    )
    model = train_thermal_model(
        ThermalBinding("living", "sensor.living_temp", "climate.living", confirmed=True),
        observations, policy, now=now,
    )
    if model is None:
        raise RuntimeError("benchmark fixture failed to train")
    house = PredictiveHouseModel(policy)
    house.install_thermal(model)
    timing = train_effect_timing(
        "cover.close", "cover.garage", tuple(14.0 + index % 5 for index in range(100)), policy
    )
    reliability = train_reliability(
        "cover.close", "cover.garage", (True,) * 95 + (False,) * 5
    )
    if timing is None or reliability is None:
        raise RuntimeError("benchmark fixture failed")
    house.install_effect_timing(timing)
    house.install_reliability(reliability)
    measurements: dict[str, list[float]] = {
        "thermal_prediction": [], "effect_lookup": [], "reliability_lookup": [],
        "adaptive_planner_advice": [], "preference_lookup": [],
        "habit_candidate_update": [], "anomaly_evaluation": [],
        "model_explanation": [], "forget_model": [],
    }
    deadline_goal = GoalModel(
        GoalKind.SCHEDULED,
        temporal=TemporalGoal(
            deadline=now + timedelta(days=1),
            must_be_achieved_by_deadline=True,
        ),
    )
    preference_context = PreferenceContext("user", "lamp", area_id="living")
    habit_observations = tuple(
        HabitSequenceObservation(
            "user", f"2026-01-{index + 1:02d}", index % 5, "morning",
            ("LIGHT_TURN_ON", "COVER_OPEN_COVER", "SWITCH_TURN_ON"),
            now - timedelta(days=index),
        )
        for index in range(15)
    )
    for _ in range(max(1, args.iterations)):
        started = time.perf_counter_ns()
        house.predict_thermal(
            "living", current_celsius=19.0, target_celsius=21.0,
            outdoor_celsius=None, now=now,
        )
        measurements["thermal_prediction"].append((time.perf_counter_ns() - started) / 1e6)
        started = time.perf_counter_ns()
        house.predict_effect_latency("cover.close", "cover.garage")
        measurements["effect_lookup"].append((time.perf_counter_ns() - started) / 1e6)
        started = time.perf_counter_ns()
        house.predict_reliability("cover.close", "cover.garage")
        measurements["reliability_lookup"].append((time.perf_counter_ns() - started) / 1e6)
        prediction = house.predict_thermal(
            "living", current_celsius=19.0, target_celsius=21.0,
            outdoor_celsius=None, now=now,
        )
        started = time.perf_counter_ns()
        advise_deadline_goal(deadline_goal, prediction)
        measurements["adaptive_planner_advice"].append((time.perf_counter_ns() - started) / 1e6)
        started = time.perf_counter_ns()
        infer_preference(preference_context, ("light.floor",) * 8, policy)
        measurements["preference_lookup"].append((time.perf_counter_ns() - started) / 1e6)
        started = time.perf_counter_ns()
        discover_habit(habit_observations, opportunity_count=20, policy=policy)
        measurements["habit_candidate_update"].append((time.perf_counter_ns() - started) / 1e6)
        started = time.perf_counter_ns()
        evaluate_latency_anomaly(timing, 50.0)
        measurements["anomaly_evaluation"].append((time.perf_counter_ns() - started) / 1e6)
        learned = _learned_model(now)
        started = time.perf_counter_ns()
        explain_learned_model(learned)
        measurements["model_explanation"].append((time.perf_counter_ns() - started) / 1e6)
        house.install_effect_timing(timing)
        started = time.perf_counter_ns()
        house.forget(timing.model_id)
        measurements["forget_model"].append((time.perf_counter_ns() - started) / 1e6)
    with tempfile.TemporaryDirectory(prefix="homeintent-v11-benchmark-") as directory:
        asyncio.run(_storage_benchmarks(
            Path(directory), policy, now, measurements,
            min(max(20, args.iterations // 10), 100),
        ))
    failed = False
    for name, values in measurements.items():
        p95 = _p95(values)
        print(f"{name}: median={statistics.median(values):.3f} ms p95={p95:.3f} ms")
        failed = failed or p95 > args.max_p95_ms
    return int(failed)


def _learned_model(now: datetime, index: int = 0) -> LearnedModel:
    return LearnedModel(
        f"reliability:light.{index}", LearnedKind.RELIABILITY,
        f"light.{index}", {"operator_id": "LIGHT_TURN_ON"},
        {"success_rate": 0.99}, KnowledgeState.OBSERVED, 0.9, 20,
        now - timedelta(days=20), now, (), health=ModelHealth.VALID,
    )


async def _storage_benchmarks(
    directory: Path,
    policy: LearningPolicy,
    now: datetime,
    measurements: dict[str, list[float]],
    iterations: int,
) -> None:
    registry = ModelRegistry(directory / "models.json", policy)
    await registry.async_upsert_many(tuple(_learned_model(now, index) for index in range(1_000)))
    registry_100 = ModelRegistry(directory / "models-100.json", policy)
    await registry_100.async_upsert_many(tuple(_learned_model(now, index) for index in range(100)))
    measurements["registry_lookup_100"] = []
    measurements["registry_lookup_1000"] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        await registry_100.async_get("reliability:light.99")
        measurements["registry_lookup_100"].append(
            (time.perf_counter_ns() - started) / 1e6
        )
        started = time.perf_counter_ns()
        await registry.async_get("reliability:light.999")
        measurements["registry_lookup_1000"].append(
            (time.perf_counter_ns() - started) / 1e6
        )
    store = ExperienceStore(directory / "experiences.json", policy)
    measurements["experience_append"] = []
    for index in range(iterations):
        record = ExperienceRecord(
            f"bench:{index}", now + timedelta(seconds=index), "goal", f"run:{index}",
            ExperienceContext(entity_id="light.bench", domain="light"),
            ExperienceAction("LIGHT_TURN_ON", "light.bench"), {}, {"state": "on"},
            ExperienceEffect("on", "on", 0.5, True),
            (f"goal_run:run:{index}",), ExperienceProvenance.GOAL_RUN,
            ExperienceQuality.COMPLETE,
        )
        started = time.perf_counter_ns()
        await store.async_append(record)
        measurements["experience_append"].append(
            (time.perf_counter_ns() - started) / 1e6
        )


if __name__ == "__main__":
    raise SystemExit(main())
