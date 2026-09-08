"""Central deterministic evidence policy for meaning candidates.

Weights rank interpretations; they never authorize execution.  Domain
validators and execution policy remain the only executability authorities.
"""

from __future__ import annotations

from typing import Mapping

from .understanding import (
    EvidenceKind,
    EvidencePolarity,
    MeaningCandidate,
    UnderstandingEvidence,
)


EVIDENCE_BASE_SCORE = 35.0
EVIDENCE_WEIGHTS: Mapping[EvidenceKind, float] = {
    EvidenceKind.ORIGINAL: 1.0,
    EvidenceKind.NORMALIZED: 0.0,
    EvidenceKind.LEXICON: 3.0,
    EvidenceKind.STRUCTURE: 4.0,
    EvidenceKind.REGISTRY: 6.0,
    EvidenceKind.ENTITY: 12.0,
    EvidenceKind.AREA: 7.0,
    EvidenceKind.FLOOR: 7.0,
    EvidenceKind.CAPABILITY: 6.0,
    EvidenceKind.PROPERTY: 5.0,
    EvidenceKind.UNIT: 4.0,
    EvidenceKind.TEMPORAL: 4.0,
    EvidenceKind.CONTEXT: 5.0,
    EvidenceKind.DISCOURSE: 7.0,
    EvidenceKind.WORLD_MODEL: 5.0,
    EvidenceKind.SPELLING: 0.0,
    EvidenceKind.PHONETIC: 0.0,
    EvidenceKind.CORRECTION: 0.0,
    EvidenceKind.NEGATIVE_EVIDENCE: 5.0,
    EvidenceKind.LEGACY: 0.0,
}

CONFLICT_PENALTY = 25.0
UNEXPLAINED_TOKEN_PENALTY = 5.0
VARIANT_COST_PENALTY = 10.0
CAPABILITY_CONTRADICTION_PENALTY = 18.0
UNIT_CONTRADICTION_PENALTY = 12.0


def evidence_score(
    evidence: tuple[UnderstandingEvidence, ...],
    *,
    variant_cost: float = 0.0,
) -> float:
    """Return a stable 0..100 score from explicit evidence only."""
    total = EVIDENCE_BASE_SCORE - variant_cost * VARIANT_COST_PENALTY
    for item in evidence:
        magnitude = abs(item.score) or EVIDENCE_WEIGHTS[item.kind]
        total += (
            -magnitude
            if item.polarity is EvidencePolarity.NEGATIVE
            else magnitude
        )
    return max(0.0, min(100.0, total))


def explain_candidate(candidate: MeaningCandidate) -> tuple[str, ...]:
    """Render a deterministic score breakdown for debug/diagnostics."""
    lines = [f"{candidate.key}: {candidate.score:.1f}"]
    for item in candidate.evidence:
        magnitude = abs(item.score) or EVIDENCE_WEIGHTS[item.kind]
        sign = "-" if item.polarity is EvidencePolarity.NEGATIVE else "+"
        detail = item.detail or item.value
        lines.append(f"{sign} {magnitude:.1f} {item.kind.name.lower()}: {detail}")
    return tuple(lines)
