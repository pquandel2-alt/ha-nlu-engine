"""Lifecycle-bound collection of compact, unambiguous heating experiences."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Mapping, cast

from .entities import EntitySnapshot
from .goal_run import GoalRun
from .learning_manager import LearningManager
from .learning_policy import LearningMode
from .nlu.primitives import SemanticProperty
from .nlu.unit_reasoning import normalize_measurement
from .service_call import ServiceCallPlan
from .thermal_model import ThermalBinding, ThermalObservation


@dataclass(frozen=True)
class ActiveThermalCycle:
    binding: ThermalBinding
    started_at: datetime
    start_celsius: float
    target_celsius: float
    outdoor_celsius: float | None
    goal_id: str
    run_id: str
    user_id: str | None = None
    window_opened: bool = False
    service_succeeded: bool = True
    source_changed: bool = False
    concurrent_action: bool = False


class ThermalExperienceTracker:
    """Tracks only HomeIntent-owned setpoint actions and exact bindings."""

    def __init__(self, manager: LearningManager) -> None:
        self._manager = manager
        self._active: dict[str, ActiveThermalCycle] = {}
        self._counter = 0

    @property
    def active(self) -> tuple[ActiveThermalCycle, ...]:
        return tuple(self._active[key] for key in sorted(self._active))

    def observe_action(
        self,
        plan: ServiceCallPlan,
        entities: tuple[EntitySnapshot, ...],
        *,
        occurred_at: datetime,
    ) -> None:
        """Start only when one climate target and one room sensor are exact."""
        if (
            self._manager.policy.learning_mode is LearningMode.OFF
            or
            plan.domain != "climate" or plan.service != "set_temperature"
            or not isinstance(plan.entity_id, str)
        ):
            return
        data = cast(Mapping[str, object], plan.data)
        raw_target = data.get("temperature")
        if not isinstance(raw_target, (int, float)):
            return
        climate = next(
            (item for item in entities if item.entity_id == plan.entity_id), None
        )
        if climate is None or climate.area_id is None:
            return
        candidates = tuple(
            item for item in entities
            if item.area_id == climate.area_id
            and item.domain == "sensor"
            and item.device_class == "temperature"
            and item.state not in {"unknown", "unavailable"}
        )
        if len(candidates) != 1:
            return
        sensor = candidates[0]
        current = _temperature(sensor)
        target = normalize_measurement(
            float(raw_target), sensor.unit, SemanticProperty.TEMPERATURE
        )
        if current is None or target is None or target.value <= current:
            return
        previous = self._active.get(plan.entity_id)
        self._counter += 1
        self._active[plan.entity_id] = ActiveThermalCycle(
            ThermalBinding(
                climate.area_id, sensor.entity_id, climate.entity_id,
                confirmed=True,
            ),
            occurred_at, current, target.value, None,
            f"pending:{self._counter}", f"thermal-pending:{self._counter}",
            concurrent_action=previous is not None,
        )

    def associate_goal_run(self, run: GoalRun) -> None:
        """Attach authoritative GoalRun provenance to a just-started cycle."""
        targets = {
            target
            for step in run.steps
            if step.operator_id == "CLIMATE_SET_TEMPERATURE"
            for target in step.selected_targets
        }
        for target in targets:
            cycle = self._active.get(target)
            if cycle is not None:
                self._active[target] = replace(
                    cycle, goal_id=run.goal_id, run_id=run.run_id,
                    user_id=run.user_id,
                )

    async def async_observe_states(
        self,
        entities: tuple[EntitySnapshot, ...],
        *,
        occurred_at: datetime,
    ) -> None:
        by_id = {item.entity_id: item for item in entities}
        completed: list[tuple[str, ActiveThermalCycle, bool]] = []
        for climate_id, cycle in tuple(self._active.items()):
            sensor = by_id.get(cycle.binding.temperature_entity_id)
            climate = by_id.get(climate_id)
            if sensor is None or climate is None:
                completed.append((climate_id, replace(cycle, source_changed=True), False))
                continue
            windows = tuple(
                item for item in entities
                if item.area_id == cycle.binding.area_id
                and item.device_class == "window"
                and item.state.casefold() in {"on", "open", "opening"}
            )
            if windows:
                cycle = replace(cycle, window_opened=True)
                self._active[climate_id] = cycle
            current = _temperature(sensor)
            invalid = (
                sensor.state in {"unknown", "unavailable"}
                or climate.state in {"unknown", "unavailable"}
                or occurred_at <= cycle.started_at
                or occurred_at - cycle.started_at > timedelta(hours=12)
            )
            if invalid or current is None:
                completed.append((climate_id, cycle, False))
            elif current >= cycle.target_celsius - 0.1:
                completed.append((climate_id, cycle, True))
        for climate_id, cycle, reached in completed:
            self._active.pop(climate_id, None)
            observation = ThermalObservation(
                cycle.started_at, occurred_at, cycle.binding.area_id,
                cycle.binding.temperature_entity_id,
                cycle.binding.climate_entity_id, cycle.start_celsius,
                cycle.target_celsius,
                max(0.0, (occurred_at - cycle.started_at).total_seconds()),
                reached, cycle.outdoor_celsius, cycle.window_opened,
                cycle.service_succeeded, cycle.source_changed,
                cycle.concurrent_action,
            )
            await self._manager.async_record_thermal_observation(
                cycle.binding, observation, goal_id=cycle.goal_id,
                run_id=cycle.run_id, user_id=cycle.user_id,
            )
            if cycle.source_changed:
                await self._manager.async_invalidate_thermal_model(
                    cycle.binding.area_id, "measurement_source_removed"
                )

    async def async_finalize(
        self,
        climate_entity_id: str,
        entities: tuple[EntitySnapshot, ...],
        *,
        occurred_at: datetime,
    ) -> bool | None:
        """Close an active cycle at its authoritative goal deadline."""
        cycle = self._active.pop(climate_entity_id, None)
        if cycle is None:
            return None
        by_id = {item.entity_id: item for item in entities}
        sensor = by_id.get(cycle.binding.temperature_entity_id)
        climate = by_id.get(climate_entity_id)
        current = _temperature(sensor) if sensor is not None else None
        source_changed = sensor is None or climate is None
        reached = (
            not source_changed
            and current is not None
            and current >= cycle.target_celsius - 0.1
        )
        finalized = replace(cycle, source_changed=cycle.source_changed or source_changed)
        observation = ThermalObservation(
            finalized.started_at, occurred_at, finalized.binding.area_id,
            finalized.binding.temperature_entity_id,
            finalized.binding.climate_entity_id, finalized.start_celsius,
            finalized.target_celsius,
            max(0.0, (occurred_at - finalized.started_at).total_seconds()),
            reached, finalized.outdoor_celsius, finalized.window_opened,
            finalized.service_succeeded, finalized.source_changed,
            finalized.concurrent_action,
        )
        await self._manager.async_record_thermal_observation(
            finalized.binding, observation, goal_id=finalized.goal_id,
            run_id=finalized.run_id, user_id=finalized.user_id,
        )
        if finalized.source_changed:
            await self._manager.async_invalidate_thermal_model(
                finalized.binding.area_id, "measurement_source_removed"
            )
        return reached


def _temperature(entity: EntitySnapshot) -> float | None:
    try:
        raw = float(entity.state)
    except ValueError:
        return None
    normalized = normalize_measurement(
        raw, entity.unit, SemanticProperty.TEMPERATURE
    )
    return normalized.value if normalized is not None else None


__all__ = ("ActiveThermalCycle", "ThermalExperienceTracker")
