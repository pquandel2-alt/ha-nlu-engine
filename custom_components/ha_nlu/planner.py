"""Deterministic hierarchical planner over closed HomeIntent actions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Awaitable, Callable, Iterable, Mapping, Protocol, Sequence, cast

from .agent_action_policy import validate_agent_service_plan
from .entities import EntitySnapshot
from .execution_policy import PolicyOutcome, evaluate_service_plan
from .risk import RiskLevel, classify_service_plan
from .service_call import ServiceCallPlan


class GoalKind(StrEnum):
    PREPARE_NIGHT = "prepare_night"
    PREPARE_MOVIE = "prepare_movie"
    SAVE_UNOCCUPIED = "save_unoccupied"
    PREPARE_AWAY = "prepare_away"
    IMPROVE_COMFORT = "improve_comfort"
    INVESTIGATE_STATE = "investigate_state"


class StepKind(StrEnum):
    CHECK = "check"
    ACTION = "action"


class PlanStatus(StrEnum):
    PREVIEW = "preview"
    NEEDS_CONFIRMATION = "needs_confirmation"
    COMPLETED = "completed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class Goal:
    kind: GoalKind
    parameters: Mapping[str, object] = field(default_factory=lambda: _empty_mapping())


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    kind: StepKind
    description: str
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    action: ServiceCallPlan | None = None
    risk: RiskLevel = RiskLevel.LOW
    reversible: bool = False
    verification: Mapping[str, str] = field(default_factory=lambda: _empty_verification())
    compensation: ServiceCallPlan | None = None


@dataclass(frozen=True)
class MaterializedPlan:
    plan_id: str
    goal: Goal
    steps: tuple[PlanStep, ...]
    aggregate_risk: RiskLevel
    requires_confirmation: bool
    summary: str


@dataclass(frozen=True)
class StepResult:
    step_id: str
    success: bool
    message: str


@dataclass(frozen=True)
class PlanResult:
    plan_id: str
    status: PlanStatus
    steps: tuple[StepResult, ...]
    compensated_steps: tuple[str, ...] = ()


def materialize_goal(
    goal: Goal,
    entities: Iterable[EntitySnapshot],
    *,
    options: Mapping[str, object],
    is_admin: bool,
    user_id: str | None,
) -> MaterializedPlan:
    """Materialize a complete, inspectable plan from a known goal.

    Entity ids must be supplied explicitly in goal parameters for actions.
    The planner never guesses preferred targets from names or statistics.
    """
    snapshots = tuple(entities)
    by_id = {entity.entity_id: entity for entity in snapshots}
    requested = goal.parameters.get("entity_ids", ())
    requested_items = (
        cast(Sequence[object], requested)
        if isinstance(requested, (list, tuple))
        else ()
    )
    if any(not isinstance(item, str) for item in requested_items):
        raise ValueError("Das Ziel enthält ungültige Entitäts-IDs")
    entity_ids = tuple(cast(str, item) for item in requested_items)
    if not entity_ids and goal.kind in {
        GoalKind.PREPARE_NIGHT,
        GoalKind.SAVE_UNOCCUPIED,
        GoalKind.PREPARE_AWAY,
    }:
        entity_ids = tuple(
            entity.entity_id
            for entity in snapshots
            if "TURN_OFF" in entity.capabilities
            and entity.state in {"on", "playing", "heating", "cooling"}
        )
    if any(item not in by_id for item in entity_ids):
        raise ValueError("Das Ziel enthält unbekannte oder veraltete Entitäten")
    steps: list[PlanStep] = []
    check_id = "check-fresh-state"
    steps.append(
        PlanStep(
            check_id,
            StepKind.CHECK,
            "Aktuelle Zustände, Verfügbarkeit und Fähigkeiten prüfen",
            invariants=("fresh_snapshot", "capability_checked", "policy_checked"),
        )
    )
    if goal.kind is GoalKind.INVESTIGATE_STATE:
        return MaterializedPlan(
            f"plan_{uuid.uuid4().hex}",
            goal,
            tuple(steps),
            RiskLevel.LOW,
            False,
            "Ich prüfe ausschließlich aktuelle Zustände; es wird nichts geschaltet.",
        )
    if not entity_ids:
        raise ValueError("Für dieses Ziel wurden keine eindeutigen Geräte festgelegt")
    service = "turn_off" if goal.kind in {
        GoalKind.PREPARE_NIGHT,
        GoalKind.SAVE_UNOCCUPIED,
        GoalKind.PREPARE_AWAY,
    } else "turn_on"
    for index, entity_id in enumerate(entity_ids, start=1):
        entity = by_id[entity_id]
        capability = "TURN_OFF" if service == "turn_off" else "TURN_ON"
        if capability not in entity.capabilities:
            raise ValueError(f"{entity.friendly_name} unterstützt {capability} nicht")
        action = ServiceCallPlan("homeassistant", service, entity_id, {})
        if error := validate_agent_service_plan(action):
            raise ValueError(error)
        policy = evaluate_service_plan(
            action, snapshots, options, is_admin=is_admin, user_id=user_id
        )
        if policy.outcome is PolicyOutcome.DENY:
            raise PermissionError(policy.reason or "Aktion ist nicht erlaubt")
        inverse = ServiceCallPlan(
            "homeassistant", "turn_on" if service == "turn_off" else "turn_off", entity_id, {}
        )
        expected = "off" if service == "turn_off" else "on"
        steps.append(
            PlanStep(
                f"action-{index}",
                StepKind.ACTION,
                f"{entity.friendly_name} {expected}",
                preconditions=("entity_available", capability.casefold()),
                effects=(f"state={expected}",),
                invariants=("same_stable_entity_id", "policy_allow_or_confirmed"),
                dependencies=(check_id,),
                action=action,
                risk=classify_service_plan(action, snapshots),
                reversible=True,
                verification={entity_id: expected},
                compensation=inverse,
            )
        )
    aggregate = max((step.risk for step in steps), default=RiskLevel.LOW)
    # Every action-bearing household goal is confirmed as one materialized
    # unit, even if each individual LOW step would be directly allowed.
    requires_confirmation = True
    return MaterializedPlan(
        f"plan_{uuid.uuid4().hex}",
        goal,
        tuple(steps),
        aggregate,
        requires_confirmation,
        f"{len(steps) - 1} geprüfte Aktion(en), Gesamtrisiko {aggregate.name.lower()}.",
    )


RefreshEntities = Callable[[], Awaitable[list[EntitySnapshot]]]
class ExecutionOutcome(Protocol):
    @property
    def executed(self) -> bool: ...

    @property
    def error(self) -> str | None: ...


ExecutePlan = Callable[[ServiceCallPlan, list[EntitySnapshot], bool], Awaitable[ExecutionOutcome]]
VerifyState = Callable[[str, str], Awaitable[bool]]


class PlanExecutor:
    """Runs a materialized plan only through the shared policy executor."""

    def __init__(
        self,
        refresh_entities: RefreshEntities,
        execute_plan: ExecutePlan,
        verify_state: VerifyState,
    ) -> None:
        self._refresh_entities = refresh_entities
        self._execute_plan = execute_plan
        self._verify_state = verify_state

    async def execute(
        self, plan: MaterializedPlan, *, confirmed: bool
    ) -> PlanResult:
        if plan.requires_confirmation and not confirmed:
            return PlanResult(plan.plan_id, PlanStatus.NEEDS_CONFIRMATION, ())
        results: list[StepResult] = []
        executed: list[PlanStep] = []
        for step in plan.steps:
            fresh = await self._refresh_entities()
            if step.kind is StepKind.CHECK:
                results.append(StepResult(step.step_id, True, "Frischer Snapshot geladen."))
                continue
            action = step.action
            if action is None:
                results.append(StepResult(step.step_id, False, "Aktionsschritt ohne Aktion."))
                return PlanResult(plan.plan_id, PlanStatus.STOPPED, tuple(results))
            if error := validate_agent_service_plan(action):
                results.append(StepResult(step.step_id, False, error))
                return PlanResult(plan.plan_id, PlanStatus.STOPPED, tuple(results))
            result = await self._execute_plan(action, fresh, confirmed)
            if not result.executed:
                results.append(StepResult(step.step_id, False, result.error or "Nicht ausgeführt."))
                compensated = await self._compensate(executed, confirmed)
                return PlanResult(
                    plan.plan_id, PlanStatus.STOPPED, tuple(results), compensated
                )
            verified = True
            for entity_id, state in step.verification.items():
                if not await self._verify_state(entity_id, state):
                    verified = False
                    break
            if not verified:
                results.append(StepResult(step.step_id, False, "Erwartete Wirkung nicht beobachtet."))
                compensated = await self._compensate((*executed, step), confirmed)
                return PlanResult(
                    plan.plan_id, PlanStatus.STOPPED, tuple(results), compensated
                )
            executed.append(step)
            results.append(StepResult(step.step_id, True, "Ausgeführt und verifiziert."))
        return PlanResult(plan.plan_id, PlanStatus.COMPLETED, tuple(results))

    async def _compensate(
        self, executed: Iterable[PlanStep], confirmed: bool
    ) -> tuple[str, ...]:
        compensated: list[str] = []
        for step in reversed(tuple(executed)):
            if not step.reversible or step.compensation is None:
                continue
            fresh = await self._refresh_entities()
            result = await self._execute_plan(step.compensation, fresh, confirmed)
            if result.executed:
                compensated.append(step.step_id)
        return tuple(compensated)


def _empty_mapping() -> dict[str, object]:
    return {}


def _empty_verification() -> dict[str, str]:
    return {}
