from ha_nlu.nlu.evidence import evidence_score
from ha_nlu.nlu.understanding import (
    EvidenceKind,
    MeaningCandidate,
    UnderstandingEvidence,
)


def test_raw_evidence_score_preserves_distance_above_display_ceiling():
    stronger = tuple(
        UnderstandingEvidence(EvidenceKind.ENTITY, str(index), score=12.0)
        for index in range(7)
    )
    weaker = tuple(
        UnderstandingEvidence(EvidenceKind.ENTITY, str(index), score=12.0)
        for index in range(6)
    )

    stronger_raw = evidence_score(stronger)
    weaker_raw = evidence_score(weaker)

    assert stronger_raw == 119.0
    assert weaker_raw == 107.0
    assert stronger_raw - weaker_raw == 12.0
    candidate = MeaningCandidate("strong", stronger_raw, True)
    assert candidate.raw_score == 119.0
    assert candidate.display_score == 100.0
