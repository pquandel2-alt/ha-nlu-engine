"""Stable, read-only snapshots of the V8 understanding stages."""

from __future__ import annotations

from typing import Mapping

from .language_frontend import LanguageDocument
from .evidence import explain_candidate
from .parser import ParseResult
from .semantic_interpreter import InterpreterResult
from .understanding import UnderstandingOutcome


def build_semantic_snapshot(
    document: LanguageDocument,
    interpreted: InterpreterResult,
    outcome: UnderstandingOutcome[object],
) -> Mapping[str, object]:
    """Expose structure, hypotheses, grounding and outcome without execution."""
    selected = (
        interpreted.candidates[interpreted.selected_candidate_index]
        if interpreted.selected_candidate_index is not None
        else None
    )
    diagnostic_graph = selected or (
        interpreted.candidates[0] if interpreted.candidates else None
    )
    resolved = (
        tuple(entity.entity_id for entity in interpreted.parse_result.resolved_entities)
        if isinstance(interpreted.parse_result, ParseResult)
        else ()
    )
    return {
        "input": document.source_text,
        "structure": {
            "clauses": tuple(
                {
                    "id": clause.clause_id,
                    "kind": clause.kind.name.lower(),
                    "span": (clause.char_start, clause.char_end),
                    "connector": clause.connector,
                    "predicates": clause.predicate_tokens,
                }
                for clause in document.structure.clauses
            ),
            "relations": tuple(
                {
                    "kind": relation.kind.name.lower(),
                    "source": relation.source_clause,
                    "target": relation.target_clause,
                }
                for relation in document.structure.relations
            ),
        },
        "graph": (
            diagnostic_graph.graph.canonical_snapshot()
            if diagnostic_graph and diagnostic_graph.graph
            else None
        ),
        "candidates": tuple(
            {
                "key": candidate.key,
                "score": candidate.score,
                "complete": candidate.complete,
                "missing": candidate.missing_slots,
                "conflicts": candidate.conflicts,
                "rejection_reason": candidate.rejection_reason,
                "evidence": tuple(
                    {
                        "kind": item.kind.name.lower(),
                        "polarity": item.polarity.name.lower(),
                        "claim": item.claim,
                        "score": item.score,
                        "detail": item.detail,
                    }
                    for item in candidate.evidence
                ),
                "explanation": explain_candidate(candidate),
            }
            for candidate in interpreted.candidates
        ),
        "selected": selected.key if selected is not None else None,
        "resolved_entities": resolved,
        "outcome": {
            "kind": outcome.kind.name.lower(),
            "reason": outcome.reason.name.lower() if outcome.reason else None,
            "actionable": outcome.actionable,
            "route": outcome.route,
        },
    }
