"""Explicit bounded retry decisions for verified idempotent operators."""

from __future__ import annotations

from dataclasses import dataclass

from .goal_run import FailureCode
from .planner import PlanStep
from .risk import RiskLevel


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    allowed_failure_codes: frozenset[FailureCode] = frozenset(
        {FailureCode.EFFECT_TIMEOUT, FailureCode.SERVICE_ERROR}
    )
    maximum_risk: RiskLevel = RiskLevel.LOW

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("Retry attempts must be bounded to 1..3")


def may_retry(
    step: PlanStep,
    failure: FailureCode,
    *,
    completed_attempts: int,
    policy: RetryPolicy = RetryPolicy(),
) -> bool:
    """Return false by default; never retries unsafe/non-idempotent actions."""
    return (
        policy.max_attempts > 1
        and completed_attempts < policy.max_attempts
        and step.idempotent
        and step.risk <= policy.maximum_risk
        and failure in policy.allowed_failure_codes
        and step.action is not None
        and step.action.service not in {
            "unlock", "open_cover", "open_valve", "alarm_disarm", "press",
            "turn_on_script",
        }
    )


__all__ = ("RetryPolicy", "may_retry")
