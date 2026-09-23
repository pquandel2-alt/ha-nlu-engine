"""Transparent robust models for effect timing, reliability and anomalies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

from .learning_policy import LearningPolicy


@dataclass(frozen=True)
class EffectTimingModel:
    model_id: str
    operator_id: str
    entity_id: str
    sample_count: int
    median_seconds: float
    p90_seconds: float
    p95_seconds: float
    mad_seconds: float
    confidence: float


@dataclass(frozen=True)
class ReliabilityStatistic:
    model_id: str
    operator_id: str
    entity_id: str
    success_count: int
    failure_count: int
    sample_count: int
    success_rate: float
    confidence: float


@dataclass(frozen=True)
class AnomalyObservation:
    model_id: str
    observed_seconds: float
    expected_median_seconds: float
    threshold_seconds: float
    score: float
    anomalous: bool
    advisory_only: bool = True


def train_effect_timing(
    operator_id: str,
    entity_id: str,
    durations_seconds: tuple[float, ...],
    policy: LearningPolicy,
) -> EffectTimingModel | None:
    values = tuple(sorted(item for item in durations_seconds if 0.0 <= item <= 86_400.0))
    if len(values) < policy.minimum_model_samples:
        return None
    center = median(values)
    mad = median(abs(item - center) for item in values)
    confidence = min(1.0, len(values) / policy.usable_model_samples)
    return EffectTimingModel(
        f"effect_latency:{operator_id}:{entity_id}", operator_id, entity_id,
        len(values), center, _quantile(values, 0.90), _quantile(values, 0.95),
        mad, confidence,
    )


def train_reliability(
    operator_id: str, entity_id: str, outcomes: tuple[bool, ...]
) -> ReliabilityStatistic | None:
    if not outcomes:
        return None
    successes = sum(outcomes)
    failures = len(outcomes) - successes
    # Wilson interval width drives confidence; success_rate never conveys
    # execution permission and the model has no action-producing API.
    n = len(outcomes)
    rate = successes / n
    z = 1.96
    denominator = 1 + z * z / n
    margin = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / denominator
    confidence = max(0.0, min(1.0, 1.0 - 2.0 * margin))
    return ReliabilityStatistic(
        f"reliability:{operator_id}:{entity_id}", operator_id, entity_id,
        successes, failures, n, rate, confidence,
    )


def evaluate_latency_anomaly(
    model: EffectTimingModel, observed_seconds: float
) -> AnomalyObservation:
    robust_spread = max(model.mad_seconds * 3.0, model.p95_seconds - model.median_seconds, 1.0)
    threshold = model.p95_seconds + robust_spread
    score = max(0.0, (observed_seconds - model.median_seconds) / robust_spread)
    return AnomalyObservation(
        model.model_id, observed_seconds, model.median_seconds, threshold,
        score, observed_seconds > threshold,
    )


def adaptive_verification_timeout(
    model: EffectTimingModel | None,
    *,
    default_seconds: float,
    absolute_max_seconds: float,
) -> float:
    if model is None:
        return min(default_seconds, absolute_max_seconds)
    learned = max(default_seconds, model.p95_seconds + max(2 * model.mad_seconds, 1.0))
    return min(learned, absolute_max_seconds)


def _quantile(values: tuple[float, ...], quantile: float) -> float:
    index = max(0, min(len(values) - 1, math.ceil(quantile * len(values)) - 1))
    return values[index]


__all__ = (
    "AnomalyObservation", "EffectTimingModel", "ReliabilityStatistic",
    "adaptive_verification_timeout", "evaluate_latency_anomaly",
    "train_effect_timing", "train_reliability",
)
