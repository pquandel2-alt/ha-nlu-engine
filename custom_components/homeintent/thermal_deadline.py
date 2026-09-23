"""Typed persistent checkpoints for an advised thermal deadline goal."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from .entities import EntitySnapshot
from .goal_run import (
    FailureCode,
    GoalRunStatus,
    GoalRunStore,
    StepExecutionRecord,
    VerificationRecord,
)
from .nlu.primitives import SemanticProperty
from .nlu.unit_reasoning import normalize_measurement
from .service_call import ServiceCallPlan
from .thermal_tracker import ThermalExperienceTracker


class ThermalCheckpointPhase(StrEnum):
    START = "start"
    INTERMEDIATE = "intermediate"
    FINAL = "final"


@dataclass(frozen=True)
class ThermalDeadlineCheckpoint:
    """Narrow evidence payload carried by a HomeIntent-owned one-shot."""

    phase: ThermalCheckpointPhase
    goal_id: str
    area_id: str
    climate_entity_id: str
    measurement_entity_id: str
    target_value: float
    model_id: str
    predicted_duration_seconds: float
    uncertainty_buffer_seconds: float

    def to_service_data(self) -> dict[str, str | float]:
        return {
            "phase": self.phase.value,
            "goal_id": self.goal_id,
            "area_id": self.area_id,
            "climate_entity_id": self.climate_entity_id,
            "measurement_entity_id": self.measurement_entity_id,
            "target_value": self.target_value,
            "model_id": self.model_id,
            "predicted_duration_seconds": self.predicted_duration_seconds,
            "uncertainty_buffer_seconds": self.uncertainty_buffer_seconds,
        }

    @classmethod
    def from_service_data(
        cls, raw: Mapping[str, object]
    ) -> ThermalDeadlineCheckpoint | None:
        try:
            phase = ThermalCheckpointPhase(str(raw["phase"]))
            texts = tuple(
                str(raw[key])
                for key in (
                    "goal_id", "area_id", "climate_entity_id",
                    "measurement_entity_id", "model_id",
                )
            )
            target = _finite_number(raw["target_value"])
            duration = _finite_number(raw["predicted_duration_seconds"])
            buffer = _finite_number(raw["uncertainty_buffer_seconds"])
        except (KeyError, TypeError, ValueError):
            return None
        if (
            any(not value or len(value) > 255 for value in texts)
            or not texts[2].startswith("climate.")
            or "." not in texts[3]
            or target is None or not -100.0 <= target <= 150.0
            or duration is None or duration <= 0.0
            or buffer is None or buffer < 0.0
        ):
            return None
        return cls(
            phase=phase,
            goal_id=texts[0],
            area_id=texts[1],
            climate_entity_id=texts[2],
            measurement_entity_id=texts[3],
            target_value=target,
            model_id=texts[4],
            predicted_duration_seconds=duration,
            uncertainty_buffer_seconds=buffer,
        )


def checkpoint_service_action(
    checkpoint: ThermalDeadlineCheckpoint,
) -> dict[str, object]:
    """Render the sole internal, non-actuating checkpoint service action."""
    return {
        "action": "homeintent.thermal_deadline_checkpoint",
        "data": checkpoint.to_service_data(),
    }


def append_start_checkpoint(
    config: Mapping[str, object], checkpoint: ThermalDeadlineCheckpoint
) -> dict[str, object] | None:
    """Insert START before a one-shot's self-delete without changing its action."""
    if checkpoint.phase is not ThermalCheckpointPhase.START:
        return None
    raw_actions = config.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        return None
    actions = list(raw_actions)
    insertion = len(actions)
    last = actions[-1]
    if isinstance(last, Mapping) and last.get("action") == "homeintent.delete_automation":
        insertion -= 1
    actions.insert(insertion, checkpoint_service_action(checkpoint))
    return {**config, "actions": actions}


def checkpoint_automation_config(
    checkpoint: ThermalDeadlineCheckpoint,
    *,
    scheduled_for: datetime,
    automation_id: str,
) -> dict[str, object] | None:
    """Build a date-guarded one-shot which can only report a checkpoint."""
    if (
        checkpoint.phase is ThermalCheckpointPhase.START
        or scheduled_for.tzinfo is None
        or not automation_id
    ):
        return None
    return {
        "alias": f"HomeIntent thermal {checkpoint.phase.value}: {checkpoint.goal_id}",
        "triggers": [{
            "trigger": "time",
            "at": scheduled_for.strftime("%H:%M:%S"),
        }],
        "conditions": [{
            "condition": "template",
            "value_template": (
                "{{ now().date().isoformat() == '"
                + scheduled_for.date().isoformat()
                + "' }}"
            ),
        }],
        "actions": [
            checkpoint_service_action(checkpoint),
            {
                "action": "homeintent.delete_automation",
                "data": {"automation_id": automation_id},
            },
        ],
    }


