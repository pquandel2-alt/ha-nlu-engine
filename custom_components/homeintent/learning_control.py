"""Shared, closed V11 knowledge mutations used by Voice and the Learning Center.

Every function here delegates to the existing authorities (``ModelRegistry``,
``PredictiveHouseModel``, ``routine_from_habit_model``) and adds nothing but
ownership and state validation.  ``conversation.py`` and the Learning Center
WebSocket API call these same functions, so a preference confirmed by voice is
indistinguishable from one confirmed in the panel and vice versa.

No function in this module issues a Home Assistant service call.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import Mapping, Sequence

from .alias_learning import remove_alias_rule
from .habit_discovery import routine_from_habit_model
from .learning_policy import KnowledgeState
from .model_registry import (
    LearnedKind,
    LearnedModel,
    ModelRegistry,
    SuppressionKind,
    UpsertResult,
)
from .predictive_house_model import PredictiveHouseModel
from .profiles import RoutineDefinition


class ControlErrorCode(StrEnum):
    """Machine-stable reasons a knowledge mutation was refused."""

    NOT_FOUND = "not_found"
    WRONG_OWNER = "wrong_owner"
    INVALID_STATE = "invalid_state"
    UNSUPPORTED_OPERATION = "unsupported_operation"


class LearningControlError(Exception):
    """A refused mutation; nothing was changed."""

    def __init__(self, code: ControlErrorCode, message: str = "") -> None:
        super().__init__(message or code.value)
        self.code = code


def model_owner(model: LearnedModel) -> str | None:
    """Owner of PERSONAL knowledge, or ``None`` for household/system models.

    Ownership is read only from the authoritative stored scope, never from
    names: a preference is scoped by ``context.user_id``, a habit by its
    ``subject`` (the GoalRun user id that produced it).
    """
    if model.kind is LearnedKind.PREFERENCE:
        owner = model.context.get("user_id")
        return owner if isinstance(owner, str) and owner else None
    if model.kind is LearnedKind.HABIT:
        return model.subject or None
    return None


def preference_confirmable(model: LearnedModel) -> bool:
    return (
        model.kind is LearnedKind.PREFERENCE
        and model.knowledge_state is KnowledgeState.INFERRED
        and model.invalidation_reason is None
    )


def habit_decidable(model: LearnedModel) -> bool:
    status = model.parameters.get("suggestion_status")
    return (
        model.kind is LearnedKind.HABIT
        and model.knowledge_state is KnowledgeState.INFERRED
        and status not in {"accepted", "rejected"}
    )


async def _owned(
    registry: ModelRegistry, model_id: str, actor_id: str, kind: LearnedKind
) -> LearnedModel:
    model = await registry.async_get(model_id)
    if model is None:
        raise LearningControlError(ControlErrorCode.NOT_FOUND)
    if model.kind is not kind:
        raise LearningControlError(ControlErrorCode.UNSUPPORTED_OPERATION)
    if model_owner(model) != actor_id:
        # Confirmation is the owner's authority; an administrator can
        # forget, but never confirm or accept on somebody's behalf.
        raise LearningControlError(ControlErrorCode.WRONG_OWNER)
    return model


async def async_confirm_preference(
    registry: ModelRegistry, model_id: str, actor_id: str
) -> LearnedModel:
    """Promote one INFERRED preference to CONFIRMED in exactly its scope."""
    model = await _owned(registry, model_id, actor_id, LearnedKind.PREFERENCE)
    if not preference_confirmable(model):
        raise LearningControlError(ControlErrorCode.INVALID_STATE)
    confirmed = replace(
        model, knowledge_state=KnowledgeState.CONFIRMED,
        parameters={**model.parameters, "suggestion_status": "accepted"},
        model_version=model.model_version + 1,
        confirmed_by=actor_id,
    )
    if await registry.async_upsert(confirmed) is not UpsertResult.STORED:
        raise LearningControlError(ControlErrorCode.NOT_FOUND)
    return confirmed


async def async_reject_preference(
    registry: ModelRegistry, model_id: str, actor_id: str
) -> LearnedModel:
    """Keep the observation non-binding; it is no longer offered."""
    model = await _owned(registry, model_id, actor_id, LearnedKind.PREFERENCE)
    if model.knowledge_state is KnowledgeState.CONFIRMED:
        raise LearningControlError(ControlErrorCode.INVALID_STATE)
    rejected = replace(
        model,
        parameters={**model.parameters, "suggestion_status": "rejected"},
        model_version=model.model_version + 1,
    )
    if await registry.async_upsert(rejected) is not UpsertResult.STORED:
        raise LearningControlError(ControlErrorCode.NOT_FOUND)
    return rejected


async def async_accept_habit(
    registry: ModelRegistry, model_id: str, actor_id: str
) -> RoutineDefinition:
    """Mark a habit accepted and return its *unconfirmed* V10 routine draft.

    The draft is never executed here; it still has to be stored through the
    normal confirmation-bound ``ProfileStore.async_save_routine`` path.
    """
    model = await _owned(registry, model_id, actor_id, LearnedKind.HABIT)
    if not habit_decidable(model):
        raise LearningControlError(ControlErrorCode.INVALID_STATE)
    routine = routine_from_habit_model(model, actor_id)
    if routine is None:
        raise LearningControlError(ControlErrorCode.UNSUPPORTED_OPERATION)
    await registry.async_upsert(replace(
        model,
        parameters={**model.parameters, "suggestion_status": "accepted"},
        model_version=model.model_version + 1,
    ))
    return routine


async def async_reject_habit(
    registry: ModelRegistry, model_id: str, actor_id: str
) -> LearnedModel:
    """Durable REJECTED_HABIT suppression of this exact pattern."""
    model = await _owned(registry, model_id, actor_id, LearnedKind.HABIT)
    await registry.async_delete_with_reason(
        model.model_id, reason="user_rejected_habit",
        suppression_kind=SuppressionKind.REJECTED_HABIT,
    )
    return model


async def async_forget_model(
    registry: ModelRegistry,
    predictive: PredictiveHouseModel | None,
    model_id: str,
) -> LearnedModel | None:
    """Ordinary FORGET: remove the model and tombstone it against old evidence.

    Returns the forgotten model (``None`` when it was already gone; a
    tombstone is still written, matching the historical voice behaviour).
    """
    model = await registry.async_get(model_id)
    await registry.async_delete(model_id, suppress=True)
    if predictive is not None:
        predictive.forget(model_id)
    return model


async def async_reset_models(
    registry: ModelRegistry, predictive: PredictiveHouseModel | None
) -> tuple[int, tuple[LearnedModel, ...]]:
    """Reset only V11 learned models; permissions, mutes and history stay."""
    before = await registry.async_list()
    deleted = await registry.async_reset()
    if predictive is not None:
        predictive.clear()
    return deleted, before


def options_without_preference_aliases(
    options: Mapping[str, object], models: Sequence[LearnedModel], alias_key: str
) -> dict[str, object] | None:
    """Options with the global aliases of forgotten preferences removed.

    Returns ``None`` when nothing changes.  Only a global (area-less)
    preference ever installed a global alias rule, so only those are removed.
    """
    current = options.get(alias_key)
    aliases: object = current
    for model in models:
        entity_id = model.parameters.get("entity_id")
        if (
            model.kind is LearnedKind.PREFERENCE
            and model.context.get("area_id") is None
            and isinstance(entity_id, str)
        ):
            aliases = remove_alias_rule(aliases, alias=model.subject, entity_id=entity_id)
    if aliases == current:
        return None
    return {**options, alias_key: aliases}


__all__ = (
    "ControlErrorCode",
    "LearningControlError",
    "async_accept_habit",
    "async_confirm_preference",
    "async_forget_model",
    "async_reject_habit",
    "async_reject_preference",
    "async_reset_models",
    "habit_decidable",
    "model_owner",
    "options_without_preference_aliases",
    "preference_confirmable",
)
