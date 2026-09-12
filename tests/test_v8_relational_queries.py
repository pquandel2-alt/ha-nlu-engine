"""End-to-end graph projection for safe, read-only relational queries."""

from __future__ import annotations

import pytest

from ha_nlu.engine import NluEngine
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.query_command import QueryCommand, QueryRelationKind
from ha_nlu.nlu.understanding import UnderstandingKind
from ha_nlu.world_model import build_world_model


def _temperature(entity_id: str, name: str, value: str, unit: str = "°C") -> EntitySnapshot:
    return EntitySnapshot(
        entity_id,
        name,
        "sensor",
        value,
        device_class="temperature",
        unit=unit,
    )


def test_live_entity_comparison_projects_from_graph_and_stays_read_only():
    outside = _temperature("sensor.outside", "Außentemperatur", "8")
    inside = _temperature("sensor.inside", "Innentemperatur", "21")
    entities = [outside, inside]
    outcome = NluEngine().understand(
        "Ist Außentemperatur kälter als Innentemperatur?",
        entities,
        build_world_model(entities, []),
    )

    assert outcome.kind is UnderstandingKind.QUERY
    assert outcome.payload is not None
    assert outcome.payload.plan is None
    assert outcome.payload.frame is not None
    assert outcome.payload.frame.intent == "HassRelationalComparison"
    assert outcome.payload.response_text.startswith("Ja,")
    assert outcome.payload.frame.semantic_graph is not None


def test_relational_comparison_preserves_negated_comparator_scope():
    outside = _temperature("sensor.outside", "Außentemperatur", "8")
    inside = _temperature("sensor.inside", "Innentemperatur", "21")
    entities = [outside, inside]
    outcome = NluEngine().understand(
        "Ist Außentemperatur nicht höher als Innentemperatur?",
        entities,
        build_world_model(entities, []),
    )

    assert outcome.kind is UnderstandingKind.QUERY
    assert outcome.payload is not None
    assert outcome.payload.plan is None
    command = outcome.payload.frame.parameters["query_command"]
    assert isinstance(command, QueryCommand)
    assert command.filter.relational is not None
    assert command.filter.relational.operator.name == "LTE"


def test_known_temperature_units_are_normalized_and_stay_read_only():
    celsius = _temperature("sensor.celsius", "Temperatur Celsius", "20")
    fahrenheit = _temperature("sensor.fahrenheit", "Temperatur Fahrenheit", "60", "°F")
    entities = [celsius, fahrenheit]
    outcome = NluEngine().understand(
        "Ist Temperatur Celsius wärmer als Temperatur Fahrenheit?",
        entities,
        build_world_model(entities, []),
    )

    assert outcome.kind is UnderstandingKind.QUERY
    assert not outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is None


def test_room_comparison_uses_one_unique_registry_temperature_sensor_per_area():
    living = EntitySnapshot(
        "sensor.living_temperature", "Wohnzimmer Temperatur", "sensor", "22",
        area_id="living", area_name="Wohnzimmer",
        device_class="temperature", unit="°C",
    )
    bedroom = EntitySnapshot(
        "sensor.bedroom_temperature", "Schlafzimmer Temperatur", "sensor", "20",
        area_id="bedroom", area_name="Schlafzimmer",
        device_class="temperature", unit="°C",
    )
    entities = [living, bedroom]

    outcome = NluEngine().understand(
        "Ist das Wohnzimmer wärmer als das Schlafzimmer?",
        entities,
        build_world_model(entities, []),
    )

    assert outcome.kind is UnderstandingKind.QUERY
    assert outcome.payload is not None
    assert outcome.payload.plan is None
    assert outcome.payload.response_text.startswith("Ja,")


def test_room_comparison_refuses_multiple_temperature_sensors_in_one_area():
    living_a = EntitySnapshot(
        "sensor.living_a", "Wohnzimmer Temperatur A", "sensor", "22",
        area_id="living", area_name="Wohnzimmer",
        device_class="temperature", unit="°C",
    )
    living_b = EntitySnapshot(
        "sensor.living_b", "Wohnzimmer Temperatur B", "sensor", "23",
        area_id="living", area_name="Wohnzimmer",
        device_class="temperature", unit="°C",
    )
    bedroom = EntitySnapshot(
        "sensor.bedroom", "Schlafzimmer Temperatur", "sensor", "20",
        area_id="bedroom", area_name="Schlafzimmer",
        device_class="temperature", unit="°C",
    )
    entities = [living_a, living_b, bedroom]

    outcome = NluEngine().understand(
        "Ist das Wohnzimmer wärmer als das Schlafzimmer?",
        entities,
        build_world_model(entities, []),
    )

    assert outcome.kind is UnderstandingKind.UNSUPPORTED
    assert not outcome.actionable


def test_same_area_query_uses_house_graph_registry_relation():
    television = EntitySnapshot(
        "media_player.tv", "Fernseher", "media_player", "on",
        area_id="living", area_name="Wohnzimmer",
    )
    ceiling = EntitySnapshot(
        "light.ceiling", "Deckenlampe", "light", "on",
        area_id="living", area_name="Wohnzimmer",
    )
    kitchen = EntitySnapshot(
        "light.kitchen", "Küchenlampe", "light", "on",
        area_id="kitchen", area_name="Küche",
    )
    entities = [television, ceiling, kitchen]
    outcome = NluEngine().understand(
        "Welche Lampen sind im selben Raum wie der Fernseher?",
        entities,
        build_world_model(entities, []),
    )

    assert outcome.kind is UnderstandingKind.QUERY
    assert outcome.payload is not None
    assert outcome.payload.plan is None
    assert outcome.payload.frame.intent == "HassRelationshipQuery"
    command = outcome.payload.frame.parameters["query_command"]
    assert isinstance(command, QueryCommand)
    assert command.filter.relationship is not None
    assert command.filter.relationship.kind is QueryRelationKind.SAME_AREA
    assert tuple(entity.entity_id for entity in outcome.payload.command.entities) == (
        "light.ceiling",
    )


@pytest.mark.parametrize(
    "text",
    (
        "Welcher Raum ist am wärmsten?",
        "Gibt es einen Raum mit mehr als zwei offenen Fenstern?",
        "Welche Räume haben ein offenes Fenster?",
        "Welche Lampen in Räumen mit offenem Fenster sind an?",
    ),
)
def test_v9_relational_aggregates_use_typed_read_only_query_algebra(text):
    window = EntitySnapshot(
        "binary_sensor.window",
        "Fenster oben",
        "binary_sensor",
        "on",
        area_id="bedroom",
        area_name="Schlafzimmer",
        floor_id="upper",
        floor_name="Oben",
        device_class="window",
    )
    outcome = NluEngine().understand(
        text, [window], build_world_model([window], [])
    )

    assert outcome.kind is UnderstandingKind.QUERY
    assert not outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is None
    assert outcome.payload.frame is not None
    command = outcome.payload.frame.parameters["query_command"]
    assert isinstance(command, QueryCommand)
    assert command.algebra is not None
