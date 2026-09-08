import json
from pathlib import Path

import pytest

from ha_nlu.nlu.language_frontend import analyse_language


CORPUS = json.loads(
    (Path(__file__).parent / "data" / "v8_ood_de.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CORPUS, ids=lambda case: case["id"])
def test_handwritten_ood_corpus_retains_expected_relations(case):
    document = analyse_language(case["text"])
    observed = {relation.kind.name.lower() for relation in document.structure.relations}

    assert set(case["relations"]) <= observed
    assert document.structure.clauses
    assert all(clause.char_start < clause.char_end for clause in document.structure.clauses)


def test_unknown_meaning_bearing_predicate_is_not_silently_executable(engine):
    outcome = engine.understand("Mach das Küchenlicht flauschig.", [])

    assert not outcome.actionable
    assert "flauschig" in outcome.unexplained_tokens
