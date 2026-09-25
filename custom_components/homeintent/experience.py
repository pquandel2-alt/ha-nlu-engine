"""Typed, minimal V11 experiences derived from authoritative GoalRuns."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping, cast

from .goal_run import EffectEvidenceState, GoalRun, GoalRunStatus


FeatureValue = str | float | int | bool


def _empty_features() -> Mapping[str, FeatureValue]:
    return {}


class ExperienceQuality(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INVALID = "invalid"


class ExperienceProvenance(StrEnum):
    GOAL_RUN = "goal_run"
    RECORDER = "recorder"
    USER_FEEDBACK = "explicit_user_feedback"
    MANUAL = "manually_configured"
    LEGACY = "imported_legacy"


@dataclass(frozen=True)
class ExperienceContext:
    area_id: str | None = None
    entity_id: str | None = None
    domain: str | None = None
    user_id: str | None = None
    household_state: str | None = None
    properties: Mapping[str, FeatureValue] = field(default_factory=_empty_features)


@dataclass(frozen=True)
class ExperienceAction:
    operator_id: str
    target_id: str
    property_name: str | None = None
    requested_value: str | float | int | bool | None = None


@dataclass(frozen=True)
class ExperienceEffect:
    expected: str | float | int | bool | None
    observed: str | float | int | bool | None
    latency_seconds: float | None
    success: bool
    evidence_state: EffectEvidenceState = EffectEvidenceState.UNVERIFIED


@dataclass(frozen=True)
class ExperienceRecord:
    experience_id: str
    timestamp: datetime
    goal_id: str
    run_id: str
    context: ExperienceContext
    action: ExperienceAction
    before: Mapping[str, str | float | int | bool]
    after: Mapping[str, str | float | int | bool]
    effect: ExperienceEffect
    evidence: tuple[str, ...]
    provenance: ExperienceProvenance
    quality: ExperienceQuality

    def to_dict(self) -> dict[str, object]:
        return {
            "experience_id": self.experience_id,
            "timestamp": self.timestamp.isoformat(),
            "goal_id": self.goal_id,
            "run_id": self.run_id,
            "context": {
                "area_id": self.context.area_id,
                "entity_id": self.context.entity_id,
                "domain": self.context.domain,
                "user_id": self.context.user_id,
                "household_state": self.context.household_state,
                "properties": dict(self.context.properties),
            },
            "action": {
                "operator_id": self.action.operator_id,
                "target_id": self.action.target_id,
                "property_name": self.action.property_name,
                "requested_value": self.action.requested_value,
            },
            "before": dict(self.before),
            "after": dict(self.after),
            "effect": {
                "expected": self.effect.expected,
                "observed": self.effect.observed,
                "latency_seconds": self.effect.latency_seconds,
                "success": self.effect.success,
                "evidence_state": self.effect.evidence_state.value,
            },
            "evidence": list(self.evidence),
            "provenance": self.provenance.value,
            "quality": self.quality.value,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "ExperienceRecord":
        context = _mapping(raw.get("context"))
        action = _mapping(raw.get("action"))
        effect = _mapping(raw.get("effect"))
        timestamp = datetime.fromisoformat(str(raw["timestamp"]))
        if timestamp.tzinfo is None:
            raise ValueError("experience timestamp must be timezone-aware")
        quality = ExperienceQuality(str(raw.get("quality", "invalid")))
        observed = _feature(effect.get("observed"))
        success = bool(effect.get("success", False))
        raw_evidence_state = effect.get("evidence_state")
        if isinstance(raw_evidence_state, str):
            evidence_state = EffectEvidenceState(raw_evidence_state)
        elif quality is ExperienceQuality.INVALID:
            evidence_state = EffectEvidenceState.INVALID
        elif quality is ExperienceQuality.PARTIAL:
            evidence_state = EffectEvidenceState.UNVERIFIED
        elif observed is not None:
            evidence_state = (
                EffectEvidenceState.VERIFIED_SUCCESS
                if success else EffectEvidenceState.VERIFIED_FAILURE
            )
        else:
            evidence_state = EffectEvidenceState.UNVERIFIED
        return cls(
            str(raw["experience_id"]), timestamp, str(raw["goal_id"]),
            str(raw["run_id"]),
            ExperienceContext(
                _optional_text(context.get("area_id")),
                _optional_text(context.get("entity_id")),
                _optional_text(context.get("domain")),
                _optional_text(context.get("user_id")),
                _optional_text(context.get("household_state")),
                _features(context.get("properties")),
            ),
            ExperienceAction(
                str(action["operator_id"]), str(action["target_id"]),
                _optional_text(action.get("property_name")),
                _feature(action.get("requested_value")),
            ),
            _features(raw.get("before")), _features(raw.get("after")),
            ExperienceEffect(
                _feature(effect.get("expected")), observed,
                _optional_float(effect.get("latency_seconds")),
                success, evidence_state,
            ),
            _strings(raw.get("evidence")),
            ExperienceProvenance(str(raw.get("provenance", "goal_run"))),
            quality,
        )


def extract_goal_run_experiences(run: GoalRun) -> tuple[ExperienceRecord, ...]:
    """Extract only verified, action-scoped features; never dump HA state."""
    try:
        timestamp = datetime.fromisoformat(run.updated_at)
    except ValueError:
        return ()
    if timestamp.tzinfo is None:
        return ()
    result: list[ExperienceRecord] = []
    for step in run.steps:
        # Only an accepted device service call can produce action-effect
        # evidence: a satisfied no-op (None) or a rejected call (False) says
        # nothing about whether the device reacts to the operator.
        if step.operator_id is None or step.service_accepted is not True:
            continue
        for target in step.selected_targets:
            matches = tuple(v for v in step.verification if v.entity_id == target)
            verification = matches[-1] if matches else None
            observed_at: datetime | None = None
            if verification is not None and verification.observed_at is not None:
                try:
                    observed_at = datetime.fromisoformat(verification.observed_at)
                except ValueError:
                    observed_at = None
            latency = None
            try:
                accepted_at = (
                    datetime.fromisoformat(step.service_accepted_at)
                    if step.service_accepted_at is not None else None
                )
                if (
                    observed_at is not None
                    and observed_at.tzinfo is not None
                    and accepted_at is not None
                    and accepted_at.tzinfo is not None
                    and observed_at >= accepted_at
                ):
                    latency = (observed_at - accepted_at).total_seconds()
            except (ValueError, TypeError):
                pass
            success = bool(verification.success) if verification is not None else False
            quality = (
                ExperienceQuality.COMPLETE
                if verification is not None and verification.observed is not None
                else ExperienceQuality.PARTIAL
            )
            expected = verification.expected if verification is not None else None
            observed = verification.observed if verification is not None else None
            evidence_state = (
                EffectEvidenceState.INVALID
                if run.status is GoalRunStatus.CANCELLED
                else EffectEvidenceState.UNVERIFIED
                if verification is None or verification.observed is None
                else EffectEvidenceState.VERIFIED_SUCCESS
                if verification.success
                else EffectEvidenceState.VERIFIED_FAILURE
            )
            digest = hashlib.sha256(
                f"{run.run_id}\0{step.step_id}\0{target}".encode()
            ).hexdigest()[:24]
            result.append(ExperienceRecord(
                f"exp_{digest}", timestamp, run.goal_id, run.run_id,
                ExperienceContext(
                    area_id=run.goal.scope.area_id,
                    entity_id=target,
                    domain=target.partition(".")[0] or None,
                    user_id=run.user_id,
                ),
                ExperienceAction(step.operator_id, target),
                {}, {"state": observed} if observed is not None else {},
                ExperienceEffect(expected, observed, latency, success, evidence_state),
                (f"goal_run:{run.run_id}", f"step:{step.step_id}"),
                ExperienceProvenance.GOAL_RUN,
                quality if run.status is not GoalRunStatus.CANCELLED else ExperienceQuality.INVALID,
            ))
    return tuple(result)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected an object")
    return cast(Mapping[str, object], value)


def _feature(value: object) -> FeatureValue | None:
    return value if isinstance(value, (str, float, int, bool)) else None


def _features(value: object) -> dict[str, FeatureValue]:
    if not isinstance(value, Mapping):
        return {}
    items = cast(Mapping[object, object], value)
    return {
        str(key): item for key, item in items.items()
        if isinstance(key, str) and isinstance(item, (str, float, int, bool))
    }


def _strings(value: object) -> tuple[str, ...]:
    return tuple(item for item in cast(list[object], value) if isinstance(item, str)) if isinstance(value, list) else ()


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


__all__ = (
    "ExperienceAction", "ExperienceContext", "ExperienceEffect",
    "ExperienceProvenance", "ExperienceQuality", "ExperienceRecord",
    "extract_goal_run_experiences",
)
