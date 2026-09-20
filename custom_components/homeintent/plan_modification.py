"""Structured edits to a pending GoalModel/PlanModel."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import Iterable

from .entities import EntitySnapshot, normalize_for_compare
from .goal_model import GoalScope, TemporalGoal
from .nlu.language_frontend import LanguageDocument
from .nlu.temporal_semantics import TemporalKind
from .planner import MaterializedPlan, PlanStep, PlanningTrace, StepKind, validate_plan_graph


class PlanModificationKind(StrEnum):
    EXCLUDE_AREA = "exclude_area"
    REMOVE_DOMAIN_STEPS = "remove_domain_steps"
    RESCHEDULE_DOMAIN = "reschedule_domain"


def apply_plan_modification(
    plan: MaterializedPlan,
    document: LanguageDocument,
    entities: Iterable[EntitySnapshot],
) -> MaterializedPlan | None:
    """Apply only closed modifications; unknown edits return ``None``."""
    words = frozenset(token.canonical for token in document.tokens if token.is_word)
    by_id = {item.entity_id: item for item in entities}
    removed: set[str] = set()
    rescheduled: set[str] = set()
    goal = plan.goal

    exclusion_words = words & {"nicht", "ausser", "ruhe"}
    if exclusion_words:
        area_ids = {
            item.area_id for item in by_id.values()
            if item.area_id is not None
            and (
                normalize_for_compare(item.area_id) in words
                or normalize_for_compare(item.area_name or "") in words
            )
        }
        if area_ids:
            for step in plan.steps:
                if step.action is None:
                    continue
                ids = (step.action.entity_id,) if isinstance(step.action.entity_id, str) else tuple(step.action.entity_id)
                if any(by_id.get(item) is not None and by_id[item].area_id in area_ids for item in ids):
                    removed.add(step.step_id)
            goal = replace(
                goal,
                exclusions=GoalScope(
                    entity_ids=goal.exclusions.entity_ids,
                    domain=goal.exclusions.domain,
                    device_class=goal.exclusions.device_class,
                    area_id=goal.exclusions.area_id,
                    floor_id=goal.exclusions.floor_id,
                    person_ids=goal.exclusions.person_ids,
                    excluded_entity_ids=goal.exclusions.excluded_entity_ids,
                    excluded_area_ids=tuple(sorted(set(goal.exclusions.excluded_area_ids) | area_ids)),
                ),
            )
        domain = _mentioned_domain(words)
        if domain is not None:
            for step in plan.steps:
                if step.action is None:
                    continue
                ids = (step.action.entity_id,) if isinstance(step.action.entity_id, str) else tuple(step.action.entity_id)
                if any(by_id.get(item) is not None and by_id[item].domain == domain for item in ids):
                    removed.add(step.step_id)

    absolute = next(
        (item.value for item in document.temporal if item.kind is TemporalKind.ABSOLUTE_TIME),
        None,
    )
    if absolute is not None and words & {"erst", "spaeter", "heizung", "klima"}:
        goal = replace(
            goal,
            temporal=TemporalGoal(day_part=absolute, must_be_achieved_by_deadline=False),
        )
        rescheduled = {
            step.step_id
            for step in plan.steps
            if step.action is not None
            and any(
                by_id.get(item) is not None and by_id[item].domain == "climate"
                for item in (
                    (step.action.entity_id,)
                    if isinstance(step.action.entity_id, str)
                    else tuple(step.action.entity_id)
                )
            )
        }
    if not removed and goal == plan.goal:
        return None

    kept = [
        replace(step, execute_at_local_time=absolute)
        if step.step_id in rescheduled
        else step
        for step in plan.steps
        if step.step_id not in removed
    ]
    rewired: list[PlanStep] = []
    previous: str | None = None
    for step in kept:
        dependencies = () if previous is None else (previous,)
        if step.kind is StepKind.CHECK:
            dependencies = ()
        rewired_step = replace(step, dependencies=dependencies)
        rewired.append(rewired_step)
        previous = rewired_step.step_id
    trace = plan.trace or PlanningTrace(goal.kind.value)
    updated = replace(
        plan,
        goal=goal,
        steps=tuple(rewired),
        summary=f"{sum(item.kind is StepKind.ACTION for item in rewired)} Aktion(en) nach strukturierter Planänderung.",
        trace=replace(
            trace,
            skipped=(
                *trace.skipped,
                *(f"{item}:removed_by_user" for item in sorted(removed)),
                *(f"{item}:scheduled_for_{absolute}" for item in sorted(rescheduled)),
            ),
        ),
    )
    validate_plan_graph(updated)
    return updated


def _mentioned_domain(words: frozenset[str]) -> str | None:
    mapping = {
        "rollladen": "cover", "rolllaeden": "cover", "jalousien": "cover",
        "lichter": "light", "licht": "light", "heizung": "climate", "klima": "climate",
    }
    values = {domain for word, domain in mapping.items() if word in words}
    return next(iter(values)) if len(values) == 1 else None


__all__ = ("PlanModificationKind", "apply_plan_modification")
