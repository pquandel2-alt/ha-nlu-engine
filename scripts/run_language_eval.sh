#!/usr/bin/env bash
set -euo pipefail

python -m pytest -q \
  tests/test_language_eval_corpus.py \
  tests/test_semantic_metamorphic_invariance.py \
  tests/test_semantic_paraphrase_matrix.py \
  tests/test_v7_semantic_contracts.py \
  tests/test_engine_understanding.py \
  tests/test_entity_clarification.py \
  tests/test_semantic_interpreter.py \
  tests/test_v8_ood_structure.py \
  tests/test_v8_graph_metamorphic.py \
  tests/test_semantic_snapshot.py \
  tests/test_v8_relational_queries.py \
  tests/test_pragmatics_v8.py \
  tests/test_reference.py \
  tests/test_discourse.py
