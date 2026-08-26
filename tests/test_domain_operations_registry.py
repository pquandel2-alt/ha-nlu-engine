"""Drift guards for the shared domain/action vocabulary."""

from __future__ import annotations

import re

from ha_nlu.nlu.domain_operations import (
    DOMAIN_EXPRESSIONS,
    DOMAIN_WORD_ONLY_TERMS,
    DOMAIN_WORDS,
    INTENT_BY_DOMAIN_ACTION,
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
    from ha_nlu.nlu.domain_operations import ACTION_EXPRESSIONS

    for domain, action in INTENT_BY_DOMAIN_ACTION:
        assert domain in DOMAIN_EXPRESSIONS
        assert action in ACTION_EXPRESSIONS
