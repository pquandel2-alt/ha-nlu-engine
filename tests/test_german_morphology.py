"""Tests for deterministic, article-safe German area morphology."""

from __future__ import annotations

import pytest

from ha_nlu.nlu.german_morphology import (
    GrammaticalGender,
    area_gender,
    dative_location_phrase,
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
