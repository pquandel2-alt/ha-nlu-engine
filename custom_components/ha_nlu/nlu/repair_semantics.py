"""Structural representation of same-turn self correction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .german_structure import ClauseKind, GermanStructuralAnalysis, StructuralRelationKind
from .language_frontend import LanguageDocument
from .temporal_semantics import TemporalKind


@dataclass(frozen=True)
class RepairSequence:
    original_clause_id: str
    replacement_clause_id: str
    marker: str


def repair_sequences(structure: GermanStructuralAnalysis) -> tuple[RepairSequence, ...]:
    clauses = {item.clause_id: item for item in structure.clauses}
    return tuple(
        RepairSequence(
            relation.source_clause,
            relation.target_clause,
            clauses[relation.target_clause].connector or "repair",
        )
        for relation in structure.relations
        if relation.kind is StructuralRelationKind.REPLACES
        and clauses[relation.target_clause].kind is ClauseKind.REPAIR
    )


def repaired_temporal_command(document: LanguageDocument) -> str | None:
    """Return one command surface containing only the final temporal slot.

    This does not schedule anything. It resolves one structurally proven
    same-slot correction, after which the existing relative/calendar parser
    and persistent automation path remain authoritative.
    """
    repairs = repair_sequences(document.structure)
    if len(repairs) != 1:
        return None
    clauses = {clause.clause_id: clause for clause in document.structure.clauses}
    original = clauses.get(repairs[0].original_clause_id)
    replacement = clauses.get(repairs[0].replacement_clause_id)
    if original is None or replacement is None:
        return None
    original_temporal = tuple(
        item for item in document.temporal
        if original.token_start <= item.token_start < original.token_end
        and item.kind in {TemporalKind.RELATIVE_DELAY, TemporalKind.ABSOLUTE_TIME, TemporalKind.DATE}
    )
    replacement_temporal = tuple(
        item for item in document.temporal
        if replacement.token_start <= item.token_start < replacement.token_end
        and item.kind in {TemporalKind.RELATIVE_DELAY, TemporalKind.ABSOLUTE_TIME, TemporalKind.DATE}
    )
    replacement_text = document.source_text[replacement.char_start:replacement.char_end]
    original_text = document.source_text[original.char_start:original.char_end]
    original_text = re.sub(
        r"\s*[—-]\s*(?:ach|aeh|äh|also)?\s*$", "", original_text,
        flags=re.IGNORECASE,
    )
    if replacement_temporal:
        # The replacement is self-contained. If it also contains the action,
        # use it alone; otherwise replace the old temporal span in the main
        # clause while retaining the original action and target.
        has_action_words = any(
            token.canonical in {"an", "aus", "auf", "zu", "hoch", "runter"}
            for token in document.tokens[replacement.token_start:replacement.token_end]
        )
        if has_action_words:
            return replacement_text
        if len(original_temporal) != 1 or len(replacement_temporal) != 1:
            return None
        old = original_temporal[0]
        old_start = document.tokens[old.token_start].start - original.char_start
        old_end = document.tokens[old.token_end - 1].end - original.char_start
        return (original_text[:old_start] + replacement_text + original_text[old_end:]).strip()
    # Elliptical relative replacement may inherit only the unit and relation
    # from one prior delay ("in zehn Minuten, nein in fünf").
    if len(original_temporal) != 1 or original_temporal[0].kind is not TemporalKind.RELATIVE_DELAY:
        return None
    replacement_numbers = tuple(
        token for token in document.tokens[replacement.token_start:replacement.token_end]
        if token.is_number or token.canonical in {
            "ein", "eine", "zwei", "drei", "vier", "fuenf", "sechs",
            "sieben", "acht", "neun", "zehn", "fuenfzehn", "zwanzig",
            "dreissig", "sechzig",
        }
    )
    if len(replacement_numbers) != 1:
        return None
    old = original_temporal[0]
    old_tokens = document.tokens[old.token_start:old.token_end]
    unit = old_tokens[-1].text
    repaired_time = f"in {replacement_numbers[0].text} {unit}"
    old_start = old_tokens[0].start - original.char_start
    old_end = old_tokens[-1].end - original.char_start
    return (original_text[:old_start] + repaired_time + original_text[old_end:]).strip()
