"""Structured response type (v2 plan Phase 19, "Antwortsystem"): the
engine's current ``match()`` collapses every kind of miss - no template
match, unresolved/ambiguous entity, wrong domain, wrong area, a rejected
capability - into a single ``None``, which is exactly enough for today's
one consumer (``conversation.py`` shows the same fixed "not understood"
text regardless of cause). ``NluResponse`` keeps that behaviour intact but
also exposes *why* a match failed, for consumers the plan lists in later
phases (Debug-Modus, Clarification) that do need to tell those cases apart.

``NluError`` mirrors ``nlu.validator.ValidationError``'s nine members by
name (mapped 1:1 in ``engine.py``) plus ``NO_MATCH`` for the failure case
the validator never sees at all: no hassil template matched, or the
matched parser's own entity/area resolution failed - both already handled
entirely inside ``parsers.py`` before a ``SemanticCommand`` exists to
validate. Kept as one flat enum (not two: a raw ``ValidationError`` plus a
separate "no match" case) so a consumer can switch on a single type.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .command import SemanticCommand


class NluError(Enum):
    NO_MATCH = auto()
    UNKNOWN_INTENT = auto()
    ENTITY_NOT_FOUND = auto()
    AMBIGUOUS_ENTITY = auto()
    AREA_NOT_FOUND = auto()
    INVALID_DOMAIN = auto()
    UNSUPPORTED_CAPABILITY = auto()
    MISSING_PARAMETER = auto()
    INVALID_PARAMETER = auto()
    INVALID_QUANTIFIER = auto()
    # A relative reference the grammar recognized but can't resolve without
    # guessing ("Die andere.", "Die daneben.") - v2 plan Phase 27,
    # "Pronomen und Referenzen". No current source: like AMBIGUOUS_ENTITY
    # before Phase 25, defined ahead of a wiring consumer - match_reference()
    # (engine.py) collapses it to a plain miss for now, same as
    # match_followup()'s established Phase 26 scope.
    AMBIGUOUS_REFERENCE = auto()


@dataclass(frozen=True)
class NluResponse:
    success: bool
    speech: str | None
    command: SemanticCommand | None
    error: NluError | None
