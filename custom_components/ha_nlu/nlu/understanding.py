"""Canonical outcomes and trace data for one HomeIntent understanding turn.

This module is deliberately Home-Assistant- and parser-free.  It is the
stable boundary between language interpretation and the domain executors:
callers no longer need to infer why a matcher returned ``None`` or whether a
plan-less result is a query, a clarification, or a rejection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Generic, Mapping, Sequence, TypeVar, cast

from .parse_outcome import ParseFailureReason
from .semantic_utterance import SpeechAct
from .semantic_graph import SemanticGraph


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


class UnderstandingAuthority(Enum):
    """Pipeline that supplied the payload for one understanding outcome."""

    NONE = auto()
    LEGACY = auto()
    V7_FALLBACK = auto()
    V7_MIGRATED = auto()


class EvidenceKind(Enum):
    """Where a piece of interpretation evidence originated."""

    ORIGINAL = auto()
    NORMALIZED = auto()
    LEXICON = auto()
    LEXICAL = LEXICON
    REGISTRY = auto()
    ENTITY = auto()
    AREA = auto()
    FLOOR = auto()
    CONTEXT = auto()
    DISCOURSE = auto()
    WORLD_MODEL = auto()
    CAPABILITY = auto()
    PROPERTY = auto()
    UNIT = auto()
    TEMPORAL = auto()
    NEGATIVE_EVIDENCE = auto()
    CORRECTION = auto()
    SPELLING = auto()
    PHONETIC = auto()
    LEGACY = auto()
    STRUCTURE = auto()


class EvidencePolarity(Enum):
    """Whether evidence supports or contradicts a semantic claim."""

    POSITIVE = auto()
    NEGATIVE = auto()


@dataclass(frozen=True)
class UnderstandingEvidence:
    """One source-spanned, scored reason for an interpretation."""

    kind: EvidenceKind
    value: str
    start: int | None = None
    end: int | None = None
    score: float = 0.0
    detail: str | None = None
    polarity: EvidencePolarity = EvidencePolarity.POSITIVE
    claim: str | None = None
    source_id: str | None = None


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
    graph: SemanticGraph | None = None
    rejection_reason: str | None = None

    @property
    def raw_score(self) -> float:
        """Lossless score used by ranking and ambiguity decisions."""
        return self.score

    @property
    def display_score(self) -> float:
        """Bounded diagnostic presentation without affecting ranking."""
        return max(0.0, min(100.0, self.score))


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
    authority: UnderstandingAuthority = UnderstandingAuthority.NONE

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
    stage_differences: tuple[str, ...] = ()


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
    if _payload_signature(authoritative.payload) != _payload_signature(
        candidate.payload
    ):
        differences.append("payload")
    stage_differences: list[str] = []
    if _candidate_signature(authoritative.candidates) != _candidate_signature(
        candidate.candidates
    ):
        stage_differences.append("meaning_candidates")
    if _graph_signature(authoritative) != _graph_signature(candidate):
        stage_differences.append("semantic_graph")
    return ShadowComparison(
        source_text=authoritative.source_text,
        authoritative=authoritative,
        candidate=candidate,
        equivalent=not differences,
        differences=tuple(differences),
        stage_differences=tuple(stage_differences),
    )


def _candidate_signature(candidates: tuple[MeaningCandidate, ...]) -> object:
    return tuple(
        (
            item.key,
            round(item.score, 6),
            item.complete,
            _freeze(item.slots),
            item.missing_slots,
            item.conflicts,
            item.rejection_reason,
        )
        for item in candidates
    )


def _graph_signature(outcome: UnderstandingOutcome[object]) -> object | None:
    graphs = tuple(
        _freeze(candidate.graph.canonical_snapshot())
        for candidate in outcome.candidates
        if candidate.graph is not None
    )
    return graphs or None


def _freeze(value: object) -> object:
    """Return a deterministic comparison form for plan parameters."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return tuple(
            sorted((str(key), _freeze(item)) for key, item in mapping.items())
        )
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return tuple(_freeze(item) for item in sequence)
    if isinstance(value, (set, frozenset)):
        items = cast(set[object] | frozenset[object], value)
        return tuple(sorted((_freeze(item) for item in items), key=repr))
    return value


def _payload_signature(payload: object | None) -> object | None:
    """Compare observable meaning, not parser-specific bookkeeping.

    Legacy and V7 intentionally build independent frame and reasoning
    objects.  A shadow comparison must flag a changed service, target,
    parameter, query answer, or clarification set, but not object-internal
    provenance that cannot affect the user-visible result.
    """
    if payload is None:
        return None
    commands = getattr(payload, "commands", None)
    if commands is not None:
        return ("commands", tuple(_payload_signature(item) for item in commands))
    plan = getattr(payload, "plan", None)
    if plan is not None:
        return (
            "plan",
            getattr(plan, "domain", None),
            getattr(plan, "service", None),
            _freeze(getattr(plan, "entity_id", None)),
            _freeze(getattr(plan, "data", {})),
        )
    clarification = getattr(payload, "clarification", None)
    if clarification is not None:
        return (
            "clarification",
            getattr(clarification, "pending_intent", None),
            tuple(
                getattr(entity, "entity_id", None)
                for entity in getattr(clarification, "candidates", ())
            ),
            _freeze(getattr(clarification, "pending_parameters", {})),
        )
    frame = getattr(payload, "frame", None)
    command = getattr(payload, "command", None)
    entities = (
        getattr(command, "entities", ())
        if command is not None
        else getattr(payload, "context_entities", ())
    )
    return (
        "non_action",
        getattr(frame, "intent", None),
        tuple(getattr(entity, "entity_id", None) for entity in entities),
        getattr(payload, "response_text", None),
    )
