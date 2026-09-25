"""V12 ContextForecastEngine: contextual anticipation over V11 predictions.

This is an orchestration layer, not a prediction engine.  It trains nothing
and stores nothing.  It reads the existing V11 authorities
(``PredictiveHouseModel`` for thermal/timing/reliability, habit
``LearnedModel`` records from the ``ModelRegistry``) and combines their
typed status with the current situation.

PREDICTION != EXECUTION: ``AnticipationResult`` has no action field.  A
non-OK V11 status (stale, low confidence, out of distribution, invalid)
always produces ``usable=False``; the OpportunityPolicy then downgrades the
situation to history-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .prediction import PredictionResult, PredictionStatus
from .predictive_house_model import PredictiveHouseModel
from .proactive_model import (
    AnticipationKind,
    AnticipationResult,
    ModelEvidenceStatus,
    ModelReference,
    ProactiveSituation,
    SituationKind,
)


_STATUS_MAP = {
    PredictionStatus.OK: ModelEvidenceStatus.OK,
    PredictionStatus.INSUFFICIENT_DATA: ModelEvidenceStatus.INSUFFICIENT,
    PredictionStatus.LOW_CONFIDENCE: ModelEvidenceStatus.LOW_CONFIDENCE,
    PredictionStatus.STALE_MODEL: ModelEvidenceStatus.STALE,
    PredictionStatus.OUT_OF_DISTRIBUTION: ModelEvidenceStatus.OUT_OF_DISTRIBUTION,
    PredictionStatus.INCOMPATIBLE_CONTEXT: ModelEvidenceStatus.INVALID,
    PredictionStatus.MODEL_UNRELIABLE: ModelEvidenceStatus.LOW_CONFIDENCE,
    PredictionStatus.MODEL_INVALID: ModelEvidenceStatus.INVALID,
    PredictionStatus.DRIFT_DETECTED: ModelEvidenceStatus.INVALID,
}


@dataclass(frozen=True)
class HabitEvidence:
    """The V11 habit model fields V12 may read; never the sequence as a plan."""

    model_id: str
    user_id: str
    healthy: bool
    confirmed_or_valid: bool
    dismissed: bool
    expired: bool
    support: float


def map_prediction_status(status: PredictionStatus) -> ModelEvidenceStatus:
    return _STATUS_MAP.get(status, ModelEvidenceStatus.INVALID)


class ContextForecastEngine:
    """Consumes V11; never replaces or retrains it."""

    def __init__(self, predictive_house: PredictiveHouseModel | None) -> None:
        self._house = predictive_house

    def anticipate(
        self,
        situation: ProactiveSituation,
        *,
        now: datetime,
        habit: HabitEvidence | None = None,
        thermal_inputs: tuple[float, float, float | None] | None = None,
        effect_operator: str | None = None,
    ) -> AnticipationResult:
        if situation.kind is SituationKind.THERMAL_GOAL_AT_RISK:
            return self._thermal(situation, now, thermal_inputs)
        if situation.kind is SituationKind.HABIT_OPPORTUNITY:
            return self._habit(situation, habit)
        if situation.kind is SituationKind.DEVICE_EFFECT_ANOMALY:
            return self._effect(situation, now, effect_operator)
        return AnticipationResult(
            AnticipationKind.ATTENTION_MAY_BE_REQUIRED, situation.situation_id,
            ModelReference(None, ModelEvidenceStatus.NOT_USED, "Direkte Beobachtung."),
            "Eine direkt beobachtete Situation kann Aufmerksamkeit erfordern.",
            True, ("observed_condition",),
        )

    def _thermal(
        self, situation: ProactiveSituation, now: datetime,
        inputs: tuple[float, float, float | None] | None,
    ) -> AnticipationResult:
        area_id = situation.area_id
        if self._house is None or area_id is None or inputs is None:
            return self._unusable(
                AnticipationKind.GOAL_AT_RISK, situation, None,
                ModelEvidenceStatus.INSUFFICIENT, "thermal_inputs_missing",
            )
        current, target, outdoor = inputs
        prediction = self._house.predict_thermal(
            area_id, current_celsius=current, target_celsius=target,
            outdoor_celsius=outdoor, now=now,
        )
        return self._from_prediction(AnticipationKind.GOAL_AT_RISK, situation, prediction,
                                     "Das thermische Ziel wird voraussichtlich verfehlt.")

    def _effect(
        self, situation: ProactiveSituation, now: datetime, operator: str | None,
    ) -> AnticipationResult:
        if self._house is None or operator is None or not situation.subject_ids:
            return self._unusable(
                AnticipationKind.DEVICE_ANOMALY_RELEVANT, situation, None,
                ModelEvidenceStatus.INSUFFICIENT, "effect_timing_unavailable",
            )
        prediction = self._house.predict_effect_latency(
            operator, situation.subject_ids[0], now=now,
        )
        return self._from_prediction(AnticipationKind.DEVICE_ANOMALY_RELEVANT, situation,
                                     prediction, "Die Gerätewirkung weicht vom gelernten Timing ab.")

    def _habit(self, situation: ProactiveSituation, habit: HabitEvidence | None) -> AnticipationResult:
        if habit is None:
            return self._unusable(AnticipationKind.ROUTINE_OPPORTUNITY, situation, None,
                                  ModelEvidenceStatus.INSUFFICIENT, "habit_model_missing")
        reference = ModelReference(habit.model_id, ModelEvidenceStatus.OK,
                                   f"Unterstützung {habit.support:.0%}")
        if habit.expired:
            return self._unusable(AnticipationKind.ROUTINE_OPPORTUNITY, situation,
                                  habit.model_id, ModelEvidenceStatus.STALE, "habit_model_stale")
        if habit.dismissed:
            return self._unusable(AnticipationKind.ROUTINE_OPPORTUNITY, situation,
                                  habit.model_id, ModelEvidenceStatus.INVALID, "habit_dismissed_by_user")
        if not habit.healthy or not habit.confirmed_or_valid:
            return self._unusable(AnticipationKind.ROUTINE_OPPORTUNITY, situation,
                                  habit.model_id, ModelEvidenceStatus.LOW_CONFIDENCE,
                                  "habit_model_low_confidence")
        return AnticipationResult(
            AnticipationKind.ROUTINE_OPPORTUNITY, situation.situation_id, reference,
            "Eine bekannte Abfolge beginnt gerade.", True, ("habit_model_valid",),
        )

    def _from_prediction(
        self, kind: AnticipationKind, situation: ProactiveSituation,
        prediction: PredictionResult[float], summary: str,
    ) -> AnticipationResult:
        status = map_prediction_status(prediction.status)
        reference = ModelReference(prediction.model_id, status, prediction.explanation)
        usable = prediction.usable_for_planning
        return AnticipationResult(
            kind, situation.situation_id, reference, summary, usable,
            ("v11_prediction_ok",) if usable else (f"v11_status_{prediction.status.value}",),
        )

    @staticmethod
    def _unusable(
        kind: AnticipationKind, situation: ProactiveSituation, model_id: str | None,
        status: ModelEvidenceStatus, reason: str,
    ) -> AnticipationResult:
        return AnticipationResult(
            kind, situation.situation_id, ModelReference(model_id, status, reason),
            "Keine belastbare Vorhersage.", False, (reason,),
        )


__all__ = ("ContextForecastEngine", "HabitEvidence", "map_prediction_status")
