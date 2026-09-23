"""Central read-only FUTURE view over V11 models."""

from __future__ import annotations

from datetime import datetime, timezone

from .learning_policy import LearningPolicy
from .prediction import PredictionResult, PredictionStatus
from .statistical_models import EffectTimingModel, ReliabilityStatistic
from .thermal_model import ThermalModel, predict_thermal_duration


class PredictiveHouseModel:
    """Prediction facade. It intentionally has no execute/service-plan method."""

    def __init__(self, policy: LearningPolicy) -> None:
        self.policy = policy
        self._thermal: dict[str, ThermalModel] = {}
        self._timing: dict[tuple[str, str], EffectTimingModel] = {}
        self._reliability: dict[tuple[str, str], ReliabilityStatistic] = {}

    def install_thermal(self, model: ThermalModel) -> None:
        self._thermal[model.binding.area_id] = model

    def thermal_model(self, area_id: str) -> ThermalModel | None:
        return self._thermal.get(area_id)

    def install_effect_timing(self, model: EffectTimingModel) -> None:
        self._timing[(model.operator_id, model.entity_id)] = model

    def effect_timing_model(
        self, operator_id: str, entity_id: str
    ) -> EffectTimingModel | None:
        return self._timing.get((operator_id, entity_id))

    def install_reliability(self, model: ReliabilityStatistic) -> None:
        self._reliability[(model.operator_id, model.entity_id)] = model

    def forget(self, model_id: str) -> bool:
        thermal_key = next((key for key, value in self._thermal.items()
                            if value.model_id == model_id), None)
        if thermal_key is not None:
            del self._thermal[thermal_key]
            return True
        timing_key = next((key for key, value in self._timing.items()
                           if value.model_id == model_id), None)
        if timing_key is not None:
            del self._timing[timing_key]
            return True
        reliability_key = next((key for key, value in self._reliability.items()
                                if value.model_id == model_id), None)
        if reliability_key is not None:
            del self._reliability[reliability_key]
            return True
        return False

    def clear(self) -> None:
        self._thermal.clear()
        self._timing.clear()
        self._reliability.clear()

    def predict_thermal(
        self, area_id: str, *, current_celsius: float,
        target_celsius: float, outdoor_celsius: float | None,
        now: datetime | None = None,
    ) -> PredictionResult[float]:
        return predict_thermal_duration(
            self._thermal.get(area_id), current_celsius=current_celsius,
            target_celsius=target_celsius, outdoor_celsius=outdoor_celsius,
            policy=self.policy, now=now,
        )

    def predict_effect_latency(
        self, operator_id: str, entity_id: str
    ) -> PredictionResult[float]:
        model = self._timing.get((operator_id, entity_id))
        now = datetime.now(timezone.utc)
        if model is None:
            return PredictionResult(PredictionStatus.INSUFFICIENT_DATA, None, None,
                                    0.0, None, None, 0, now, None, None, (),
                                    "Keine Timing-Evidenz.")
        status = (
            PredictionStatus.OK
            if self.policy.permits_planning(model.confidence, model.sample_count)
            else PredictionStatus.LOW_CONFIDENCE
        )
        return PredictionResult(
            status, model.median_seconds,
            (max(0.0, model.median_seconds - 3 * model.mad_seconds), model.p95_seconds),
            model.confidence, model.model_id, 1, model.sample_count, now, None,
            None, ("operator_id", "entity_id"),
            f"Median {model.median_seconds:.1f}s, p95 {model.p95_seconds:.1f}s.",
        )

    def predict_reliability(self, operator_id: str, entity_id: str) -> PredictionResult[float]:
        model = self._reliability.get((operator_id, entity_id))
        now = datetime.now(timezone.utc)
        if model is None:
            return PredictionResult(PredictionStatus.INSUFFICIENT_DATA, None, None,
                                    0.0, None, None, 0, now, None, None, (),
                                    "Keine Reliability-Evidenz.")
        status = (
            PredictionStatus.OK
            if self.policy.permits_planning(model.confidence, model.sample_count)
            else PredictionStatus.LOW_CONFIDENCE
        )
        return PredictionResult(
            status, model.success_rate, None, model.confidence,
            model.model_id, 1, model.sample_count, now, None, None,
            ("operator_id", "entity_id"),
            f"{model.success_count} von {model.sample_count} Wirkungen verifiziert.",
        )


__all__ = ("PredictiveHouseModel",)
