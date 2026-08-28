"""Drift guards for the shared domain/action vocabulary."""

from __future__ import annotations

import re
from pathlib import Path

from ha_nlu.nlu.domain_operations import (
    ACTION_EXPRESSIONS,
    DOMAIN_EXPRESSIONS,
    DOMAIN_WORD_ONLY_TERMS,
    DOMAIN_WORDS,
    INTENT_BY_DOMAIN_ACTION,
)
from ha_nlu.nlu.semantic_catalog import (
    SEMANTIC_RESOLUTION_WORDS,
    V7_AUTHORITATIVE_DIRECT_CAPABILITIES,
)


def test_every_resolver_word_is_lexical_or_an_explicit_exception():
    actual_exceptions: dict[str, frozenset[str]] = {}
    for domain, words in DOMAIN_WORDS.items():
        unmatched = frozenset(
            word
            for word in words
            if not any(re.fullmatch(expression, word, re.I) for expression in DOMAIN_EXPRESSIONS[domain])
        )
        if unmatched:
            actual_exceptions[domain] = unmatched
    assert actual_exceptions == DOMAIN_WORD_ONLY_TERMS


def test_every_registered_action_has_domain_and_action_vocabulary():
    for domain, action in INTENT_BY_DOMAIN_ACTION:
        assert domain in DOMAIN_EXPRESSIONS
        assert action in ACTION_EXPRESSIONS


def test_v7_authority_cohort_has_one_registered_semantic_source():
    for domain, intent in V7_AUTHORITATIVE_DIRECT_CAPABILITIES:
        matching_actions = {
            action
            for (registered_domain, action), registered_intent
            in INTENT_BY_DOMAIN_ACTION.items()
            if registered_domain == domain and registered_intent == intent
        }
        assert matching_actions
        assert domain in DOMAIN_EXPRESSIONS
        assert matching_actions <= ACTION_EXPRESSIONS.keys()
        assert SEMANTIC_RESOLUTION_WORDS


def test_v7_core_imports_vocabulary_through_catalogue_facade():
    root = Path(__file__).parents[1] / "custom_components" / "ha_nlu" / "nlu"
    for name in (
        "entity_resolution.py",
        "semantic_compiler.py",
        "semantic_interpreter.py",
        "semantic_lexicon.py",
        "semantic_utterance.py",
    ):
        source = (root / name).read_text(encoding="utf-8")
        assert "from .domain_operations import" not in source, name
        assert "_SEMANTIC_WORDS" not in source, name
