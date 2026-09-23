"""Typed future estimates, deliberately separate from the current WorldModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar


class PredictionStatus(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    LOW_CONFIDENCE = "low_confidence"
    STALE_MODEL = "stale_model"
    INCOMPATIBLE_CONTEXT = "incompatible_context"
    MODEL_UNRELIABLE = "model_unreliable"
    MODEL_INVALID = "model_invalid"
    DRIFT_DETECTED = "drift_detected"


T = TypeVar("T", float, int, str, bool)


@dataclass(frozen=True)
class PredictionResult(Generic[T]):
    status: PredictionStatus
    value: T | None
    uncertainty: tuple[T, T] | None
    confidence: float
    model_id: str | None
    model_version: int | None
    sample_count: int
    based_on: datetime
    valid_until: datetime | None
    training_range: tuple[datetime, datetime] | None
    input_features: tuple[str, ...]
    explanation: str

    @property
    def usable_for_planning(self) -> bool:
        return self.status is PredictionStatus.OK and self.value is not None


__all__ = ("PredictionResult", "PredictionStatus")
