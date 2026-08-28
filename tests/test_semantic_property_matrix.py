"""Metamorphic V7 gate for independently ordered property commands."""

from __future__ import annotations

from itertools import product

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.understanding import UnderstandingAuthority


TARGETS = (
    EntitySnapshot(
        "cover.atlas",
        "Rollladen Atlas",
        "cover",
        "open",
        capabilities=frozenset({"POSITION"}),
        attributes={"current_position": 80},
    ),
    EntitySnapshot(
        "light.birke",
        "Licht Birke",
        "light",
        "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
        attributes={"brightness": 180},
    ),
    EntitySnapshot(
        "climate.citrin",
        "Heizung Citrin",
        "climate",
        "heat",
        capabilities=frozenset({"TEMPERATURE"}),
        attributes={"temperature": 20, "current_temperature": 19},
    ),
)

CASES = (
    (
        "cover.atlas",
        "set_cover_position",
        {"position": 40},
        (
            "Stelle {particle} Rollladen Atlas auf 40 Prozent",
            "Auf 40 Prozent {particle} den Rollladen Atlas stellen",
            "Rollladen Atlas {particle} bitte auf 40 Prozent",
        ),
    ),
    (
        "light.birke",
        "turn_on",
        {"brightness_pct": 40},
        (
            "Stelle {particle} Licht Birke auf 40 Prozent",
            "Auf 40 Prozent {particle} das Licht Birke stellen",
            "Licht Birke {particle} bitte auf 40 Prozent",
        ),
    ),
    (
        "climate.citrin",
        "set_temperature",
        {"temperature": 22},
        (
            "Stelle {particle} Heizung Citrin auf 22 Grad",
            "Auf 22 Grad {particle} die Heizung Citrin stellen",
            "Heizung Citrin {particle} bitte auf 22 Grad",
        ),
    ),
)


@pytest.mark.parametrize(
    ("entity_id", "service", "data", "shells"), CASES
)
def test_property_value_word_order_is_v7_authoritative(
    engine, entity_id: str, service: str, data: dict, shells: tuple[str, ...]
):
    for shell, particle in product(shells, ("", "mal", "doch", "kurz")):
        sentence = shell.format(particle=particle).replace("  ", " ")
        outcome = engine.understand(sentence, list(TARGETS))

        assert outcome.authority is UnderstandingAuthority.V7_MIGRATED, sentence
        assert outcome.payload is not None and outcome.payload.plan is not None, sentence
        assert outcome.payload.plan.entity_id == entity_id, sentence
        assert outcome.payload.plan.service == service, sentence
        assert outcome.payload.plan.data == data, sentence


@pytest.mark.parametrize("value", (4, 31, 99))
def test_out_of_range_temperature_never_creates_a_plan(engine, value: int):
    outcome = engine.understand(
        f"Stelle Heizung Citrin auf {value} Grad", list(TARGETS)
    )

    assert not outcome.actionable
