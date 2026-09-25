"""Central typed registry for every V11 statistical model and learned item."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Sequence, cast

from .learning_policy import KnowledgeState, LearningPolicy


SCHEMA_VERSION = 2


class LearnedKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    THERMAL_MODEL = "thermal_model"
    EFFECT_TIMING = "effect_timing"
    RELIABILITY = "reliability"
    HABIT = "habit"
    DURATION = "duration"
    ENERGY = "energy"
    BATTERY_TREND = "battery_trend"


class ModelHealth(StrEnum):
    VALID = "valid"
    LOW_CONFIDENCE = "low_confidence"
    UNRELIABLE = "unreliable"
    STALE = "stale"
    DRIFT_DETECTED = "drift_detected"
    INVALID = "invalid"


class UpsertResult(StrEnum):
    """Authoritative outcome of attempting to store learned knowledge."""

    STORED = "stored"
    SUPPRESSED = "suppressed"
    REJECTED = "rejected"


class SuppressionKind(StrEnum):
    FORGET = "forget"
    REJECTED_HABIT = "rejected_habit"


@dataclass(frozen=True)
class TombstoneRecord:
    model_id: str
    deleted_at: datetime
    reason: str
    source_cutoff: datetime
    suppression_kind: SuppressionKind = SuppressionKind.FORGET

    @property
    def durable(self) -> bool:
        return self.suppression_kind is SuppressionKind.REJECTED_HABIT

    def to_dict(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "deleted_at": self.deleted_at.isoformat(),
            "reason": self.reason,
            "source_cutoff": self.source_cutoff.isoformat(),
            "suppression_kind": self.suppression_kind.value,
        }


ModelValue = str | float | int | bool


def _empty_metrics() -> Mapping[str, float]:
    return {}


@dataclass(frozen=True)
class LearnedModel:
    model_id: str
    kind: LearnedKind
    subject: str
    context: Mapping[str, ModelValue]
    parameters: Mapping[str, ModelValue]
    knowledge_state: KnowledgeState
    confidence: float
    sample_count: int
    first_observed: datetime
    last_observed: datetime
    provenance: tuple[str, ...]
    model_version: int = 1
    validation_metrics: Mapping[str, float] = field(default_factory=_empty_metrics)
    health: ModelHealth = ModelHealth.LOW_CONFIDENCE
    expires_at: datetime | None = None
    confirmed_by: str | None = None
    invalidation_reason: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        for value in (self.first_observed, self.last_observed, self.expires_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("model timestamps must be timezone-aware")

    @property
    def usable(self) -> bool:
        return self.health is ModelHealth.VALID and self.invalidation_reason is None

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id, "kind": self.kind.value,
            "subject": self.subject, "context": dict(self.context),
            "parameters": dict(self.parameters),
            "knowledge_state": self.knowledge_state.value,
            "confidence": self.confidence, "sample_count": self.sample_count,
            "first_observed": self.first_observed.isoformat(),
            "last_observed": self.last_observed.isoformat(),
            "provenance": list(self.provenance), "model_version": self.model_version,
            "validation_metrics": dict(self.validation_metrics),
            "health": self.health.value,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "confirmed_by": self.confirmed_by,
            "invalidation_reason": self.invalidation_reason,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "LearnedModel":
        return cls(
            str(raw["model_id"]), LearnedKind(str(raw["kind"])), str(raw["subject"]),
            _values(raw.get("context")), _values(raw.get("parameters")),
            KnowledgeState(str(raw.get("knowledge_state", "observed"))),
            _number(raw.get("confidence")), _integer(raw.get("sample_count")),
            _datetime(raw["first_observed"]), _datetime(raw["last_observed"]),
            _strings(raw.get("provenance")), _integer(raw.get("model_version"), 1),
            _floats(raw.get("validation_metrics")),
            ModelHealth(str(raw.get("health", "low_confidence"))),
            _optional_datetime(raw.get("expires_at")), _text(raw.get("confirmed_by")),
            _text(raw.get("invalidation_reason")),
        )


class ModelRegistry:
    def __init__(self, path: str | Path, policy: LearningPolicy) -> None:
        self.path = Path(path)
        self.policy = policy
        self._lock = asyncio.Lock()
        self._cache: tuple[list[LearnedModel], dict[str, TombstoneRecord]] | None = None
        self._activate: Callable[[LearnedModel], None] | None = None
        self._deactivate: Callable[[str], None] | None = None
        self._change_listeners: list[Callable[[], None]] = []

    def bind_active_view(
        self,
        activate: Callable[[LearnedModel], None],
        deactivate: Callable[[str], None],
    ) -> None:
        """Bind the sole in-memory view governed by registry decisions."""
        self._activate = activate
        self._deactivate = deactivate

    def add_change_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Notify after every persisted write; the callback gets no content."""
        self._change_listeners.append(listener)

        def _remove() -> None:
            if listener in self._change_listeners:
                self._change_listeners.remove(listener)

        return _remove

    def _notify_changed(self) -> None:
        for listener in tuple(self._change_listeners):
            listener()

    async def async_list_tombstones(self) -> tuple[TombstoneRecord, ...]:
        """Read-only copy of the persisted suppression records."""
        async with self._lock:
            _models, tombstones = await self._load_unlocked()
        return tuple(tombstones[key] for key in sorted(tombstones))

    async def async_upsert(self, model: LearnedModel) -> UpsertResult:
        """Store one model and report whether it may become active."""
        return (await self.async_upsert_many((model,)))[0]

    async def async_upsert_many(
        self, incoming: Sequence[LearnedModel]
    ) -> tuple[UpsertResult, ...]:
        """Atomically update a bounded batch without feature-specific files."""
        async with self._lock:
            models, tombstones = await self._load_unlocked()
            previous_ids = {item.model_id for item in models}
            indexed = {item.model_id: item for item in models}
            for model in incoming:
                if model.model_id not in tombstones:
                    indexed[model.model_id] = model
            bounded = sorted(
                indexed.values(), key=lambda item: (item.last_observed, item.model_id)
            )[-max(1, self.policy.model_limit):]
            await asyncio.to_thread(self._write, bounded, tombstones)
            self._cache = (list(bounded), dict(tombstones))
            self._notify_changed()
            stored_ids = {item.model_id for item in bounded}
            results = tuple(
                UpsertResult.SUPPRESSED
                if model.model_id in tombstones
                else UpsertResult.STORED
                if model.model_id in stored_ids
                else UpsertResult.REJECTED
                for model in incoming
            )
            if self._deactivate is not None:
                for model_id in previous_ids - stored_ids:
                    self._deactivate(model_id)
                for model, result in zip(incoming, results, strict=True):
                    if result is not UpsertResult.STORED:
                        self._deactivate(model.model_id)
            if self._activate is not None:
                for model, result in zip(incoming, results, strict=True):
                    if result is UpsertResult.STORED:
                        self._activate(model)
            return results

    async def async_is_suppressed(self, model_id: str) -> bool:
        """Return the persisted tombstone decision for a model identifier."""
        async with self._lock:
            _models, tombstones = await self._load_unlocked()
            return model_id in tombstones

    async def async_restore_active_view(self) -> int:
        """Restore accepted models while serializing against delete/upsert."""
        async with self._lock:
            models, tombstones = await self._load_unlocked()
            active = tuple(
                model for model in models if model.model_id not in tombstones
            )
            if self._activate is not None:
                for model in active:
                    self._activate(model)
            return len(active)

    async def async_get(self, model_id: str) -> LearnedModel | None:
        async with self._lock:
            models, tombstones = await self._load_unlocked()
        if model_id in tombstones:
            return None
        return next((item for item in models if item.model_id == model_id), None)

    async def async_list(
        self, *, kind: LearnedKind | None = None, subject: str | None = None
    ) -> tuple[LearnedModel, ...]:
        async with self._lock:
            models, tombstones = await self._load_unlocked()
        return tuple(
            item for item in models
            if item.model_id not in tombstones
            and (kind is None or item.kind is kind)
            and (subject is None or item.subject == subject)
        )

    async def async_delete(self, model_id: str, *, suppress: bool = True) -> bool:
        return await self.async_delete_with_reason(model_id, suppress=suppress)

    async def async_delete_with_reason(
        self, model_id: str, *, suppress: bool = True,
        reason: str = "user_forget",
        suppression_kind: SuppressionKind = SuppressionKind.FORGET,
        deleted_at: datetime | None = None,
    ) -> bool:
        async with self._lock:
            models, tombstones = await self._load_unlocked()
            retained = [item for item in models if item.model_id != model_id]
            existed = len(retained) != len(models)
            if suppress:
                current = deleted_at or datetime.now(timezone.utc)
                if current.tzinfo is None:
                    raise ValueError("tombstone timestamp must be timezone-aware")
                tombstones[model_id] = TombstoneRecord(
                    model_id, current, reason, current, suppression_kind
                )
            await asyncio.to_thread(self._write, retained, tombstones)
            self._cache = (list(retained), dict(tombstones))
            self._notify_changed()
            if self._deactivate is not None:
                self._deactivate(model_id)
            return existed

    async def async_reset(self) -> int:
        async with self._lock:
            models, tombstones = await self._load_unlocked()
            current = datetime.now(timezone.utc)
            tombstones.update({
                item.model_id: TombstoneRecord(
                    item.model_id, current, "user_reset", current
                )
                for item in models
            })
            await asyncio.to_thread(self._write, (), tombstones)
            self._cache = ([], dict(tombstones))
            self._notify_changed()
            if self._deactivate is not None:
                for model in models:
                    self._deactivate(model.model_id)
            return len(models)

    async def async_gc_tombstones(
        self, *, oldest_retained_evidence_at: datetime | None
    ) -> int:
        """Drop ordinary tombstones only after pre-deletion evidence is gone."""
        if (
            oldest_retained_evidence_at is not None
            and oldest_retained_evidence_at.tzinfo is None
        ):
            raise ValueError("evidence timestamp must be timezone-aware")
        async with self._lock:
            models, tombstones = await self._load_unlocked()
            removable = tuple(
                model_id for model_id, tombstone in tombstones.items()
                if not tombstone.durable
                and (
                    oldest_retained_evidence_at is None
                    or oldest_retained_evidence_at > tombstone.source_cutoff
                )
            )
            for model_id in removable:
                del tombstones[model_id]
            if removable:
                await asyncio.to_thread(self._write, models, tombstones)
                self._cache = (list(models), dict(tombstones))
                self._notify_changed()
            return len(removable)

    async def async_invalidate(self, model_id: str, reason: str) -> bool:
        model = await self.async_get(model_id)
        if model is None:
            return False
        await self.async_upsert(replace(
            model, health=ModelHealth.INVALID, invalidation_reason=reason,
            model_version=model.model_version + 1,
        ))
        return True

    async def async_redacted_summary(self) -> dict[str, object]:
        models = await self.async_list()
        by_kind: dict[str, int] = {}
        by_health: dict[str, int] = {}
        for model in models:
            by_kind[model.kind.value] = by_kind.get(model.kind.value, 0) + 1
            by_health[model.health.value] = by_health.get(model.health.value, 0) + 1
        return {"schema_version": SCHEMA_VERSION, "model_count": len(models),
                "kind_counts": by_kind, "health_counts": by_health,
                "personal_values_included": False, "provenance_included": False}

    async def _load_unlocked(self) -> tuple[list[LearnedModel], dict[str, TombstoneRecord]]:
        if self._cache is None:
            models, tombstones = await asyncio.to_thread(self._read)
            self._cache = (models, tombstones)
        return list(self._cache[0]), dict(self._cache[1])

    def _read(self) -> tuple[list[LearnedModel], dict[str, TombstoneRecord]]:
        try:
            raw: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return [], {}
        if not isinstance(raw, Mapping):
            return [], {}
        document = cast(Mapping[str, object], raw)
        schema = document.get("schema_version")
        if schema not in {1, SCHEMA_VERSION}:
            return [], {}
        raw_models = document.get("models", ())
        models: list[LearnedModel] = []
        if isinstance(raw_models, list):
            for item in cast(list[object], raw_models):
                if not isinstance(item, Mapping):
                    continue
                try:
                    models.append(LearnedModel.from_dict(cast(Mapping[str, object], item)))
                except (KeyError, TypeError, ValueError):
                    continue
        tombstones: dict[str, TombstoneRecord] = {}
        raw_tombstones = document.get("tombstones", ())
        if schema == 1:
            # Old string tombstones remain conservatively durable. Their
            # deletion/source chronology was never recorded, so safe GC
            # cannot be proven.
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            for model_id in _strings(raw_tombstones):
                tombstones[model_id] = TombstoneRecord(
                    model_id, epoch, "legacy_unknown", epoch,
                    SuppressionKind.REJECTED_HABIT,
                )
        elif isinstance(raw_tombstones, list):
            for raw_tombstone in cast(list[object], raw_tombstones):
                if not isinstance(raw_tombstone, Mapping):
                    continue
                item = cast(Mapping[str, object], raw_tombstone)
                try:
                    record = TombstoneRecord(
                        str(item["model_id"]), _datetime(item["deleted_at"]),
                        str(item.get("reason", "user_forget")),
                        _datetime(item["source_cutoff"]),
                        SuppressionKind(str(item.get(
                            "suppression_kind", SuppressionKind.FORGET.value
                        ))),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                tombstones[record.model_id] = record
        return models, tombstones

    def _write(
        self, models: Sequence[LearnedModel],
        tombstones: Mapping[str, TombstoneRecord],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".homeintent_models_", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"schema_version": SCHEMA_VERSION,
                           "models": [item.to_dict() for item in models],
                           "tombstones": [tombstones[key].to_dict()
                                          for key in sorted(tombstones)]}, handle,
                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


def _datetime(value: object) -> datetime:
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return result


def _optional_datetime(value: object) -> datetime | None:
    return _datetime(value) if isinstance(value, str) and value else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _strings(value: object) -> tuple[str, ...]:
    return tuple(item for item in cast(list[object], value) if isinstance(item, str)) if isinstance(value, list) else ()


def _values(value: object) -> dict[str, ModelValue]:
    if not isinstance(value, Mapping):
        return {}
    items = cast(Mapping[object, object], value)
    return {str(key): item for key, item in items.items()
            if isinstance(key, str) and isinstance(item, (str, float, int, bool))}


def _floats(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    items = cast(Mapping[object, object], value)
    return {str(key): float(item) for key, item in items.items()
            if isinstance(key, str) and isinstance(item, (float, int))}


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (float, int)) else default


def _integer(value: object, default: int = 0) -> int:
    return int(value) if isinstance(value, (float, int)) else default


# One central store serves both learned knowledge and model metadata.  The
# semantic alias makes that consolidation explicit without a second store.
LearnedKnowledgeStore = ModelRegistry


def explain_learned_model(model: LearnedModel) -> str:
    """Render bounded provenance metadata without raw personal evidence."""
    metrics = ", ".join(
        f"{key}={value:.2f}" for key, value in sorted(model.validation_metrics.items())
    )
    detail = f", Validierung {metrics}" if metrics else ""
    return (
        f"Modell {model.model_id}, Version {model.model_version}: "
        f"{model.sample_count} lokale Belege vom {model.first_observed.date()} bis "
        f"{model.last_observed.date()}, Konfidenz {model.confidence:.2f}{detail}. "
        "Die Statistik ist keine Berechtigung und umgeht keine Ausführungsrichtlinie."
    )


__all__ = (
    "LearnedKind", "LearnedKnowledgeStore", "LearnedModel", "ModelHealth",
    "ModelRegistry", "ModelValue", "SuppressionKind", "TombstoneRecord",
    "UpsertResult", "explain_learned_model",
)
