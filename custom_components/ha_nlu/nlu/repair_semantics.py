"""Structural representation of same-turn self correction."""

from __future__ import annotations

from dataclasses import dataclass

from .german_structure import ClauseKind, GermanStructuralAnalysis, StructuralRelationKind


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