async def async_process_thermal_checkpoint(
    checkpoint: ThermalDeadlineCheckpoint,
    snapshots: tuple[EntitySnapshot, ...],
    tracker: ThermalExperienceTracker,
    goal_runs: GoalRunStore,
    *,
    now: datetime,
) -> bool | None:
    """Observe one checkpoint and finalize the existing scheduled GoalRun."""
    if now.tzinfo is None:
        raise ValueError("Thermal checkpoint timestamps require a timezone")
    if checkpoint.phase is ThermalCheckpointPhase.START:
        tracker.observe_action(
            ServiceCallPlan(
                "climate", "set_temperature", checkpoint.climate_entity_id,
                {"temperature": checkpoint.target_value},
            ),
            snapshots,
            occurred_at=now,
        )
        scheduled = await goal_runs.async_latest(goal_id=checkpoint.goal_id)
        if scheduled is not None:
            tracker.associate_goal_run(scheduled)
            await goal_runs.async_append(replace(
                scheduled,
                updated_at=now.isoformat(),
                status=GoalRunStatus.RUNNING,
                evidence=(*scheduled.evidence, "thermal_start_observed"),
            ))
        return None
    if checkpoint.phase is ThermalCheckpointPhase.INTERMEDIATE:
        # This checkpoint is intentionally observation-only. State-event
        # tracking continues; no corrective setpoint is authorized.
        return None

    await tracker.async_finalize(
        checkpoint.climate_entity_id, snapshots, occurred_at=now
    )
    scheduled = await goal_runs.async_latest(goal_id=checkpoint.goal_id)
    if scheduled is None:
        return None
    sensor = next(
        (item for item in snapshots
         if item.entity_id == checkpoint.measurement_entity_id),
        None,
    )
    observed: str | None = None
    current_celsius: float | None = None
    target_celsius: float | None = None
    if sensor is not None and sensor.state not in {"unknown", "unavailable"}:
        observed = sensor.state
        try:
            current = normalize_measurement(
                float(sensor.state), sensor.unit, SemanticProperty.TEMPERATURE
            )
            target = normalize_measurement(
                checkpoint.target_value, sensor.unit, SemanticProperty.TEMPERATURE
            )
        except ValueError:
            current = target = None
        current_celsius = current.value if current is not None else None
        target_celsius = target.value if target is not None else None
    success = (
        current_celsius is not None and target_celsius is not None
        and current_celsius >= target_celsius - 0.1
    )
    failure = None if success else (
        FailureCode.TARGET_UNAVAILABLE if observed is None else FailureCode.WRONG_STATE
    )
    start_observed = "thermal_start_observed" in scheduled.evidence
    verification = VerificationRecord(
        checkpoint.measurement_entity_id,
        f"temperature={target_celsius:g}"
        if target_celsius is not None else "temperature=unknown",
        observed,
        success,
        failure,
        now.isoformat(),
    )
    final_run = replace(
        scheduled,
        updated_at=now.isoformat(),
        selected_targets=(checkpoint.climate_entity_id,),
        steps=(*(
            step for step in scheduled.steps
            if step.step_id != "scheduled-setpoint"
        ), StepExecutionRecord(
            "thermal-final-verification",
            "CLIMATE_SET_TEMPERATURE" if start_observed else None,
            (checkpoint.climate_entity_id,), ("confirmed_measurement_binding",),
            True if start_observed else None, (verification,),
            failure if start_observed else FailureCode.SERVICE_ERROR,
            "Thermisches Ergebnis zum bestätigten Zieltermin geprüft.",
        )),
        status=GoalRunStatus.SUCCESS if success else GoalRunStatus.FAILURE,
        failures=tuple(dict.fromkeys((
            *((FailureCode.SERVICE_ERROR,) if not start_observed else ()),
            *((failure,) if failure is not None else ()),
        ))),
        evidence=(*scheduled.evidence,
                  f"prediction_model={checkpoint.model_id}",
                  f"prediction_seconds={checkpoint.predicted_duration_seconds:g}",
                  f"uncertainty_buffer_seconds={checkpoint.uncertainty_buffer_seconds:g}"),
    )
    await goal_runs.async_append(final_run)
    return success


def _finite_number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = float(value)
    return result if result == result and abs(result) != float("inf") else None


__all__ = (
    "ThermalCheckpointPhase", "ThermalDeadlineCheckpoint",
    "async_process_thermal_checkpoint",
    "append_start_checkpoint", "checkpoint_automation_config",
    "checkpoint_service_action",
)
