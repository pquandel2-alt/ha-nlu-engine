"""IntentParser abstraction (v2 plan, Phase 2): engine.py should orchestrate
routing and ServiceCall construction only, not contain the sentence-
matching logic itself. Concrete, hassil-based parsers live in
``ha_nlu.parsers`` (outside this package, since ``nlu/`` stays free of
hassil/HA imports) and implement this Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..entities import EntitySnapshot
from .frame import SemanticFrame


@dataclass(frozen=True)
class ParseContext:
    entities: list[EntitySnapshot]


@dataclass(frozen=True)
class ParseResult:
    frame: SemanticFrame
    resolved_entities: list[EntitySnapshot]


@dataclass(frozen=True)
class ClarificationRequest:
    """A pending disambiguation question (v2 plan Phase 25, "Clarification"):
    a parser's alternate outcome when a spoken name ties between multiple
    candidates instead of resolving to zero or one. Lives here rather than
    in ``nlu/context.py`` (which re-exports it for ``ConversationContext``'s
    ``pending_clarification`` field) to avoid a circular import - ``context.py``
    already depends on ``SemanticCommand`` from ``nlu/command.py``, which
    itself depends on this module for ``ParseResult``.

    Field names match the plan's ``ConversationState`` sketch exactly (brain
    node e2946a55, section 23).
    """

    pending_intent: str
    pending_target: str | None
    candidates: tuple[EntitySnapshot, ...]


@runtime_checkable
class IntentParser(Protocol):
    """Most parsers only ever return ``ParseResult | None`` - only
    ``SingleTargetParser`` (v2 plan Phase 25, "Clarification") can also
    return a ``ClarificationRequest``, when a name resolves to more than one
    tied candidate instead of zero or one. Kept on the shared Protocol
    rather than a parser-specific signature so ``engine.py`` can handle the
    case uniformly regardless of which parser produced it.
    """

    def parse(self, text: str, context: ParseContext) -> ParseResult | ClarificationRequest | None: ...
