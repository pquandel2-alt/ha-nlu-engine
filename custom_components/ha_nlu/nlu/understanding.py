"""Canonical outcomes and trace data for one HomeIntent understanding turn.

This module is deliberately Home-Assistant- and parser-free.  It is the
stable boundary between language interpretation and the domain executors:
callers no longer need to infer why a matcher returned ``None`` or whether a
plan-less result is a query, a clarification, or a rejection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Generic, Mapping, TypeVar

from .parse_outcome import ParseFailureReason
from .semantic_utterance import SpeechAct


class UnderstandingKind(Enum):
    """Exhaustive public result classes for a language turn."""

    QUERY = auto()
    COMMAND = auto()
    AUTOMATION = auto()
    MANAGEMENT = auto()
    CLARIFICATION = auto()
    AMBIGUOUS = auto()
    UNSUPPORTED = auto()
    UNSAFE = auto()


class EvidenceKind(Enum):
    """Where a piece of interpretation evidence originated."""

    ORIGINAL = auto()
    NORMALIZED = auto()
    LEXICON = auto()
    REGISTRY = auto()
    CONTEXT = auto()
    CAPABILITY = auto()
    SPELLING = auto()
    PHONETIC = auto()
    LEGACY = auto()


@dataclass(frozen=True)
class UnderstandingEvidence:
    """One source-spanned, scored reason for an interpretation."""

    kind: EvidenceKind
    value: str
    start: int | None = None
    end: int | None = None
    score: float = 0.0
    detail: str | None = None


@dataclass(frozen=True)
class MeaningCandidate:
    """A ranked but not yet executable semantic interpretation."""

    key: str
    score: float
    complete: bool
    slots: Mapping[str, object] = field(default_factory=dict[str, object])
    missing_slots: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    evidence: tuple[UnderstandingEvidence, ...] = ()


T = TypeVar("T")


@dataclass(frozen=True)
class UnderstandingOutcome(Generic[T]):
    """The one canonical result of understanding a complete user turn.

    ``payload`` is an already validated domain object (for example a legacy
    ``MatchResult`` during migration).  Language modules only construct
    candidates; the orchestration boundary attaches an executable payload
    after resolution and safety validation.
    """

    kind: UnderstandingKind
    source_text: str
    normalized_text: str
    speech_act: SpeechAct
    payload: T | None = None
    reason: ParseFailureReason | None = None
    speech: str | None = None
    candidates: tuple[MeaningCandidate, ...] = ()
    evidence: tuple[UnderstandingEvidence, ...] = ()
    unexplained_tokens: tuple[str, ...] = ()
    corrections: tuple[str, ...] = ()
    route: str | None = None
    margin: float | None = None

    @property
    def actionable(self) -> bool:
        return self.kind in {
            UnderstandingKind.COMMAND,
            UnderstandingKind.AUTOMATION,
            UnderstandingKind.MANAGEMENT,
        } and self.payload is not None

    @property
    def safe_non_action(self) -> bool:
        return self.kind in {
            UnderstandingKind.QUERY,
            UnderstandingKind.CLARIFICATION,
            UnderstandingKind.AMBIGUOUS,
            UnderstandingKind.UNSUPPORTED,
            UnderstandingKind.UNSAFE,
        }


@dataclass(frozen=True)
class ShadowComparison:
    """Read-only comparison between candidate and authoritative pipelines."""

    source_text: str
    authoritative: UnderstandingOutcome[object]
    candidate: UnderstandingOutcome[object]
    equivalent: bool
    differences: tuple[str, ...] = ()


def compare_outcomes(
    authoritative: UnderstandingOutcome[object],
    candidate: UnderstandingOutcome[object],
) -> ShadowComparison:
    """Compare two outcomes without executing either payload."""
    differences: list[str] = []
    if authoritative.kind is not candidate.kind:
        differences.append(
            f"kind:{authoritative.kind.name}!={candidate.kind.name}"
        )
    if authoritative.speech_act is not candidate.speech_act:
        differences.append(
            "speech_act:"
            f"{authoritative.speech_act.name}!={candidate.speech_act.name}"
        )
    if authoritative.reason is not candidate.reason:
        left = authoritative.reason.name if authoritative.reason else "-"
        right = candidate.reason.name if candidate.reason else "-"
        differences.append(f"reason:{left}!={right}")
    if authoritative.actionable != candidate.actionable:
        differences.append(
            f"actionable:{authoritative.actionable}!={candidate.actionable}"
        )
    if authoritative.payload != candidate.payload:
        differences.append("payload")
    return ShadowComparison(
        source_text=authoritative.source_text,
        authoritative=authoritative,
        candidate=candidate,
        equivalent=not differences,
        differences=tuple(differences),
    )
