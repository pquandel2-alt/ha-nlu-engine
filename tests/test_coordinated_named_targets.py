from __future__ import annotations

from ha_nlu.engine import CommandPlan
from ha_nlu.entities import EntitySnapshot


LIGHTS = [
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.flur", "Flurlicht", "light", "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]


def test_one_verb_is_distributed_over_two_explicit_targets(engine):
    result = engine.match("Schalte Küchenlicht und Flurlicht aus", LIGHTS)

    assert isinstance(result, CommandPlan)
    assert {command.plan.entity_id for command in result.commands} == {
        "light.kueche", "light.flur",
    }
    assert {command.plan.service for command in result.commands} == {"turn_off"}


def test_coordinated_targets_remain_atomic_on_one_invalid_target(engine):
    unsupported = EntitySnapshot("sensor.flur", "Flursensor", "sensor", "12")

    assert engine.match(
        "Schalte Küchenlicht und Flursensor aus", LIGHTS + [unsupported]
    ) is None
