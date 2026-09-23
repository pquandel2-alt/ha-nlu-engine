"""Central, conservative policy for local V11 learning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class KnowledgeState(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"


class ConfidenceBand(StrEnum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LearningMode(StrEnum):
    OFF = "off"
    SILENT_LEARN = "silent_learn"
    ASK = "ask"


@dataclass(frozen=True)
class LearningPolicy:
    """All V11 thresholds live here instead of being feature-local magic."""

    experience_limit: int = 5_000
    model_limit: int = 1_000
    retention_days: int = 365
    minimum_model_samples: int = 5
    usable_model_samples: int = 15
    minimum_planning_confidence: float = 0.75
    minimum_suggestion_confidence: float = 0.60
    maximum_thermal_mae_minutes: float = 15.0
    stale_model_days: int = 180
    habit_min_occurrences: int = 10
    habit_min_support: float = 0.70
    preference_min_samples: int = 8
    preference_min_support: float = 0.75
    drift_window: int = 5
    drift_residual_minutes: float = 15.0
    maximum_effect_timeout: timedelta = timedelta(minutes=10)
    learning_mode: LearningMode = LearningMode.OFF
    predictive_models_enabled: bool = False
    habit_discovery_enabled: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_planning_confidence <= 1.0:
            raise ValueError("minimum_planning_confidence must be between 0 and 1")
        if not 0.0 <= self.minimum_suggestion_confidence <= 1.0:
            raise ValueError("minimum_suggestion_confidence must be between 0 and 1")
        if self.minimum_model_samples < 2:
            raise ValueError("minimum_model_samples must be at least two")
        if self.usable_model_samples < self.minimum_model_samples:
            raise ValueError("usable_model_samples must not be smaller")

    @property
    def retention(self) -> timedelta:
        return timedelta(days=max(1, self.retention_days))

    def confidence_band(self, confidence: float) -> ConfidenceBand:
        value = max(0.0, min(1.0, confidence))
        if value < 0.25:
            return ConfidenceBand.VERY_LOW
        if value < 0.50:
            return ConfidenceBand.LOW
        if value < self.minimum_planning_confidence:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.HIGH

    def permits_planning(self, confidence: float, sample_count: int) -> bool:
        return (
            self.predictive_models_enabled
            and sample_count >= self.usable_model_samples
            and confidence >= self.minimum_planning_confidence
        )

    @property
    def suggestions_enabled(self) -> bool:
        return self.learning_mode is LearningMode.ASK


DEFAULT_LEARNING_POLICY = LearningPolicy()


__all__ = (
    "ConfidenceBand", "DEFAULT_LEARNING_POLICY", "KnowledgeState",
    "LearningMode", "LearningPolicy",
)
