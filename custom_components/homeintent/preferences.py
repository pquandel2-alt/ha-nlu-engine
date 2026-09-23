"""Context-scoped preference candidates; confirmation remains authoritative."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from enum import StrEnum

from .learning_policy import KnowledgeState, LearningPolicy


@dataclass(frozen=True)
class PreferenceContext:
    user_id: str
    concept: str
    area_id: str | None = None
    floor_id: str | None = None
    routine_id: str | None = None
    time_band: str | None = None
    presence_set: tuple[str, ...] = ()


@dataclass(frozen=True)
class LearnedPreference:
    preference_id: str
    context: PreferenceContext
    preferred_value: str
    knowledge_state: KnowledgeState
    confidence: float
    sample_count: int
    support_count: int
    confirmed_by: str | None = None


class ConflictResolution(StrEnum):
    SHARED_PROFILE = "shared_profile"
    OWNER_PRIORITY = "owner_priority"
    MANUAL_CLARIFICATION = "manual_clarification"


@dataclass(frozen=True)
class PreferenceResolution:
    value: str | None
    requires_clarification: bool
    source_preference_ids: tuple[str, ...]


def infer_preference(
    context: PreferenceContext,
    selections: tuple[str, ...],
    policy: LearningPolicy,
) -> LearnedPreference | None:
    if len(selections) < policy.preference_min_samples:
        return None
    counts = Counter(selections)
    preferred, support = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    ratio = support / len(selections)
    if ratio < policy.preference_min_support:
        return None
    signature = repr((context, preferred)).encode()
    return LearnedPreference(
        "preference:" + hashlib.sha256(signature).hexdigest()[:24],
        context, preferred, KnowledgeState.INFERRED, ratio, len(selections), support,
    )


def confirm_preference(
    preference: LearnedPreference, *, confirmed_by: str
) -> LearnedPreference:
    if not confirmed_by:
        raise ValueError("confirmation requires an actor")
    return replace(
        preference, knowledge_state=KnowledgeState.CONFIRMED,
        confirmed_by=confirmed_by,
    )


def resolve_preferences(
    preferences: tuple[LearnedPreference, ...],
    *,
    present_user_ids: tuple[str, ...],
    shared_preference: LearnedPreference | None = None,
    conflict_policy: ConflictResolution = ConflictResolution.MANUAL_CLARIFICATION,
    owner_user_id: str | None = None,
) -> PreferenceResolution:
    confirmed = tuple(
        item for item in preferences
        if item.knowledge_state is KnowledgeState.CONFIRMED
        and item.context.user_id in present_user_ids
    )
    if len(present_user_ids) > 1 and shared_preference is not None:
        if shared_preference.knowledge_state is KnowledgeState.CONFIRMED:
            return PreferenceResolution(
                shared_preference.preferred_value, False,
                (shared_preference.preference_id,),
            )
    if len(confirmed) == 1 and len(present_user_ids) == 1:
        return PreferenceResolution(confirmed[0].preferred_value, False,
                                    (confirmed[0].preference_id,))
    values = {item.preferred_value for item in confirmed}
    if len(values) == 1 and confirmed:
        return PreferenceResolution(next(iter(values)), False,
                                    tuple(item.preference_id for item in confirmed))
    if conflict_policy is ConflictResolution.OWNER_PRIORITY and owner_user_id:
        owner = tuple(item for item in confirmed if item.context.user_id == owner_user_id)
        if len(owner) == 1:
            return PreferenceResolution(owner[0].preferred_value, False,
                                        (owner[0].preference_id,))
    return PreferenceResolution(None, True,
                                tuple(item.preference_id for item in confirmed))


__all__ = (
    "ConflictResolution", "LearnedPreference", "PreferenceContext",
    "PreferenceResolution", "confirm_preference", "infer_preference",
    "resolve_preferences",
)
