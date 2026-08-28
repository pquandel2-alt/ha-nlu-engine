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
    DEVICE_CLASS_ENTRIES,
    SEMANTIC_RESOLUTION_WORDS,
    MEASUREMENT_PROPERTY_SPECS,
    VALUE_INTENT_BY_DOMAIN_PROPERTY,
    V7_AUTHORITATIVE_COMMAND_CAPABILITIES,
    V7_AUTHORITATIVE_DIRECT_CAPABILITIES,
    V7_AUTHORITATIVE_QUERY_CAPABILITIES,
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
    assert V7_AUTHORITATIVE_DIRECT_CAPABILITIES == (
        V7_AUTHORITATIVE_COMMAND_CAPABILITIES
        | V7_AUTHORITATIVE_QUERY_CAPABILITIES
    )
    for domain, intent in V7_AUTHORITATIVE_COMMAND_CAPABILITIES:
        matching_actions = {
            action
            for (registered_domain, action), registered_intent
            in INTENT_BY_DOMAIN_ACTION.items()
            if registered_domain == domain and registered_intent == intent
        }
        assert domain in DOMAIN_EXPRESSIONS
        matching_properties = {
            property_name
            for (registered_domain, property_name), registered_intent
            in VALUE_INTENT_BY_DOMAIN_PROPERTY.items()
            if registered_domain == domain and registered_intent == intent
        }
        assert bool(matching_actions) != bool(matching_properties)
        assert matching_actions <= ACTION_EXPRESSIONS.keys()
        assert SEMANTIC_RESOLUTION_WORDS
    for domain, intent in V7_AUTHORITATIVE_QUERY_CAPABILITIES:
        measurement_domains = {
            specification[0]
            for specification in MEASUREMENT_PROPERTY_SPECS.values()
        }
        device_class_domains = {entry.value[0] for entry in DEVICE_CLASS_ENTRIES}
        assert (
            domain in DOMAIN_EXPRESSIONS
            or domain in measurement_domains
            or domain in device_class_domains
        )
        assert intent.startswith("Hass")


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
