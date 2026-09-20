"""Deterministic conflict detection for concurrent goal runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from .planner import MaterializedPlan


class ConflictOutcome(StrEnum):
    ACQUIRED = "acquired"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class ReservationResult:
    outcome: ConflictOutcome
    entity_ids: tuple[str, ...]
    conflicting_run_ids: tuple[str, ...] = ()


class ExecutionCoordinator:
    """Reserve concrete write targets; unrelated goals remain concurrent."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def async_acquire(
        self, run_id: str, plan: MaterializedPlan
    ) -> ReservationResult:
        targets = _targets(plan)
        async with self._lock:
            conflicts = tuple(sorted({self._owners[item] for item in targets if item in self._owners and self._owners[item] != run_id}))
            if conflicts:
                return ReservationResult(ConflictOutcome.CONFLICT, targets, conflicts)
            for entity_id in targets:
                self._owners[entity_id] = run_id
            return ReservationResult(ConflictOutcome.ACQUIRED, targets)

    async def async_release(self, run_id: str) -> None:
        async with self._lock:
            for entity_id in tuple(self._owners):
                if self._owners[entity_id] == run_id:
                    del self._owners[entity_id]


def _targets(plan: MaterializedPlan) -> tuple[str, ...]:
    values: list[str] = []
    for step in plan.steps:
        if step.action is None:
            continue
        raw = step.action.entity_id
        values.extend((raw,) if isinstance(raw, str) else raw)
    return tuple(dict.fromkeys(values))


__all__ = ("ConflictOutcome", "ExecutionCoordinator", "ReservationResult")
