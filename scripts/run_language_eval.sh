#!/usr/bin/env bash
set -euo pipefail

python -m pytest -q \
  tests/test_language_eval_corpus.py \
  tests/test_semantic_metamorphic_invariance.py \
  tests/test_semantic_paraphrase_matrix.py \
  tests/test_v7_semantic_contracts.py \
  tests/test_engine_understanding.py \
  tests/test_entity_clarification.py \
  tests/test_semantic_interpreter.py
