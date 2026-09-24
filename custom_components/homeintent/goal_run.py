"""Bounded local GoalRun history and fact-grounded failure explanations."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Awaitable, Callable, Mapping, Sequence, cast

from .goal_model import GoalModel
from .goal_model import GoalKind


class GoalRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SCHEDULED = "scheduled"
    PARTIAL_FAILURE = "partial_failure"
    FAILURE = "failure"
    POLICY_BLOCKED = "policy_blocked"
    CANCELLED = "cancelled"


class FailureCode(StrEnum):
    TRIGGER_NOT_OBSERVED = "trigger_not_observed"
    CONDITION_FALSE = "condition_false"
    USER_PERSON_BINDING_MISSING = "user_person_binding_missing"
    NOTIFICATION_TARGET_MISSING = "notification_target_missing"
    NOTIFICATION_TARGET_AMBIGUOUS = "notification_target_ambiguous"
    TARGET_UNAVAILABLE = "target_unavailable"
    SERVICE_ERROR = "service_error"
    POLICY_BLOCKED = "policy_blocked"
    CONFIRMATION_MISSING = "confirmation_missing"
    EFFECT_TIMEOUT = "effect_timeout"
    WRONG_STATE = "wrong_state"
    AUTOMATION_DISABLED = "automation_disabled"
    HOME_ASSISTANT_UNAVAILABLE = "home_assistant_unavailable"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CausalityLevel(StrEnum):
    DIRECTLY_OBSERVED = "directly_observed"
    DERIVED_FROM_TRACE = "derived_from_trace"
    POSSIBLE_BUT_UNPROVEN = "possible_but_unproven"


@dataclass(frozen=True)
class VerificationRecord:
    entity_id: str
    expected: str
    observed: str | None
    success: bool
    failure_code: FailureCode | None = None
    observed_at: str | None = None


@dataclass(frozen=True)
class StepExecutionRecord:
    step_id: str
    operator_id: str | None
    selected_targets: tuple[str, ...]
    preconditions: tuple[str, ...]
    service_accepted: bool | None
    verification: tuple[VerificationRecord, ...] = ()
    failure_code: FailureCode | None = None
    message: str = ""
    executed_at: str | None = None


@dataclass(frozen=True)
class NotificationRecord:
    recipient_person_id: str
    target_id: str
    channel: str
    severity: str
    delivered: bool
    dedupe_key: str
    category: str


@dataclass(frozen=True)
class GoalRun:
    run_id: str
    goal_id: str
    created_at: str
    updated_at: str
    source_utterance: str
    user_id: str | None
    person_entity_id: str | None
    goal: GoalModel
    plan_id: str | None
    selected_targets: tuple[str, ...]
    preconditions: tuple[str, ...]
    confirmed: bool
    steps: tuple[StepExecutionRecord, ...]
    notifications: tuple[NotificationRecord, ...]
    status: GoalRunStatus
    failures: tuple[FailureCode, ...] = ()
    evidence: tuple[str, ...] = ()
    idempotency_key: str | None = None

    @classmethod
    def start(
        cls,
        goal: GoalModel,
        *,
        user_id: str | None,
        person_entity_id: str | None,
        plan_id: str | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> "GoalRun":
        current = (now or datetime.now(timezone.utc)).isoformat()
        return cls(
            f"run_{uuid.uuid4().hex}", goal.goal_id, current, current,
            goal.provenance.source_utterance, user_id, person_entity_id, goal,
            plan_id, (), (), False, (), (), GoalRunStatus.RUNNING,
            idempotency_key=idempotency_key,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_utterance": self.source_utterance,
            "user_id": self.user_id,
            "person_entity_id": self.person_entity_id,
            "goal": self.goal.to_dict(),
            "plan_id": self.plan_id,
            "selected_targets": list(self.selected_targets),
            "preconditions": list(self.preconditions),
            "confirmed": self.confirmed,
            "steps": [_step_dict(item) for item in self.steps],
            "notifications": [_notification_dict(item) for item in self.notifications],
            "status": self.status.value,
            "failures": [item.value for item in self.failures],
            "evidence": list(self.evidence),
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "GoalRun":
        return cls(
            str(raw["run_id"]), str(raw.get("goal_id", "")),
            str(raw["created_at"]), str(raw.get("updated_at", raw["created_at"])),
            str(raw.get("source_utterance", "")), _text(raw.get("user_id")),
            _text(raw.get("person_entity_id")),
            GoalModel.from_dict(cast(Mapping[str, object], raw["goal"])),
            _text(raw.get("plan_id")), _strings(raw.get("selected_targets")),
            _strings(raw.get("preconditions")), bool(raw.get("confirmed", False)),
            tuple(_step_from(item) for item in _mapping_sequence(raw.get("steps", ()))),
            tuple(_notification_from(item) for item in _mapping_sequence(raw.get("notifications", ()))),
            GoalRunStatus(str(raw.get("status", "failure"))),
            tuple(FailureCode(str(item)) for item in _strings(raw.get("failures"))),
            _strings(raw.get("evidence")), _text(raw.get("idempotency_key")),
        )


@dataclass(frozen=True)
class GoalRunQuery:
    """Typed, composable selection over the bounded GoalRun history."""

    user_id: str | None = None
    person_entity_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    failed_only: bool = False
    goal_kind: GoalKind | None = None
    routine_id: str | None = None
    goal_id: str | None = None
    run_id: str | None = None
    entity_id: str | None = None
    status: GoalRunStatus | None = None


@dataclass(frozen=True)
class GoalRunClarification:
    run_ids: tuple[str, ...]
    labels: tuple[str, ...]
    requested_by_user_id: str | None


class GoalRunStore:
    def __init__(self, path: str | Path, *, limit: int = 100) -> None:
        self.path = Path(path)
        self.limit = max(1, min(limit, 1000))
        self._lock = asyncio.Lock()
        self._append_listeners: list[Callable[[GoalRun], Awaitable[None]]] = []

    def add_append_listener(
        self, listener: Callable[[GoalRun], Awaitable[None]]
    ) -> None:
        self._append_listeners.append(listener)

    async def async_append(self, run: GoalRun) -> None:
        async with self._lock:
            runs = await asyncio.to_thread(self._read)
            runs = [item for item in runs if item.run_id != run.run_id]
            runs.append(run)
            await asyncio.to_thread(self._write, runs[-self.limit:])
        for listener in tuple(self._append_listeners):
            await listener(run)

    async def async_list(self) -> tuple[GoalRun, ...]:
        return tuple(await asyncio.to_thread(self._read))

    async def async_query(self, query: GoalRunQuery) -> tuple[GoalRun, ...]:
        """Return matching runs in chronological order after one store read."""
        runs = await self.async_list()
        return tuple(item for item in runs if _matches_query(item, query))

    async def async_latest(
        self,
        *,
        user_id: str | None = None,
        goal_id: str | None = None,
        failed_only: bool = False,
    ) -> GoalRun | None:
        matches = await self.async_query(
            GoalRunQuery(user_id=user_id, goal_id=goal_id, failed_only=failed_only)
        )
        return matches[-1] if matches else None

    async def async_seen_idempotency_key(self, key: str) -> bool:
        return any(item.idempotency_key == key for item in await self.async_list())

    def _read(self) -> list[GoalRun]:
        try:
            raw: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        values = cast(Mapping[str, object], raw).get("runs", ()) if isinstance(raw, Mapping) else ()
        result: list[GoalRun] = []
        for item in _mapping_sequence(values):
            try:
                result.append(GoalRun.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _write(self, runs: Sequence[GoalRun]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".homeintent_runs_", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {"schema_version": 1, "runs": [item.to_dict() for item in runs]},
                    handle, ensure_ascii=False, indent=2, sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


@dataclass(frozen=True)
class FailureExplanation:
    causality: CausalityLevel
    message: str
    run_id: str | None = None
    evidence: tuple[str, ...] = ()


def explain_goal_run(run: GoalRun | None) -> FailureExplanation:
    """Render only evidence recorded by execution/runtime adapters."""
    if run is None:
        return FailureExplanation(
            CausalityLevel.POSSIBLE_BUT_UNPROVEN,
            "Das kann ich anhand der vorhandenen Daten nicht sicher feststellen.",
        )
    if "fresh_runtime_query_empty" in run.evidence:
        return FailureExplanation(
            CausalityLevel.DERIVED_FROM_TRACE,
            "Der Auslöser trat ein, aber die frisch geprüfte Bedingung war nicht erfüllt; deshalb wurde keine Meldung versendet.",
            run.run_id,
            run.evidence,
        )
    failed_verifications = [
        verification for step in run.steps for verification in step.verification
        if not verification.success
    ]
    if failed_verifications:
        item = failed_verifications[0]
        if item.observed is not None:
            message = (
                f"Der Befehl wurde angenommen, aber {item.entity_id} hatte danach "
                f"weiterhin den Zustand {item.observed} statt {item.expected}."
            )
        else:
            message = (
                f"Für {item.entity_id} wurde der erwartete Zustand {item.expected} "
                "innerhalb der Prüffrist nicht beobachtet."
            )
        return FailureExplanation(
            CausalityLevel.DIRECTLY_OBSERVED, message, run.run_id, run.evidence
        )
    if run.failures:
        code = run.failures[0]
        messages = {
            FailureCode.TRIGGER_NOT_OBSERVED: "Der gespeicherte Auslöser ist im betrachteten Zeitraum nicht eingetreten.",
            FailureCode.CONDITION_FALSE: "Der Auslöser trat ein, aber die frisch geprüfte Bedingung war nicht erfüllt.",
            FailureCode.NOTIFICATION_TARGET_MISSING: "Für die Person war kein bestätigtes Benachrichtigungsziel hinterlegt.",
            FailureCode.NOTIFICATION_TARGET_AMBIGUOUS: "Das Benachrichtigungsziel war mehrdeutig; deshalb wurde nichts versendet.",
            FailureCode.TARGET_UNAVAILABLE: "Mindestens ein Ziel war unmittelbar vor der Ausführung nicht verfügbar.",
            FailureCode.POLICY_BLOCKED: "Die zentrale Ausführungsrichtlinie hat die Aktion blockiert.",
            FailureCode.CONFIRMATION_MISSING: "Die erforderliche Bestätigung lag zum Ausführungszeitpunkt nicht vor.",
            FailureCode.AUTOMATION_DISABLED: "Das persistente Ziel war zum Auslösezeitpunkt deaktiviert.",
            FailureCode.SERVICE_ERROR: "Home Assistant hat den Serviceaufruf mit einem Fehler beendet.",
        }
        return FailureExplanation(
            CausalityLevel.DERIVED_FROM_TRACE,
            messages.get(code, "Die gespeicherten Daten belegen keine eindeutige Ursache."),
            run.run_id,
            run.evidence,
        )
    return FailureExplanation(
        CausalityLevel.POSSIBLE_BUT_UNPROVEN,
        "Die gespeicherten Daten belegen keine eindeutige Ursache.",
        run.run_id,
        run.evidence,
    )


def _step_dict(value: StepExecutionRecord) -> dict[str, object]:
    return {
        "step_id": value.step_id, "operator_id": value.operator_id,
        "selected_targets": list(value.selected_targets),
        "preconditions": list(value.preconditions),
        "service_accepted": value.service_accepted,
        "verification": [
            {
                "entity_id": item.entity_id, "expected": item.expected,
                "observed": item.observed, "success": item.success,
                "failure_code": item.failure_code.value if item.failure_code else None,
                "observed_at": item.observed_at,
            }
            for item in value.verification
        ],
        "failure_code": value.failure_code.value if value.failure_code else None,
        "message": value.message,
        "executed_at": value.executed_at,
    }


def _step_from(raw: Mapping[str, object]) -> StepExecutionRecord:
    verification = tuple(
        VerificationRecord(
            str(item.get("entity_id", "")), str(item.get("expected", "")),
            _text(item.get("observed")), bool(item.get("success", False)),
            FailureCode(str(item["failure_code"])) if item.get("failure_code") else None,
            _text(item.get("observed_at")),
        )
        for item in _mapping_sequence(raw.get("verification", ()))
    )
    accepted = raw.get("service_accepted")
    return StepExecutionRecord(
        str(raw.get("step_id", "")), _text(raw.get("operator_id")),
        _strings(raw.get("selected_targets")), _strings(raw.get("preconditions")),
        accepted if isinstance(accepted, bool) else None, verification,
        FailureCode(str(raw["failure_code"])) if raw.get("failure_code") else None,
        str(raw.get("message", "")),
        _text(raw.get("executed_at")),
    )


def _notification_dict(value: NotificationRecord) -> dict[str, object]:
    return {
        "recipient_person_id": value.recipient_person_id,
        "target_id": value.target_id, "channel": value.channel,
        "severity": value.severity, "delivered": value.delivered,
        "dedupe_key": value.dedupe_key, "category": value.category,
    }


def _notification_from(raw: Mapping[str, object]) -> NotificationRecord:
    return NotificationRecord(
        str(raw.get("recipient_person_id", "")), str(raw.get("target_id", "")),
        str(raw.get("channel", "push")), str(raw.get("severity", "info")),
        bool(raw.get("delivered", False)), str(raw.get("dedupe_key", "")),
        str(raw.get("category", "")),
    )


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    values = cast(Sequence[object], value)
    return tuple(cast(Mapping[str, object], item) for item in values if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    return tuple(item for item in cast(Sequence[object], value) if isinstance(item, str)) if isinstance(value, (list, tuple)) else ()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _matches_query(run: GoalRun, query: GoalRunQuery) -> bool:
    if query.user_id is not None and run.user_id != query.user_id:
        return False
    if query.person_entity_id is not None and run.person_entity_id != query.person_entity_id:
        return False
    if query.goal_id is not None and run.goal_id != query.goal_id:
        return False
    if query.run_id is not None and run.run_id != query.run_id:
        return False
    if query.goal_kind is not None and run.goal.kind is not query.goal_kind:
        return False
    if query.routine_id is not None and run.goal.routine_id != query.routine_id:
        return False
    if query.status is not None and run.status is not query.status:
        return False
    if query.failed_only and run.status in {
        GoalRunStatus.SUCCESS,
        GoalRunStatus.SCHEDULED,
        GoalRunStatus.RUNNING,
        GoalRunStatus.PENDING,
    }:
        return False
    if query.entity_id is not None and query.entity_id not in _run_entity_ids(run):
        return False
    try:
        created = datetime.fromisoformat(run.created_at)
    except ValueError:
        return False
    try:
        if query.start_time is not None and created < query.start_time:
            return False
        if query.end_time is not None and created >= query.end_time:
            return False
    except TypeError:
        # Old malformed/naive timestamps cannot be assigned safely to an HA
        # local-time window, so they are ignored instead of guessed.
        return False
    return True


def _run_entity_ids(run: GoalRun) -> frozenset[str]:
    return frozenset(
        (
            *run.selected_targets,
            *run.goal.scope.entity_ids,
            *(entity_id for step in run.steps for entity_id in step.selected_targets),
            *(
                verification.entity_id
                for step in run.steps
                for verification in step.verification
            ),
        )
    )


__all__ = (
    "CausalityLevel", "FailureCode", "FailureExplanation", "GoalRun",
    "GoalRunClarification", "GoalRunQuery",
    "GoalRunStatus", "GoalRunStore", "NotificationRecord", "StepExecutionRecord",
    "VerificationRecord", "explain_goal_run",
)
