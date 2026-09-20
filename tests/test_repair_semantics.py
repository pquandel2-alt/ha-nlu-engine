from homeintent.nlu.language_frontend import analyse_language
from homeintent.nlu.repair_semantics import repair_sequences
from homeintent.nlu.semantic_graph import SemanticEdgeKind, build_semantic_graph
from homeintent.entities import EntitySnapshot
from homeintent.world_model import build_world_model
from homeintent.house_graph import RelationKind, RelationSpec


KITCHEN = EntitySnapshot(
    "light.kitchen", "Küchenlicht", "light", "on",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
LIVING = EntitySnapshot(
    "light.living", "Wohnzimmerlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)


def test_repair_retains_original_marker_and_replacement():
    document = analyse_language("Stell die Heizung auf 22, nein 21 Grad.")
    repairs = repair_sequences(document.structure)

    assert len(repairs) == 1
    assert repairs[0].marker == "nein"
    graph = build_semantic_graph(
        document.source_text,
        document.tokens,
        document.structure,
        document.semantics,
        document.utterance.speech_act,
    )
    assert any(edge.kind is SemanticEdgeKind.REPLACES for edge in graph.edges)


def test_unambiguous_target_repair_executes_only_replacement(engine):
    outcome = engine.understand(
        "Mach das Küchenlicht an, äh nein, das Wohnzimmerlicht.",
        [KITCHEN, LIVING],
    )

    assert outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is not None
    assert outcome.payload.plan.entity_id == LIVING.entity_id
    assert outcome.payload.frame is not None
    assert outcome.payload.frame.semantic_graph is not None
    assert any(
        edge.kind is SemanticEdgeKind.REPLACES
        for edge in outcome.payload.frame.semantic_graph.edges
    )
    assert (
        outcome.payload.command.parameters["reasoning_trace"].steps[0].operation
        == "repair_replacement"
    )


def test_value_repair_with_compound_target_executes_only_replacement(engine):
    climate = EntitySnapshot(
        "climate.living", "Wohnzimmerheizung", "climate", "heat",
        attributes={"temperature": 20},
        capabilities=frozenset({"TEMPERATURE"}),
    )

    outcome = engine.understand(
        "Stell die Wohnzimmerheizung auf 22 Grad, nein 21 Grad.", [climate]
    )

    assert outcome.actionable
    assert outcome.payload is not None and outcome.payload.plan is not None
    assert outcome.payload.plan.entity_id == climate.entity_id
    assert outcome.payload.plan.data == {"temperature": 21.0}
    assert (
        outcome.payload.command.parameters["reasoning_trace"].steps[0].operation
        == "repair_replacement"
    )


def test_elliptical_brightness_value_repair_uses_final_value(engine):
    light = EntitySnapshot(
        "light.main", "Licht", "light", "on",
        capabilities=frozenset({"BRIGHTNESS"}),
    )
    outcome = engine.understand(
        "Mach das Licht auf 50 Prozent, äh 30.",
        [light], build_world_model([light], []),
    )
    assert outcome.actionable
    assert outcome.payload is not None and outcome.payload.plan is not None
    assert outcome.payload.plan.data == {"brightness_pct": 30}


def test_elliptical_cover_value_repair_uses_final_value(engine):
    cover = EntitySnapshot(
        "cover.main", "Rollladen", "cover", "open",
        capabilities=frozenset({"POSITION"}),
    )
    outcome = engine.understand(
        "Rollladen auf 70, nein auf 40 Prozent.",
        [cover], build_world_model([cover], []),
    )
    assert outcome.actionable
    assert outcome.payload is not None and outcome.payload.plan is not None
    assert outcome.payload.plan.data == {"position": 40}


def test_property_repair_replaces_temperature_with_humidity(engine):
    temperature = EntitySnapshot(
        "sensor.temp", "Wohnzimmer Temperatur", "sensor", "21",
        area_id="living", area_name="Wohnzimmer",
        device_class="temperature", unit="°C",
    )
    humidity = EntitySnapshot(
        "sensor.humidity", "Wohnzimmer Feuchte", "sensor", "54",
        area_id="living", area_name="Wohnzimmer",
        device_class="humidity", unit="%",
    )
    entities = [temperature, humidity]
    outcome = engine.understand(
        "Wie warm ist es im Wohnzimmer — nein, wie hoch ist die Luftfeuchtigkeit?",
        entities, build_world_model(entities, []),
    )
    assert outcome.kind.name == "QUERY"
    assert not outcome.actionable
    assert outcome.payload is not None and outcome.payload.command is not None
    assert tuple(item.entity_id for item in outcome.payload.command.entities) == (
        humidity.entity_id,
    )
    assert outcome.payload.command.parameters["repair_replacement"] == "humidity"
    assert (
        outcome.payload.command.parameters["reasoning_trace"].steps[0].operation
        == "repair_replacement"
    )
    assert outcome.payload.response_text == "54 Prozent."


def test_property_repair_refuses_equal_measurement_sources(engine):
    sensors = [
        EntitySnapshot(
            f"sensor.humidity_{index}", f"Wohnzimmer Feuchte {index}",
            "sensor", str(50 + index), area_id="living",
            area_name="Wohnzimmer", device_class="humidity", unit="%",
        )
        for index in (1, 2)
    ]
    temperature = EntitySnapshot(
        "sensor.temp", "Wohnzimmer Temperatur", "sensor", "21",
        area_id="living", area_name="Wohnzimmer",
        device_class="temperature", unit="°C",
    )
    entities = [temperature, *sensors]
    outcome = engine.understand(
        "Wie warm ist es im Wohnzimmer — nein, wie hoch ist die Luftfeuchtigkeit?",
        entities, build_world_model(entities, []),
    )

    assert outcome.kind.name == "AMBIGUOUS"
    assert not outcome.actionable
    assert outcome.payload is not None and outcome.payload.plan is None


def test_property_repair_uses_configured_preferred_measurement(engine):
    sensors = [
        EntitySnapshot(
            f"sensor.humidity_{index}", f"Wohnzimmer Feuchte {index}",
            "sensor", str(50 + index), area_id="living",
            area_name="Wohnzimmer", device_class="humidity", unit="%",
        )
        for index in (1, 2)
    ]
    temperature = EntitySnapshot(
        "sensor.temp", "Wohnzimmer Temperatur", "sensor", "21",
        area_id="living", area_name="Wohnzimmer",
        device_class="temperature", unit="°C",
    )
    entities = [temperature, *sensors]
    base = build_world_model(entities, [])
    configured_graph = base.build_house_graph((RelationSpec(
        "area:living", RelationKind.PREFERRED_MEASUREMENT,
        "entity:sensor.humidity_2",
    ),))
    outcome = engine.understand(
        "Wie warm ist es im Wohnzimmer — nein, wie hoch ist die Luftfeuchtigkeit?",
        entities, base.with_house_graph(configured_graph),
    )

    assert outcome.kind.name == "QUERY"
    assert outcome.payload is not None and outcome.payload.command is not None
    assert tuple(
        entity.entity_id for entity in outcome.payload.command.entities
    ) == ("sensor.humidity_2",)
    assert outcome.payload.response_text == "52 Prozent."
