"""Policy-bounded V11 advice for the existing V10 planner."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .goal_model import GoalModel, TemporalGoal
from .prediction import PredictionResult


@dataclass(frozen=True)
class AdaptivePlanningAdvice:
    model_id: str
    predicted_duration: timedelta
    uncertainty_buffer: timedelta
    start_at: datetime
    intermediate_check_at: datetime
    final_verification_at: datetime
    confidence: float
    sample_count: int
    explanation: str
    advisory_only: bool = True


def advise_deadline_goal(
    goal: GoalModel, prediction: PredictionResult[float]
) -> AdaptivePlanningAdvice | None:
    """Translate a usable prediction into timing, never into a service call."""
    temporal = goal.temporal
    if (
        temporal is None or temporal.deadline is None
        or not temporal.must_be_achieved_by_deadline
        or not prediction.usable_for_planning
        or prediction.model_id is None or prediction.value is None
        or prediction.uncertainty is None
    ):
        return None
    duration = timedelta(seconds=max(0.0, prediction.value))
    # The reserve is exactly the validated upper interval distance. There is
    # no invented constant safety time.
    buffer = timedelta(seconds=max(0.0, prediction.uncertainty[1] - prediction.value))
    start = temporal.deadline - duration - buffer
    intermediate = start + (temporal.deadline - start) * 0.65
    return AdaptivePlanningAdvice(
        prediction.model_id, duration, buffer, start, intermediate,
        temporal.deadline, prediction.confidence, prediction.sample_count,
        prediction.explanation,
    )


def apply_advice(goal: GoalModel, advice: AdaptivePlanningAdvice | None) -> GoalModel:
    """Set scheduling semantics only; the V10 planner still selects actions."""
    if advice is None or not advice.advisory_only or goal.temporal is None:
        return goal
    if goal.temporal.deadline != advice.final_verification_at:
        raise ValueError("Adaptive advice does not match the goal deadline")
    temporal = TemporalGoal(
        deadline=goal.temporal.deadline,
        execute_at=advice.start_at,
        day_part=goal.temporal.day_part,
        must_be_achieved_by_deadline=False,
    )
    return replace(goal, temporal=temporal)


__all__ = ("AdaptivePlanningAdvice", "advise_deadline_goal", "apply_advice")
