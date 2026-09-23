"""Opt-in discovery of abstract repeated sequences; never automation creation."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .learning_policy import KnowledgeState, LearningPolicy
from .goal_model import DesiredState, GoalScope
from .model_registry import LearnedKind, LearnedModel
from .profiles import RoutineDefinition, RoutineStepDefinition


class SuggestionStatus(StrEnum):
    NEW = "new"
    SHOWN = "shown"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SNOOZED = "snoozed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class HabitSequenceObservation:
    user_id: str
    day: str
    weekday: int
    time_band: str
    actions: tuple[str, ...]
    observed_at: datetime
    source: str = "goal_run"


@dataclass(frozen=True)
class HabitCandidate:
    habit_id: str
    user_id: str
    repeated_sequence: tuple[str, ...]
    time_band: str
    weekdays: tuple[int, ...]
    sample_count: int
    opportunity_count: int
    support: float
    confidence: float
    first_observed: datetime
    last_observed: datetime
    source_evidence: tuple[str, ...]
    suggested_routine_name: str
    knowledge_state: KnowledgeState = KnowledgeState.INFERRED
    suggestion_status: SuggestionStatus = SuggestionStatus.NEW
    creates_automation: bool = False

    @property
    def signature(self) -> str:
        return self.habit_id


def discover_habit(
    observations: tuple[HabitSequenceObservation, ...],
    *,
    opportunity_count: int,
    policy: LearningPolicy,
    rejected_signatures: frozenset[str] = frozenset(),
) -> HabitCandidate | None:
    if not policy.habit_discovery_enabled or not observations or opportunity_count <= 0:
        return None
    patterns = Counter((item.user_id, item.time_band, item.actions) for item in observations)
    (user_id, time_band, actions), count = sorted(
        patterns.items(), key=lambda item: (-item[1], repr(item[0]))
    )[0]
    support = count / opportunity_count
    matching = tuple(
        item for item in observations
        if (item.user_id, item.time_band, item.actions) == (user_id, time_band, actions)
    )
    if count < policy.habit_min_occurrences or support < policy.habit_min_support:
        return None
    raw_signature = repr((user_id, time_band, actions)).encode()
    habit_id = "habit:" + hashlib.sha256(raw_signature).hexdigest()[:24]
    if habit_id in rejected_signatures:
        return None
    return HabitCandidate(
        habit_id, user_id, actions, time_band,
        tuple(sorted({item.weekday for item in matching})), count,
        opportunity_count, support, min(1.0, support),
        min(item.observed_at for item in matching),
        max(item.observed_at for item in matching),
        tuple(sorted({f"{item.source}:{item.day}" for item in matching})),
        f"Routine {time_band}",
    )


def update_suggestion(
    candidate: HabitCandidate, status: SuggestionStatus
) -> HabitCandidate:
    return replace(candidate, suggestion_status=status)


def routine_from_habit_model(
    model: LearnedModel, owner_user_id: str
) -> RoutineDefinition | None:
    """Decode only the closed GoalRun-derived sequence into a V10 draft."""
    if model.kind is not LearnedKind.HABIT or model.knowledge_state is not KnowledgeState.INFERRED:
        return None
    raw_sequence = model.parameters.get("sequence")
    if not isinstance(raw_sequence, str):
        return None
    steps: list[RoutineStepDefinition] = []
    for index, encoded in enumerate(raw_sequence.split("|")):
        operator, separator, remainder = encoded.partition("@")
        entity_id, value_separator, expected = remainder.partition("=")
        if (
            not separator or not value_separator or not operator
            or "." not in entity_id or not expected
        ):
            return None
        if "=" in expected:
            property_name, _, raw_value = expected.partition("=")
            try:
                desired_value: str | float | int | bool = float(raw_value)
            except ValueError:
                desired_value = raw_value
            desired = DesiredState(property_name, desired_value)
        else:
            desired = DesiredState("state", expected)
        steps.append(RoutineStepDefinition(
            f"habit-step-{index + 1}", GoalScope(entity_ids=(entity_id,)),
            desired, f"{entity_id} → {expected}",
        ))
    if len(steps) < 2:
        return None
    time_band = model.context.get("time_band")
    name = "Morgenroutine" if time_band == "morning" else "Gelernte Routine"
    return RoutineDefinition(
        model.model_id.replace(":", "_"), name, owner_user_id,
        tuple(steps), confirmed=False,
    )


__all__ = (
    "HabitCandidate", "HabitSequenceObservation", "SuggestionStatus",
    "discover_habit", "routine_from_habit_model", "update_suggestion",
)
