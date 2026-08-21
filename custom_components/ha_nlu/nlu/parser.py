"""IntentParser abstraction (v2 plan, Phase 2): engine.py should orchestrate
routing and ServiceCall construction only, not contain the sentence-
matching logic itself. Concrete, hassil-based parsers live in
``ha_nlu.parsers`` (outside this package, since ``nlu/`` stays free of
hassil/HA imports) and implement this Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from ..areas import AreaSnapshot
from ..entities import EntityIndex, EntitySnapshot
from ..world_model import WorldModel
from .frame import SemanticFrame


@dataclass(frozen=True)
class ParseContext:
    entities: list[EntitySnapshot]
    # World Model Wave 1's EntityIndex, built once per turn by engine.py and
    # reused across parsers (see Wave 1 report: without this, the cost of
    # resolve_entity_scored()'s per-entity generate_aliases() scan
    # multiplies with every additional pipeline stage Wave 3+ introduces).
    # None keeps every parser's behaviour byte-for-byte unchanged (full scan).
    index: EntityIndex | None = None
    # The per-turn WorldModel (conversation.py builds it every turn already) -
    # None keeps every existing caller unchanged; only query parsers that need
    # device/area-level lookups read this.
    world_model: WorldModel | None = None
    # V5 Wave 5 (V5.18, "Context in Automations") - the previous turn's
    # ConversationContext.last_entities/last_area (nlu/context.py), plumbed
    # through as plain primitives rather than a ConversationContext object
    # itself, same reasoning ReferenceParser's parse() already documents for
    # taking these as parameters (parsers.py) - decouples this module from
    # nlu/context.py. ()/None keeps every existing caller unchanged; only the
    # automation trigger/condition/action parsers' pronoun handling ("es")
    # reads these (Regel 6 - same context fields the command path already
    # resolves pronouns against, not a second context system).
    last_entities: tuple[EntitySnapshot, ...] = ()
    last_area: AreaSnapshot | None = None


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
    # Parameters already parsed before target disambiguation (for example
    # the requested 22-degree setpoint). Empty for all older clarification
    # paths, so existing callers remain unchanged.
    pending_parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AmbiguousReference:
    """A relative reference recognized by the grammar but not resolvable
    without guessing (v2 plan Phase 27, "Pronomen und Referenzen") - e.g.
    "Die andere.", "Die daneben.". The engine keeps no "not-selected sibling
    candidates" list and no spatial/adjacency model at all, so resolving
    *which* other entity is meant would require guessing - explicitly
    forbidden by the plan ("Keine zufällige Auswahl", brain node e2946a55,
    section 25). Distinct from ``ClarificationRequest``: a clarification has
    real candidates to ask the user about, this has none at all - it maps to
    ``NluError.AMBIGUOUS_REFERENCE`` (nlu/response.py) rather than a
    follow-up question.

    Lives here (not ``ReferenceParser``'s own return type in ``parsers.py``)
    for the same reason ``ClarificationRequest`` does: kept close to
    ``ParseResult``, its sibling alternate-outcome type. Not part of the
    shared ``IntentParser`` Protocol below - like ``ContextFollowupParser``,
    ``ReferenceParser`` is special-cased directly by ``engine.py``
    (``match_reference()``), not routed through ``_select_parser()``.
    """

    source_text: str


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
