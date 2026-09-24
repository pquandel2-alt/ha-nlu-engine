"""Deterministic, explainable room-heating duration model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

from .experience import (
    ExperienceAction,
    ExperienceContext,
    ExperienceEffect,
    ExperienceProvenance,
    ExperienceQuality,
    ExperienceRecord,
)
from .learning_policy import DEFAULT_LEARNING_POLICY, LearningPolicy
from .learning_policy import KnowledgeState
from .goal_run import EffectEvidenceState
from .model_registry import LearnedKind, LearnedModel, ModelHealth
from .prediction import PredictionResult, PredictionStatus


@dataclass(frozen=True)
class ThermalBinding:
    area_id: str
    temperature_entity_id: str
    climate_entity_id: str
    outdoor_temperature_entity_id: str | None = None
    confirmed: bool = False


@dataclass(frozen=True)
class ThermalObservation:
    started_at: datetime
    ended_at: datetime
    area_id: str
    temperature_entity_id: str
    climate_entity_id: str
    start_celsius: float
    target_celsius: float
    duration_seconds: float
    reached_target: bool
    outdoor_celsius: float | None = None
    window_opened: bool = False
    service_succeeded: bool = True
    source_changed: bool = False
    concurrent_action: bool = False

    @property
    def usable(self) -> bool:
        return (
            self.started_at.tzinfo is not None
            and self.ended_at.tzinfo is not None
            and self.ended_at > self.started_at
            and self.reached_target
            and self.service_succeeded
            and not self.window_opened
            and not self.source_changed
            and not self.concurrent_action
            and 0.1 <= self.target_celsius - self.start_celsius <= 15.0
            and 1.0 <= self.duration_seconds <= 12 * 60 * 60
        )


@dataclass(frozen=True)
class ThermalModel:
    model_id: str
    model_version: int
    binding: ThermalBinding
    intercept_seconds: float
    delta_coefficient: float
    outside_gap_coefficient: float | None
    sample_count: int
    confidence: float
    mae_seconds: float
    residual_median_seconds: float
    residual_mad_seconds: float
    residual_p90_seconds: float
    trained_from: datetime
    trained_until: datetime
    updated_at: datetime
    drift_detected: bool = False
    invalidation_reason: str | None = None
    min_temperature_delta: float | None = None
    max_temperature_delta: float | None = None
    min_start_temperature: float | None = None
    max_start_temperature: float | None = None
    min_outdoor_gap: float | None = None
    max_outdoor_gap: float | None = None
    validation_sample_count: int = 0
    validation_mae_seconds: float | None = None
    validation_median_absolute_error_seconds: float | None = None
    validation_p90_absolute_error_seconds: float | None = None


def thermal_observation_to_experience(
    observation: ThermalObservation, *, goal_id: str, run_id: str,
    user_id: str | None = None,
) -> ExperienceRecord:
    """Persist a validated compact cycle, not the underlying sensor series."""
    evidence = (f"goal_run:{run_id}", f"measurement:{observation.temperature_entity_id}")
    properties: dict[str, str | float | int | bool] = {
        "temperature_entity_id": observation.temperature_entity_id,
        "climate_entity_id": observation.climate_entity_id,
        "window_opened": observation.window_opened,
        "source_changed": observation.source_changed,
        "concurrent_action": observation.concurrent_action,
    }
    if observation.outdoor_celsius is not None:
        properties["outdoor_celsius"] = observation.outdoor_celsius
    return ExperienceRecord(
        f"thermal:{run_id}:{observation.area_id}", observation.ended_at,
        goal_id, run_id,
        ExperienceContext(
            observation.area_id, observation.climate_entity_id, "climate",
            user_id, properties=properties,
        ),
        ExperienceAction(
            "climate.set_temperature", observation.climate_entity_id,
            "temperature", observation.target_celsius,
        ),
        {"temperature_celsius": observation.start_celsius},
        {"temperature_celsius": observation.target_celsius},
        ExperienceEffect(
            observation.target_celsius,
            observation.target_celsius if observation.reached_target else None,
            observation.duration_seconds,
            observation.reached_target and observation.service_succeeded,
            (EffectEvidenceState.VERIFIED_SUCCESS
             if observation.usable else EffectEvidenceState.INVALID),
        ),
        evidence, ExperienceProvenance.GOAL_RUN,
        ExperienceQuality.COMPLETE if observation.usable else ExperienceQuality.INVALID,
    )


def thermal_observations_from_experiences(
    records: tuple[ExperienceRecord, ...], binding: ThermalBinding
) -> tuple[ThermalObservation, ...]:
    result: list[ThermalObservation] = []
    for record in records:
        if (
            record.context.area_id != binding.area_id
            or record.action.operator_id != "climate.set_temperature"
            or record.action.target_id != binding.climate_entity_id
        ):
            continue
        start = _numeric(record.before.get("temperature_celsius"))
        target = _numeric(record.action.requested_value)
        duration = record.effect.latency_seconds
        temperature_source = record.context.properties.get("temperature_entity_id")
        if (
            start is None or target is None or duration is None
            or not isinstance(temperature_source, str)
            or temperature_source != binding.temperature_entity_id
        ):
            continue
        result.append(ThermalObservation(
            record.timestamp - timedelta(seconds=duration), record.timestamp,
            binding.area_id, temperature_source, binding.climate_entity_id,
            start, target, duration, record.effect.success,
            _numeric(record.context.properties.get("outdoor_celsius")),
            bool(record.context.properties.get("window_opened", False)),
            record.effect.success,
            bool(record.context.properties.get("source_changed", False)),
            bool(record.context.properties.get("concurrent_action", False)),
        ))
    return tuple(result)


def thermal_model_to_learned(
    model: ThermalModel, policy: LearningPolicy = DEFAULT_LEARNING_POLICY
) -> LearnedModel:
    parameters: dict[str, str | float | int | bool] = {
        "temperature_entity_id": model.binding.temperature_entity_id,
        "climate_entity_id": model.binding.climate_entity_id,
        "binding_confirmed": model.binding.confirmed,
        "intercept_seconds": model.intercept_seconds,
        "delta_coefficient": model.delta_coefficient,
        "mae_seconds": model.mae_seconds,
        "residual_median_seconds": model.residual_median_seconds,
        "residual_mad_seconds": model.residual_mad_seconds,
        "residual_p90_seconds": model.residual_p90_seconds,
        "drift_detected": model.drift_detected,
        "updated_at": model.updated_at.isoformat(),
        "validation_sample_count": model.validation_sample_count,
    }
    if model.binding.outdoor_temperature_entity_id is not None:
        parameters["outdoor_temperature_entity_id"] = model.binding.outdoor_temperature_entity_id
    if model.outside_gap_coefficient is not None:
        parameters["outside_gap_coefficient"] = model.outside_gap_coefficient
    for key, value in (
        ("min_temperature_delta", model.min_temperature_delta),
        ("max_temperature_delta", model.max_temperature_delta),
        ("min_start_temperature", model.min_start_temperature),
        ("max_start_temperature", model.max_start_temperature),
        ("min_outdoor_gap", model.min_outdoor_gap),
        ("max_outdoor_gap", model.max_outdoor_gap),
        ("validation_mae_seconds", model.validation_mae_seconds),
        ("validation_median_absolute_error_seconds", model.validation_median_absolute_error_seconds),
        ("validation_p90_absolute_error_seconds", model.validation_p90_absolute_error_seconds),
    ):
        if value is not None:
            parameters[key] = value
    health = (
        ModelHealth.INVALID if model.invalidation_reason else
        ModelHealth.DRIFT_DETECTED if model.drift_detected else ModelHealth.VALID
    )
    if health is ModelHealth.VALID:
        authoritative_mae = (
            model.validation_mae_seconds
            if model.validation_mae_seconds is not None else model.mae_seconds
        )
        if authoritative_mae > policy.maximum_thermal_mae_minutes * 60.0:
            health = ModelHealth.UNRELIABLE
        elif (
            model.sample_count < policy.usable_model_samples
            or model.confidence < policy.minimum_planning_confidence
            or model.validation_sample_count == 0
        ):
            health = ModelHealth.LOW_CONFIDENCE
    validation_metrics = {
        "training_mae_seconds": model.mae_seconds,
        "residual_mad_seconds": model.residual_mad_seconds,
    }
    if model.validation_mae_seconds is not None:
        validation_metrics["holdout_mae_seconds"] = model.validation_mae_seconds
    if model.validation_median_absolute_error_seconds is not None:
        validation_metrics["holdout_median_absolute_error_seconds"] = model.validation_median_absolute_error_seconds
    if model.validation_p90_absolute_error_seconds is not None:
        validation_metrics["holdout_p90_absolute_error_seconds"] = model.validation_p90_absolute_error_seconds
    return LearnedModel(
        model.model_id, LearnedKind.THERMAL_MODEL, model.binding.area_id,
        {"area_id": model.binding.area_id}, parameters, KnowledgeState.OBSERVED,
        model.confidence, model.sample_count, model.trained_from,
        model.trained_until, (), model.model_version,
        validation_metrics,
        health=health, invalidation_reason=model.invalidation_reason,
    )


def thermal_model_from_learned(model: LearnedModel) -> ThermalModel | None:
    if model.kind is not LearnedKind.THERMAL_MODEL:
        return None
    values = model.parameters
    temperature_entity = values.get("temperature_entity_id")
    climate_entity = values.get("climate_entity_id")
    if not isinstance(temperature_entity, str) or not isinstance(climate_entity, str):
        return None
    required = tuple(_numeric(values.get(key)) for key in (
        "intercept_seconds", "delta_coefficient", "mae_seconds",
        "residual_median_seconds", "residual_mad_seconds", "residual_p90_seconds",
    ))
    if any(value is None for value in required):
        return None
    outdoor_source = values.get("outdoor_temperature_entity_id")
    return ThermalModel(
        model.model_id, model.model_version,
        ThermalBinding(
            model.subject, temperature_entity, climate_entity,
            outdoor_source if isinstance(outdoor_source, str) else None,
            bool(values.get("binding_confirmed", False)),
        ),
        required[0] or 0.0, required[1] or 0.0,
        _numeric(values.get("outside_gap_coefficient")), model.sample_count,
        model.confidence, required[2] or 0.0, required[3] or 0.0,
        required[4] or 0.0, required[5] or 0.0, model.first_observed,
        model.last_observed, _stored_datetime(values.get("updated_at"), model.last_observed),
        bool(values.get("drift_detected", False)), model.invalidation_reason,
        _numeric(values.get("min_temperature_delta")),
        _numeric(values.get("max_temperature_delta")),
        _numeric(values.get("min_start_temperature")),
        _numeric(values.get("max_start_temperature")),
        _numeric(values.get("min_outdoor_gap")),
        _numeric(values.get("max_outdoor_gap")),
        int(_numeric(values.get("validation_sample_count")) or 0),
        _numeric(values.get("validation_mae_seconds")),
        _numeric(values.get("validation_median_absolute_error_seconds")),
        _numeric(values.get("validation_p90_absolute_error_seconds")),
    )


def train_thermal_model(
    binding: ThermalBinding,
    observations: tuple[ThermalObservation, ...],
    policy: LearningPolicy,
    *,
    model_version: int = 1,
    now: datetime | None = None,
) -> ThermalModel | None:
    usable = tuple(
        item for item in observations
        if item.usable and item.area_id == binding.area_id
        and item.temperature_entity_id == binding.temperature_entity_id
        and item.climate_entity_id == binding.climate_entity_id
    )
    if len(usable) < policy.minimum_model_samples:
        return None
    use_outside = (
        binding.outdoor_temperature_entity_id is not None
        and len(usable) >= policy.usable_model_samples
        and all(item.outdoor_celsius is not None for item in usable)
    )
    ordered = tuple(sorted(usable, key=lambda item: (item.ended_at, item.started_at)))
    holdout_count = (
        max(1, math.ceil(len(ordered) * policy.thermal_holdout_fraction))
        if len(ordered) >= policy.thermal_minimum_holdout_samples else 0
    )
    training = ordered[:-holdout_count] if holdout_count else ordered
    holdout = ordered[-holdout_count:] if holdout_count else ()
    rows = tuple(_row(item, use_outside) for item in training)
    coefficients = _least_squares(rows)
    predictions = tuple(_dot(row[:-1], coefficients) for row in rows)
    residuals = tuple(row[-1] - prediction for row, prediction in zip(rows, predictions))
    absolute = tuple(abs(item) for item in residuals)
    mae = sum(absolute) / len(absolute)
    mad = median(abs(item - median(residuals)) for item in residuals)
    p90 = _quantile(absolute, 0.90)
    validation_absolute = tuple(
        abs(row[-1] - _dot(row[:-1], coefficients))
        for row in (_row(item, use_outside) for item in holdout)
    )
    validation_mae = (
        sum(validation_absolute) / len(validation_absolute)
        if validation_absolute else None
    )
    authoritative_error = validation_mae if validation_mae is not None else mae
    evidence_factor = min(1.0, len(usable) / policy.usable_model_samples)
    error_factor = max(0.0, 1.0 - authoritative_error / (policy.maximum_thermal_mae_minutes * 60.0))
    confidence = max(0.0, min(1.0, evidence_factor * error_factor))
    current = now or datetime.now(timezone.utc)
    return ThermalModel(
        f"thermal:{binding.area_id}", model_version, binding,
        coefficients[0], coefficients[1], coefficients[2] if use_outside else None,
        len(usable), confidence, mae, median(residuals), mad, p90,
        min(item.started_at for item in usable), max(item.ended_at for item in usable),
        current, invalidation_reason=(
            "non_positive_temperature_delta_coefficient"
            if coefficients[1] <= 0.0 else None
        ),
        min_temperature_delta=min(item.target_celsius - item.start_celsius for item in usable),
        max_temperature_delta=max(item.target_celsius - item.start_celsius for item in usable),
        min_start_temperature=min(item.start_celsius for item in usable),
        max_start_temperature=max(item.start_celsius for item in usable),
        min_outdoor_gap=(
            min(max(0.0, item.start_celsius - (item.outdoor_celsius or 0.0)) for item in usable)
            if use_outside else None
        ),
        max_outdoor_gap=(
            max(max(0.0, item.start_celsius - (item.outdoor_celsius or 0.0)) for item in usable)
            if use_outside else None
        ),
        validation_sample_count=len(validation_absolute),
        validation_mae_seconds=validation_mae,
        validation_median_absolute_error_seconds=(median(validation_absolute) if validation_absolute else None),
        validation_p90_absolute_error_seconds=(_quantile(validation_absolute, 0.90) if validation_absolute else None),
    )


def predict_thermal_duration(
    model: ThermalModel | None,
    *,
    current_celsius: float,
    target_celsius: float,
    outdoor_celsius: float | None,
    policy: LearningPolicy,
    now: datetime | None = None,
) -> PredictionResult[float]:
    current = now or datetime.now(timezone.utc)
    if model is None:
        return _empty(PredictionStatus.INSUFFICIENT_DATA, current)
    valid_until = model.updated_at + timedelta(days=policy.stale_model_days)
    if model.invalidation_reason:
        return _model_prediction(model, policy, PredictionStatus.MODEL_INVALID,
                                 explanation=model.invalidation_reason)
    if model.drift_detected:
        return _model_prediction(model, policy, PredictionStatus.DRIFT_DETECTED,
                                 explanation="Systematisch verschobene Residuen erkannt.")
    if current > valid_until:
        return _model_prediction(model, policy, PredictionStatus.STALE_MODEL,
                                 explanation="Das Modell ist älter als die zentrale Gültigkeitsgrenze.")
    if target_celsius <= current_celsius:
        return _model_prediction(model, policy, PredictionStatus.INCOMPATIBLE_CONTEXT,
                                 explanation="Das Ziel erfordert keinen Heizvorgang.")
    if model.outside_gap_coefficient is not None and outdoor_celsius is None:
        return _model_prediction(model, policy, PredictionStatus.INCOMPATIBLE_CONTEXT,
                                 explanation="Die bestätigte Außentemperaturmessung fehlt.")
    delta = target_celsius - current_celsius
    if _outside_domain(
        delta, model.min_temperature_delta, model.max_temperature_delta,
        policy.thermal_extrapolation_margin_ratio,
    ):
        return _model_prediction(
            model, policy, PredictionStatus.OUT_OF_DISTRIBUTION,
            explanation="Die angefragte Temperaturänderung liegt außerhalb der Trainingsdomäne.",
        )
    outdoor_gap = (
        max(0.0, current_celsius - outdoor_celsius)
        if outdoor_celsius is not None else None
    )
    if model.outside_gap_coefficient is not None and outdoor_gap is not None and _outside_domain(
        outdoor_gap, model.min_outdoor_gap, model.max_outdoor_gap,
        policy.thermal_extrapolation_margin_ratio,
    ):
        return _model_prediction(
            model, policy, PredictionStatus.OUT_OF_DISTRIBUTION,
            explanation="Die Außentemperaturdifferenz liegt außerhalb der Trainingsdomäne.",
        )
    if model.sample_count < policy.usable_model_samples:
        return _model_prediction(model, policy, PredictionStatus.LOW_CONFIDENCE,
                                 explanation="Noch nicht genug verwertbare Heizvorgänge.")
    authoritative_mae = (
        model.validation_mae_seconds
        if model.validation_mae_seconds is not None else model.mae_seconds
    )
    if authoritative_mae > policy.maximum_thermal_mae_minutes * 60.0:
        return _model_prediction(model, policy, PredictionStatus.MODEL_UNRELIABLE,
                                 explanation="Der historische mittlere Fehler ist zu hoch.")
    if not policy.permits_planning(model.confidence, model.sample_count):
        return _model_prediction(model, policy, PredictionStatus.LOW_CONFIDENCE,
                                 explanation="Konfidenz unterhalb der Planning-Schwelle.")
    if model.validation_sample_count == 0:
        return _model_prediction(
            model, policy, PredictionStatus.LOW_CONFIDENCE,
            explanation="Noch keine deterministische Holdout-Validierung verfügbar.",
        )
    features = [1.0, delta]
    names = ["temperature_delta"]
    if model.outside_gap_coefficient is not None and outdoor_celsius is not None:
        features.append(max(0.0, current_celsius - outdoor_celsius))
        names.append("outside_temperature_gap")
    coefficients = [model.intercept_seconds, model.delta_coefficient]
    if model.outside_gap_coefficient is not None:
        coefficients.append(model.outside_gap_coefficient)
    estimate = max(0.0, _dot(tuple(features), tuple(coefficients)))
    uncertainty = max(model.residual_p90_seconds, 60.0)
    return _model_prediction(
        model, policy, PredictionStatus.OK, value=estimate,
        uncertainty=(max(0.0, estimate - uncertainty), estimate + uncertainty),
        input_features=tuple(names),
        explanation=(f"{model.sample_count} verwertbare Vorgänge; "
                     f"MAE {model.mae_seconds / 60:.1f} min; "
                     f"deterministische p90-Reserve {uncertainty / 60:.1f} min."),
    )


def detect_thermal_drift(
    model: ThermalModel, residual_seconds: tuple[float, ...], policy: LearningPolicy
) -> bool:
    if len(residual_seconds) < policy.drift_window:
        return False
    recent = residual_seconds[-policy.drift_window:]
    threshold = policy.drift_residual_minutes * 60.0
    return abs(median(recent)) > threshold and all(
        (item > 0) == (recent[0] > 0) for item in recent
    )


def thermal_residuals(
    model: ThermalModel, observations: tuple[ThermalObservation, ...]
) -> tuple[float, ...]:
    """Evaluate later observations against one frozen model version."""
    result: list[float] = []
    for item in observations:
        features = [1.0, item.target_celsius - item.start_celsius]
        coefficients = [model.intercept_seconds, model.delta_coefficient]
        if model.outside_gap_coefficient is not None:
            if item.outdoor_celsius is None:
                continue
            features.append(max(0.0, item.start_celsius - item.outdoor_celsius))
            coefficients.append(model.outside_gap_coefficient)
        result.append(item.duration_seconds - _dot(tuple(features), tuple(coefficients)))
    return tuple(result)


def _empty(status: PredictionStatus, now: datetime) -> PredictionResult[float]:
    return PredictionResult(status, None, None, 0.0, None, None, 0, now, None,
                            None, (), "Keine ausreichend validierte historische Evidenz.")


def _model_prediction(
    model: ThermalModel,
    policy: LearningPolicy,
    status: PredictionStatus,
    *,
    value: float | None = None,
    uncertainty: tuple[float, float] | None = None,
    input_features: tuple[str, ...] = (),
    explanation: str,
) -> PredictionResult[float]:
    return PredictionResult(
        status, value, uncertainty, model.confidence, model.model_id,
        model.model_version, model.sample_count, model.updated_at,
        model.updated_at + timedelta(days=policy.stale_model_days),
        (model.trained_from, model.trained_until), input_features, explanation,
    )


def _row(item: ThermalObservation, outside: bool) -> tuple[float, ...]:
    values = [1.0, item.target_celsius - item.start_celsius]
    if outside:
        assert item.outdoor_celsius is not None
        values.append(max(0.0, item.start_celsius - item.outdoor_celsius))
    values.append(item.duration_seconds)
    return tuple(values)


def _least_squares(rows: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
    width = len(rows[0]) - 1
    matrix = [[0.0 for _ in range(width + 1)] for _ in range(width)]
    for row in rows:
        x, y = row[:-1], row[-1]
        for i in range(width):
            for j in range(width):
                matrix[i][j] += x[i] * x[j]
            matrix[i][width] += x[i] * y
    # Fixed-order Gaussian elimination with a tiny deterministic ridge for
    # collinear contexts. It has no random initialization or iteration order.
    for i in range(width):
        matrix[i][i] += 1e-9
    for column in range(width):
        pivot = max(range(column, width), key=lambda row: abs(matrix[row][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        if math.isclose(divisor, 0.0, abs_tol=1e-12):
            continue
        matrix[column] = [item / divisor for item in matrix[column]]
        for row in range(width):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(matrix[row], matrix[column])
            ]
    return tuple(matrix[index][width] for index in range(width))


def _dot(values: tuple[float, ...], coefficients: tuple[float, ...]) -> float:
    return sum(value * coefficient for value, coefficient in zip(values, coefficients))


def _quantile(values: tuple[float, ...], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _numeric(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _outside_domain(
    value: float, minimum: float | None, maximum: float | None, margin_ratio: float
) -> bool:
    if minimum is None or maximum is None:
        return False
    width = max(0.0, maximum - minimum)
    margin = width * max(0.0, margin_ratio)
    return value < minimum - margin or value > maximum + margin


def _stored_datetime(value: object, default: datetime) -> datetime:
    if not isinstance(value, str):
        return default
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return default
    return result if result.tzinfo is not None else default


__all__ = (
    "ThermalBinding", "ThermalModel", "ThermalObservation",
    "detect_thermal_drift", "predict_thermal_duration", "train_thermal_model",
    "thermal_residuals",
    "thermal_model_from_learned", "thermal_model_to_learned",
    "thermal_observation_to_experience", "thermal_observations_from_experiences",
)
