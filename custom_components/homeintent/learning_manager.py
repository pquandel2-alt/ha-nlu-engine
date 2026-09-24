"""Bounded event-driven coordinator from GoalRun evidence to V11 models."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

from .experience import ExperienceQuality, extract_goal_run_experiences
from .experience_store import ExperienceStore
from .goal_run import EffectEvidenceState, GoalRun, GoalRunStatus
from .learning_policy import KnowledgeState, LearningPolicy
from .model_registry import (
    LearnedKind,
    LearnedModel,
    ModelHealth,
    ModelRegistry,
    UpsertResult,
)
from .predictive_house_model import PredictiveHouseModel
from .statistical_models import (
    EffectTimingModel,
    ReliabilityStatistic,
    train_effect_timing,
    train_reliability,
)
from .thermal_model import (
    ThermalBinding,
    ThermalModel,
    ThermalObservation,
    thermal_model_from_learned,
    thermal_model_to_learned,
    detect_thermal_drift,
    thermal_residuals,
    thermal_observations_from_experiences,
    train_thermal_model,
)
from .habit_discovery import SuggestionStatus


class LearningManager:
    """Updates only transparent statistics; it cannot create a plan/action."""

    def __init__(
        self,
        experiences: ExperienceStore,
        models: ModelRegistry,
        predictive_house: PredictiveHouseModel,
        policy: LearningPolicy,
    ) -> None:
        self.experiences = experiences
        self.models = models
        self.predictive_house = predictive_house
        self.policy = policy
        self.models.bind_active_view(
            self._activate_learned_model, self._deactivate_learned_model
        )

    async def async_restore_models(self) -> None:
        """Rehydrate the read-only prediction view after an HA restart."""
        await self.models.async_restore_active_view()

    def _activate_learned_model(self, model: LearnedModel) -> None:
        """Update the advisory view only after authoritative registry acceptance."""
        if model.health is ModelHealth.INVALID:
            self.predictive_house.forget(model.model_id)
            return
        if model.kind is LearnedKind.THERMAL_MODEL:
            thermal = thermal_model_from_learned(model)
            if thermal is not None:
                self.predictive_house.install_thermal(thermal)
        elif model.kind is LearnedKind.EFFECT_TIMING:
            operator = model.context.get("operator_id")
            median = _number(model.parameters.get("median_seconds"))
            p90 = _number(model.parameters.get("p90_seconds"))
            p95 = _number(model.parameters.get("p95_seconds"))
            mad = _number(model.parameters.get("mad_seconds"))
            if isinstance(operator, str) and None not in (median, p90, p95, mad):
                self.predictive_house.install_effect_timing(EffectTimingModel(
                    model.model_id, operator, model.subject, model.sample_count,
                    median or 0.0, p90 or 0.0, p95 or 0.0, mad or 0.0,
                    model.confidence, model.first_observed, model.last_observed,
                    model.expires_at,
                ))
        elif model.kind is LearnedKind.RELIABILITY:
            operator = model.context.get("operator_id")
            rate = _number(model.parameters.get("success_rate"))
            if isinstance(operator, str) and rate is not None:
                successes = round(rate * model.sample_count)
                self.predictive_house.install_reliability(ReliabilityStatistic(
                    model.model_id, operator, model.subject, successes,
                    model.sample_count - successes, model.sample_count, rate,
                    model.confidence, model.first_observed, model.last_observed,
                    model.expires_at,
                ))

    def _deactivate_learned_model(self, model_id: str) -> None:
        self.predictive_house.forget(model_id)

    async def async_update_thermal_model(
        self, binding: ThermalBinding
    ) -> ThermalModel | None:
        """Train only from compact stored experiences and persist the result."""
        if not self.policy.predictive_models_enabled or not binding.confirmed:
            return None
        records = await self.experiences.async_list()
        observations = thermal_observations_from_experiences(records, binding)
        existing = await self.models.async_get(f"thermal:{binding.area_id}")
        if existing is not None and (
            existing.parameters.get("temperature_entity_id")
            != binding.temperature_entity_id
            or existing.parameters.get("climate_entity_id")
            != binding.climate_entity_id
        ):
            await self.async_invalidate_thermal_model(
                binding.area_id, "measurement_binding_changed"
            )
            existing = await self.models.async_get(f"thermal:{binding.area_id}")
        existing_thermal = (
            thermal_model_from_learned(existing) if existing is not None else None
        )
        if existing_thermal is not None and existing_thermal.invalidation_reason:
            existing_thermal = None
        if existing_thermal is not None and existing_thermal.drift_detected:
            observations = tuple(
                item for item in observations
                if item.started_at > existing_thermal.updated_at
            )
            if len(observations) < self.policy.usable_model_samples:
                return existing_thermal
        elif existing_thermal is not None:
            later = tuple(
                item for item in observations
                if item.ended_at > existing_thermal.trained_until
            )
            if detect_thermal_drift(
                existing_thermal, thermal_residuals(existing_thermal, later),
                self.policy,
            ):
                drifted = replace(
                    existing_thermal, drift_detected=True,
                    updated_at=(later[-1].ended_at if later else existing_thermal.updated_at),
                    model_version=existing_thermal.model_version + 1,
                )
                stored = await self.models.async_upsert(
                    thermal_model_to_learned(drifted, self.policy)
                )
                if stored is UpsertResult.STORED:
                    return drifted
                return None
        model = train_thermal_model(
            binding, observations, self.policy,
            model_version=(existing.model_version + 1 if existing is not None else 1),
        )
        if model is None:
            return None
        stored = await self.models.async_upsert(
            thermal_model_to_learned(model, self.policy)
        )
        if stored is not UpsertResult.STORED:
            return None
        return model

    async def async_invalidate_thermal_model(
        self, area_id: str, reason: str
    ) -> bool:
        model_id = f"thermal:{area_id}"
        invalidated = await self.models.async_invalidate(model_id, reason)
        self.predictive_house.forget(model_id)
        return invalidated

    async def async_record_thermal_observation(
        self,
        binding: ThermalBinding,
        observation: ThermalObservation,
        *,
        goal_id: str,
        run_id: str,
        user_id: str | None,
    ) -> ThermalModel | None:
        """Persist one compact completed cycle, then boundedly update its model."""
        from .thermal_model import thermal_observation_to_experience

        if self.policy.learning_mode.value == "off":
            return None
        record = thermal_observation_to_experience(
            observation, goal_id=goal_id, run_id=run_id, user_id=user_id
        )
        await self.experiences.async_append(record)
        return await self.async_update_thermal_model(binding)

    async def async_observe_preference_selection(
        self,
        *,
        user_id: str,
        concept: str,
        area_id: str | None,
        entity_id: str,
        observed_at: datetime,
    ) -> LearnedModel | None:
        """Update one contextual clarification statistic deterministically."""
        if self.policy.learning_mode.value == "off" or observed_at.tzinfo is None:
            return None
        normalized_concept = concept.casefold().strip()
        signature = hashlib.sha256(
            f"{user_id}\0{area_id or '*'}\0{normalized_concept}".encode()
        ).hexdigest()[:24]
        model_id = f"preference:{signature}"
        existing = await self.models.async_get(model_id)
        counts: dict[str, int] = {}
        if existing is not None:
            for key, value in existing.parameters.items():
                if key.startswith("count:") and isinstance(value, int):
                    counts[key[6:]] = value
        counts[entity_id] = counts.get(entity_id, 0) + 1
        sample_count = sum(counts.values())
        preferred, support_count = sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )[0]
        support = support_count / sample_count
        inferred = (
            sample_count >= self.policy.preference_min_samples
            and support >= self.policy.preference_min_support
        )
        state = (
            existing.knowledge_state
            if existing is not None
            and existing.knowledge_state is KnowledgeState.CONFIRMED
            else KnowledgeState.INFERRED if inferred else KnowledgeState.OBSERVED
        )
        parameters: dict[str, str | float | int | bool] = {
            **{f"count:{key}": value for key, value in counts.items()},
            "entity_id": (
                str(existing.parameters.get("entity_id"))
                if state is KnowledgeState.CONFIRMED and existing is not None
                else preferred
            ),
            "support_count": support_count,
            "suggestion_status": (
                str(existing.parameters.get("suggestion_status", "new"))
                if existing is not None else "new"
            ),
        }
        model = LearnedModel(
            model_id, LearnedKind.PREFERENCE, normalized_concept,
            {"user_id": user_id, **({"area_id": area_id} if area_id else {})},
            parameters, state, support, sample_count,
            existing.first_observed if existing is not None else observed_at,
            observed_at,
            (*existing.provenance, "clarification_selection")[-100:]
            if existing is not None else ("clarification_selection",),
            (existing.model_version + 1 if existing is not None else 1),
            health=ModelHealth.VALID if inferred else ModelHealth.LOW_CONFIDENCE,
            confirmed_by=existing.confirmed_by if existing is not None else None,
        )
        if await self.models.async_upsert(model) is not UpsertResult.STORED:
            return None
        return model

    async def async_observe_goal_run(self, run: GoalRun) -> None:
        if self.policy.learning_mode.value == "off":
            return
        if run.status not in {
            GoalRunStatus.SUCCESS,
            GoalRunStatus.PARTIAL_FAILURE,
            GoalRunStatus.FAILURE,
        }:
            return
        extracted = extract_goal_run_experiences(run)
        if not extracted:
            return
        if await self.experiences.async_extend(extracted) == 0:
            return
        await self._async_update_habits(run)
        all_records = await self.experiences.async_list()
        await self.models.async_gc_tombstones(
            oldest_retained_evidence_at=(
                min(item.timestamp for item in all_records)
                if all_records else None
            )
        )
        for record in extracted:
            key_records = tuple(
                item for item in all_records
                if item.action.operator_id == record.action.operator_id
                and item.action.target_id == record.action.target_id
                and item.quality is not ExperienceQuality.INVALID
            )
            verified_records = tuple(
                item for item in key_records
                if item.effect.evidence_state in {
                    EffectEvidenceState.VERIFIED_SUCCESS,
                    EffectEvidenceState.VERIFIED_FAILURE,
                }
            )
            outcomes = tuple(
                item.effect.evidence_state is EffectEvidenceState.VERIFIED_SUCCESS
                for item in verified_records
            )
            reliability = train_reliability(
                record.action.operator_id, record.action.target_id, outcomes
            )
            if reliability is not None:
                await self.models.async_upsert(LearnedModel(
                    reliability.model_id, LearnedKind.RELIABILITY,
                    record.action.target_id,
                    {"operator_id": record.action.operator_id},
                    {"success_rate": reliability.success_rate},
                    KnowledgeState.OBSERVED, reliability.confidence,
                    reliability.sample_count, verified_records[0].timestamp,
                    verified_records[-1].timestamp,
                    tuple(item.experience_id for item in verified_records[-100:]),
                    health=(ModelHealth.VALID
                            if reliability.sample_count >= self.policy.usable_model_samples
                            and reliability.confidence
                            >= self.policy.minimum_planning_confidence
                            else ModelHealth.LOW_CONFIDENCE),
                    expires_at=(verified_records[-1].timestamp
                                + self.policy.stale_model_age),
                ))
            timing_records = tuple(
                item for item in key_records
                if item.effect.evidence_state is EffectEvidenceState.VERIFIED_SUCCESS
                and item.effect.latency_seconds is not None
            )
            durations = tuple(
                item.effect.latency_seconds for item in timing_records
                if item.effect.latency_seconds is not None
            )
            timing = train_effect_timing(
                record.action.operator_id, record.action.target_id,
                durations, self.policy,
            )
            if timing is None:
                continue
            await self.models.async_upsert(LearnedModel(
                timing.model_id, LearnedKind.EFFECT_TIMING,
                record.action.target_id,
                {"operator_id": record.action.operator_id},
                {"median_seconds": timing.median_seconds,
                 "p90_seconds": timing.p90_seconds,
                 "p95_seconds": timing.p95_seconds,
                 "mad_seconds": timing.mad_seconds},
                KnowledgeState.OBSERVED, timing.confidence,
                timing.sample_count, timing_records[0].timestamp,
                timing_records[-1].timestamp,
                tuple(item.experience_id for item in timing_records[-100:]),
                health=(ModelHealth.VALID
                        if timing.sample_count >= self.policy.usable_model_samples
                        else ModelHealth.LOW_CONFIDENCE),
                expires_at=(timing_records[-1].timestamp
                            + self.policy.stale_model_age),
            ))

    async def _async_update_habits(self, run: GoalRun) -> None:
        """Increment bounded abstract sequences; never create a routine or plan."""
        if (
            not self.policy.habit_discovery_enabled
            or run.user_id is None
            or run.status is not GoalRunStatus.SUCCESS
        ):
            return
        sequence = tuple(
            f"{step.operator_id}@{verification.entity_id}={verification.expected}"
            for step in run.steps
            if step.operator_id is not None and step.service_accepted is True
            for verification in step.verification
            if verification.success
        )
        if len(sequence) < 2:
            return
        try:
            observed_at = datetime.fromisoformat(run.updated_at)
        except ValueError:
            return
        if observed_at.tzinfo is None:
            return
        time_band = _time_band(observed_at.hour)
        existing = tuple(
            model for model in await self.models.async_list(kind=LearnedKind.HABIT)
            if model.subject == run.user_id
            and model.context.get("time_band") == time_band
        )
        evidence = f"goal_run:{run.run_id}"
        if any(evidence in model.provenance for model in existing):
            return
        signature = hashlib.sha256(
            repr((run.user_id, time_band, sequence)).encode()
        ).hexdigest()[:24]
        sequence_family = hashlib.sha256(
            repr(tuple(item.partition("@")[0] for item in sequence)).encode()
        ).hexdigest()[:16]
        model_id = f"habit:{signature}"
        sequence_text = "|".join(sequence)
        found = False
        for model in existing:
            if model.context.get("sequence_family") != sequence_family:
                continue
            matches = model.model_id == model_id
            found = found or matches
            samples = model.sample_count + int(matches)
            opportunities = int(model.parameters.get("opportunity_count", 0)) + 1
            support = samples / opportunities
            valid = (
                samples >= self.policy.habit_min_occurrences
                and support >= self.policy.habit_min_support
            )
            await self.models.async_upsert(replace(
                model,
                sample_count=samples,
                last_observed=observed_at if matches else model.last_observed,
                provenance=(
                    (*model.provenance, evidence)[-100:]
                    if matches else model.provenance
                ),
                confidence=min(1.0, support),
                parameters={
                    **model.parameters,
                    "opportunity_count": opportunities,
                    "support": support,
                },
                health=ModelHealth.VALID if valid else ModelHealth.LOW_CONFIDENCE,
                model_version=model.model_version + 1,
            ))
        if found:
            return
        opportunities = max(
            (int(model.parameters.get("opportunity_count", 0)) for model in existing
             if model.context.get("sequence_family") == sequence_family),
            default=0,
        ) + 1
        support = 1.0 / opportunities
        status = (
            SuggestionStatus.NEW if self.policy.suggestions_enabled
            else SuggestionStatus.SNOOZED
        )
        await self.models.async_upsert(LearnedModel(
            model_id, LearnedKind.HABIT, run.user_id,
            {"time_band": time_band, "weekday": observed_at.weekday(),
             "sequence_family": sequence_family},
            {
                "sequence": sequence_text,
                "opportunity_count": opportunities,
                "support": support,
                "suggestion_status": status.value,
                "creates_automation": False,
            },
            KnowledgeState.INFERRED, support, 1, observed_at, observed_at,
            (evidence,), health=ModelHealth.LOW_CONFIDENCE,
        ))


__all__ = ("LearningManager",)


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _time_band(hour: int) -> str:
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "day"
    if 17 <= hour < 22:
        return "evening"
    return "night"
