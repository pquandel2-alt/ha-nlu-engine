"""Typed payloads for confirmation-bound V11 learning dialogs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LearningDialogOperation(StrEnum):
    DELETE_MODEL = "delete_model"
    RESET_MODELS = "reset_models"
    CONFIRM_PREFERENCE = "confirm_preference"
    RESOLVE_CONFLICT = "resolve_conflict"
    ACCEPT_HABIT = "accept_habit"
    REJECT_HABIT = "reject_habit"


@dataclass(frozen=True)
class LearningDialogPayload:
    operation: LearningDialogOperation
    model_id: str | None = None
    preference_id: str | None = None
    habit_id: str | None = None
    requested_by_user_id: str | None = None


__all__ = ("LearningDialogOperation", "LearningDialogPayload")
