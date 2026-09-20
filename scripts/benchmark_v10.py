#!/usr/bin/env python3
"""Reproducible hass-free V10 planning microbenchmarks."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from homeintent.entities import EntitySnapshot  # noqa: E402
from homeintent.goal_intent import interpret_goal  # noqa: E402
from homeintent.goal_model import DesiredState, GoalCondition, GoalKind, GoalModel, GoalScope  # noqa: E402
from homeintent.goal_run import GoalRun, explain_goal_run  # noqa: E402
from homeintent.monitor_goal import _evaluate_dynamic_condition  # noqa: E402
from homeintent.nlu.language_frontend import analyse_language  # noqa: E402
from homeintent.planner import materialize_routine  # noqa: E402
from homeintent.profiles import RoutineDefinition, RoutineStepDefinition  # noqa: E402
from homeintent.user_context import NotificationTarget, UserContext  # noqa: E402


def _registry(size: int) -> list[EntitySnapshot]:
    return [
        EntitySnapshot(
            f"light.test_{index}", f"Testlicht {index}", "light",
            "on" if index < 10 else "off", area_id=f"area_{index % 20}",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        )
        for index in range(size)
    ]


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=100, method="inclusive")[94]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--registry-size", type=int, default=5000)
    parser.add_argument("--max-p95-ms", type=float, default=100.0)
    args = parser.parse_args()
    entities = _registry(args.registry_size)
    routine = RoutineDefinition(
        "ten", "Ten", "bench",
        tuple(
            RoutineStepDefinition(
                f"step-{index}", GoalScope(entity_ids=(f"light.test_{index}",)),
                DesiredState("state", "off"),
            )
            for index in range(10)
        ),
        True,
    )
    routine_goal = GoalModel(GoalKind.PREPARE_ROUTINE, routine_id="ten")
    monitor_goal = GoalModel(
        GoalKind.MONITOR_AND_NOTIFY,
        conditions=(
            GoalCondition(
                "open_entities", GoalScope(domain="binary_sensor", device_class="window"),
                "non_empty", True,
            ),
        ),
    )
    context = UserContext(
        "bench", "person.bench", (NotificationTarget("notify.bench", preferred=True),)
    )
    run = GoalRun.start(routine_goal, user_id="bench", person_entity_id="person.bench")
    operations = {
        "simple_goal_understanding": lambda: interpret_goal(analyse_language("Mach das Haus für die Nacht fertig.")),
        "routine_plan": lambda: materialize_routine(routine_goal, routine, entities, options={}, is_admin=True, user_id="bench"),
        "ten_step_plan": lambda: materialize_routine(routine_goal, routine, entities, options={}, is_admin=True, user_id="bench"),
        "presence_monitor_evaluation": lambda: monitor_goal.kind,
        "dynamic_open_window_query": lambda: _evaluate_dynamic_condition(monitor_goal, entities),
        "notification_target_resolution": lambda: context.notification_targets[0],
        "effect_state_lookup": lambda: entities[0].state == "off",
        "failure_explanation_lookup": lambda: explain_goal_run(run),
    }
    failed = False
    for name, operation in operations.items():
        samples: list[float] = []
        for _ in range(max(5, args.iterations)):
            started = perf_counter()
            operation()
            samples.append((perf_counter() - started) * 1000)
        p95 = _p95(samples)
        print(f"{name}: p95={p95:.3f}ms")
        if p95 > args.max_p95_ms:
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
