"""Meaning-preserving speech transformations must not change execution."""

from __future__ import annotations

import pytest

from ha_nlu.entities import EntitySnapshot


ENTITIES = [
    EntitySnapshot(
        "light.kueche",
        "Küchenlicht",
        "light",
        "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    ),
    EntitySnapshot(
        "cover.buero",
        "Rollladen Büro",
        "cover",
        "closed",
        capabilities=frozenset({"POSITION"}),
    ),
]


@pytest.mark.parametrize(
    ("base", "variants"),
    (
        (
            "Schalte das Küchenlicht aus",
            (
                "Also, schalte das Küchenlicht aus",
                "Ähm, schalte das Küchenlicht aus",
                "Schalte, äh, das Küchenlicht aus",
                "Schalte mal kurz das Küchenlicht aus!",
            ),
        ),
        (
            "Fahre den Rollladen Büro hoch",
            (
                "Okay, fahre den Rollladen Büro hoch",
                "Äh fahre mal den Rollladen Büro hoch",
                "Fahr doch den Rollladen Büro hoch!",
            ),
        ),
    ),
)
def test_fillers_and_hesitations_preserve_service_and_target(
    engine, base: str, variants: tuple[str, ...]
) -> None:
    expected = engine.match(base, ENTITIES)

    assert expected is not None and expected.plan is not None
    for sentence in variants:
        result = engine.match(sentence, ENTITIES)
        assert result is not None and result.plan is not None, sentence
        assert result.plan == expected.plan, sentence


@pytest.mark.parametrize("filler", ("also", "okay", "ok", "gut", "nun", "na gut"))
@pytest.mark.parametrize("position", ("leading", "middle", "trailing"))
@pytest.mark.parametrize(
    ("base", "middle"),
    (
        ("Schalte das Küchenlicht aus", "Schalte {filler} das Küchenlicht aus"),
        ("Fahre den Rollladen Büro hoch", "Fahre {filler} den Rollladen Büro hoch"),
    ),
)
def test_discourse_fillers_are_position_invariant(
    engine, filler: str, position: str, base: str, middle: str
) -> None:
    variants = {
        "leading": f"{filler}, {base}",
        "middle": middle.format(filler=filler),
        "trailing": f"{base}, {filler}",
    }
    expected = engine.match(base, ENTITIES)

    result = engine.match(variants[position], ENTITIES)

    assert expected is not None and expected.plan is not None
    assert result is not None and result.plan == expected.plan
