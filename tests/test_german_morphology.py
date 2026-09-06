"""Tests for deterministic, article-safe German area morphology."""

from __future__ import annotations

import pytest

from ha_nlu.nlu.german_morphology import (
    GrammaticalGender,
    area_gender,
    dative_location_phrase,
    entity_name_gender,
    nominative_pronoun_for_entity,
)


@pytest.mark.parametrize(
    ("name", "gender", "phrase"),
    (
        ("Küche", GrammaticalGender.FEMININE, "in der Küche"),
        ("Flur", GrammaticalGender.MASCULINE, "im Flur"),
        ("Bad", GrammaticalGender.NEUTER, "im Bad"),
        ("Waschküche", GrammaticalGender.FEMININE, "in der Waschküche"),
        ("Gästebad", GrammaticalGender.NEUTER, "im Gästebad"),
        ("Hobbyraum", GrammaticalGender.MASCULINE, "im Hobbyraum"),
    ),
)
def test_known_area_gender_and_dative_phrase(
    name: str, gender: GrammaticalGender, phrase: str
) -> None:
    assert area_gender(name) is gender
    assert dative_location_phrase(name) == phrase


@pytest.mark.parametrize(
    ("name", "phrase"),
    (
        ("Kids Room", "im Bereich Kids Room"),
        ("Küche EG", "im Bereich Küche EG"),
        ("", "im angegebenen Bereich"),
        ("   ", "im angegebenen Bereich"),
    ),
)
def test_unknown_or_empty_area_uses_safe_fallback(name: str, phrase: str) -> None:
    assert area_gender(name) is None
    assert dative_location_phrase(name) == phrase


@pytest.mark.parametrize(
    ("name", "gender", "pronoun"),
    (
        ("Küchenlicht", GrammaticalGender.NEUTER, "es"),
        ("Stehlampe", GrammaticalGender.FEMININE, "sie"),
        ("Flurschalter", GrammaticalGender.MASCULINE, "er"),
    ),
)
def test_entity_name_head_proves_singular_pronoun(
    name: str, gender: GrammaticalGender, pronoun: str
) -> None:
    assert entity_name_gender(name) is gender
    assert nominative_pronoun_for_entity(name) == pronoun


def test_unknown_entity_name_has_no_pronoun() -> None:
    assert entity_name_gender("Gerät links") is None
    assert nominative_pronoun_for_entity("Gerät links") is None
