"""Hand-written V9 algebra oracles; no expected result is compiler-generated."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from homeintent.entities import EntitySnapshot
from homeintent.engine import NluEngine
from homeintent.devices import DeviceSnapshot
from homeintent.house_graph import (
    ConfidenceClass,
    FactProvenance,
    GraphNode,
    HouseGraph,
    NodeKind,
    RelationKind,
    RelationSpec,
    TraversalDirection,
    TraversalStep,
    TraversalLimitExceeded,
)
from homeintent.nlu.primitives import SemanticProperty
from homeintent.nlu.context import ConversationContext
from homeintent.nlu.discourse import (
    DiscourseRole,
    current_discourse_group,
    remember_entities,
    remember_query_group,
)
from homeintent.nlu.query_command import (
    AggregateExpression,
    AggregateKind,
    CompareExpression,
    GroupExpression,
    LimitExpression,
    LiteralSetExpression,
    MeasurementExpression,
    OrderExpression,
    QueryCommand,
    QueryFilter,
    QueryResultStatus,
    QueryScope,
    QueryTarget,
    QueryTargetKind,
    QueryTraversal,
    QuantifiedExpression,
    RelationFilterExpression,
    RelationalOperator,
    SetExpression,
    SetOperator,
    SortDirection,
    SourceExpression,
    StateFilterExpression,
    StateDurationFilterExpression,
    ThresholdExpression,
)
from homeintent.nlu.query_executor import QueryExecutor
from homeintent.nlu.semantic_state import SemanticState
from homeintent.nlu.unit_reasoning import normalize_measurement
from homeintent.world_model import build_world_model


def _entity(
    entity_id: str,
    name: str,
    domain: str,
    state: str,
    *,
    area: str,
    area_name: str,
    floor: str,
    floor_name: str,
    device_class: str | None = None,
    unit: str | None = None,
) -> EntitySnapshot:
    return EntitySnapshot(
        entity_id, name, domain, state,
        area_id=area, area_name=area_name,
        floor_id=floor, floor_name=floor_name,
        floor_level=(1 if floor == "upper" else 0),
        device_class=device_class, unit=unit,
    )


@pytest.fixture
def world():
    entities = [
        _entity("binary_sensor.kitchen_window", "Küchenfenster", "binary_sensor", "on", area="kitchen", area_name="Küche", floor="ground", floor_name="Erdgeschoss", device_class="window"),
        _entity("binary_sensor.office_window", "Bürofenster", "binary_sensor", "off", area="office", area_name="Büro", floor="upper", floor_name="Obergeschoss", device_class="window"),
        _entity("binary_sensor.bed_window", "Schlafzimmerfenster", "binary_sensor", "on", area="bed", area_name="Schlafzimmer", floor="upper", floor_name="Obergeschoss", device_class="window"),
        _entity("light.kitchen", "Küchenlicht", "light", "on", area="kitchen", area_name="Küche", floor="ground", floor_name="Erdgeschoss"),
        _entity("light.office", "Bürolicht", "light", "on", area="office", area_name="Büro", floor="upper", floor_name="Obergeschoss"),
        _entity("light.bed", "Schlafzimmerlicht", "light", "off", area="bed", area_name="Schlafzimmer", floor="upper", floor_name="Obergeschoss"),
        _entity("sensor.kitchen_temp", "Küchentemperatur", "sensor", "68", area="kitchen", area_name="Küche", floor="ground", floor_name="Erdgeschoss", device_class="temperature", unit="°F"),
        _entity("sensor.office_temp", "Bürotemperatur", "sensor", "19", area="office", area_name="Büro", floor="upper", floor_name="Obergeschoss", device_class="temperature", unit="°C"),
        _entity("sensor.bed_temp", "Schlafzimmertemperatur", "sensor", "22", area="bed", area_name="Schlafzimmer", floor="upper", floor_name="Obergeschoss", device_class="temperature", unit="°C"),
        _entity("sensor.kitchen_humidity", "Küchenfeuchte", "sensor", "45", area="kitchen", area_name="Küche", floor="ground", floor_name="Erdgeschoss", device_class="humidity", unit="%"),
        _entity("sensor.office_humidity", "Bürofeuchte", "sensor", "55", area="office", area_name="Büro", floor="upper", floor_name="Obergeschoss", device_class="humidity", unit="%"),
        _entity("sensor.bed_humidity", "Schlafzimmerfeuchte", "sensor", "50", area="bed", area_name="Schlafzimmer", floor="upper", floor_name="Obergeschoss", device_class="humidity", unit="%"),
    ]
    return build_world_model(entities, [])


def _source(kind: QueryTargetKind, **kwargs: object) -> SourceExpression:
    return SourceExpression(QueryTarget(kind=kind, **kwargs))


OPEN_WINDOWS = StateFilterExpression(
    _source(QueryTargetKind.ENTITY, domain="binary_sensor", device_class="window"),
    SemanticState.OPEN,
)
AREAS_WITH_OPEN_WINDOWS = RelationFilterExpression(
    _source(QueryTargetKind.AREA),
    QueryTraversal(((RelationKind.LOCATED_IN, TraversalDirection.INCOMING),)),
    OPEN_WINDOWS,
)


def _run(expression, world):
    command = QueryCommand(
        "HassSemanticReasoningQuery",
        QueryScope.LIST,
        QueryTarget(),
        QueryFilter(),
        expression,
    )
    return QueryExecutor().execute(command, [], world)


def test_relational_filter_finds_areas_with_open_windows(world):
    result = _run(AREAS_WITH_OPEN_WINDOWS, world)

    assert result.status is QueryResultStatus.MATCHED
    assert tuple(area.area_id for area in result.areas) == ("bed", "kitchen")
    assert result.trace is not None
    assert result.trace.steps[-1].operation == "filter_relation"


def test_nested_filter_finds_on_lights_in_qualifying_areas(world):
    expression = StateFilterExpression(
        RelationFilterExpression(
            _source(QueryTargetKind.ENTITY, domain="light"),
            QueryTraversal(((RelationKind.LOCATED_IN, TraversalDirection.OUTGOING),)),
            AREAS_WITH_OPEN_WINDOWS,
        ),
        SemanticState.ON,
    )
    result = _run(expression, world)

    assert tuple(entity.entity_id for entity in result.entities) == ("light.kitchen",)


def test_count_exists_and_group_by_floor_are_typed(world):
    count = _run(AggregateExpression(OPEN_WINDOWS, AggregateKind.COUNT), world)
    exists = _run(AggregateExpression(AREAS_WITH_OPEN_WINDOWS, AggregateKind.EXISTS), world)
    grouped = _run(GroupExpression(
        OPEN_WINDOWS,
        QueryTraversal(((RelationKind.ON_FLOOR, TraversalDirection.OUTGOING),)),
        QueryTargetKind.FLOOR,
    ), world)

    assert count.scalar == 2
    assert exists.scalar is True
    assert tuple((item.label, item.value) for item in grouped.groups) == (
        ("Erdgeschoss", 1),
        ("Obergeschoss", 1),
    )


def test_any_and_all_compare_explicit_typed_sets(world):
    lights = _source(QueryTargetKind.ENTITY, domain="light")
    off_lights = StateFilterExpression(lights, SemanticState.OFF)

    any_off = _run(QuantifiedExpression(lights, off_lights, AggregateKind.ANY), world)
    all_off = _run(QuantifiedExpression(lights, off_lights, AggregateKind.ALL), world)

    assert any_off.scalar is True
    assert all_off.scalar is False


def test_superlative_uses_unique_measurement_binding_and_unit_normalization(world):
    areas = _source(QueryTargetKind.AREA)
    measured = MeasurementExpression(areas, SemanticProperty.TEMPERATURE)
    expression = LimitExpression(
        OrderExpression(areas, measured, SortDirection.DESCENDING),
        1,
    )
    result = _run(expression, world)

    assert tuple(area.area_id for area in result.areas) == ("bed",)
    assert result.trace is not None
    assert [step.operation for step in result.trace.steps][-2:] == ["order", "limit"]


def test_superlative_limit_retains_equal_boundary_values():
    entities = [
        _entity(
            f"sensor.{area}", f"{area} Temperatur", "sensor", "23",
            area=area, area_name=area.title(), floor="ground",
            floor_name="Erdgeschoss", device_class="temperature", unit="°C",
        )
        for area in ("a", "b")
    ]
    world = build_world_model(entities, [])
    areas = _source(QueryTargetKind.AREA)
    result = _run(
        LimitExpression(
            OrderExpression(
                areas,
                MeasurementExpression(areas, SemanticProperty.TEMPERATURE),
                SortDirection.DESCENDING,
            ),
            1,
        ),
        world,
    )

    assert tuple(area.area_id for area in result.areas) == ("a", "b")
    assert result.trace is not None
    assert result.trace.steps[-1].detail == "1;ties=retained"


def test_comparative_set_query_compares_against_one_reference_area(world):
    all_areas = _source(QueryTargetKind.AREA)
    office = _source(
        QueryTargetKind.AREA,
        area=next(area for area in world.areas if area.area_id == "office"),
    )
    expression = CompareExpression(
        MeasurementExpression(all_areas, SemanticProperty.TEMPERATURE),
        RelationalOperator.GT,
        MeasurementExpression(office, SemanticProperty.TEMPERATURE),
    )
    result = _run(expression, world)

    assert tuple(area.area_id for area in result.areas) == ("bed", "kitchen")


def test_set_difference_is_over_grounded_ids(world):
    upstairs = _source(QueryTargetKind.AREA, floor_id="upper")
    expression = SetExpression(
        AREAS_WITH_OPEN_WINDOWS,
        SetOperator.DIFFERENCE,
        upstairs,
    )
    result = _run(expression, world)

    assert tuple(area.area_id for area in result.areas) == ("kitchen",)


def test_query_result_is_remembered_as_typed_non_executable_group(world):
    result = _run(AREAS_WITH_OPEN_WINDOWS, world)
    discourse = remember_query_group(None, result)
    group = current_discourse_group(discourse, semantic_type="area")

    assert group is not None
    assert group.member_ids == ("area:bed", "area:kitchen")
    assert group.origin_query.algebra is not None
    assert group.relation_provenance


def test_stale_discourse_literal_never_returns_a_partial_set(world):
    expression = LiteralSetExpression(
        QueryTargetKind.AREA, ("area:kitchen", "area:removed")
    )
    result = _run(expression, world)

    assert result.status is QueryResultStatus.TARGET_NOT_FOUND
    assert result.member_ids == ()
    assert result.trace is not None
    assert result.trace.steps[-1].operation == "discourse_reference"


def _query_context(result, previous=None):
    assert result.payload is not None and result.payload.command is not None
    command = result.payload.command
    query_result = command.parameters["query_result"]
    discourse = remember_entities(
        previous.discourse if previous is not None else None,
        command.entities,
        role=DiscourseRole.QUERY_RESULT,
    )
    discourse = remember_query_group(discourse, query_result)
    return ConversationContext(
        last_command=command,
        last_entities=tuple(command.entities),
        last_area=command.area,
        pending_clarification=None,
        discourse=discourse,
    )


def test_multiturn_area_set_filter_then_relational_command(world):
    engine = NluEngine()
    first = engine.understand(
        "Welche Räume haben offene Fenster?", list(world.entities), world
    )
    first_context = _query_context(first)

    second = engine.match_query_followup(
        "Welche davon sind oben?", list(world.entities), first_context, world
    )

    assert second is not None and second.command is not None
    second_result = second.command.parameters["query_result"]
    assert tuple(area.area_id for area in second_result.areas) == ("bed",)
    second_context = _query_context(
        type("Outcome", (), {"payload": second})(), first_context
    )

    third = engine.match_reference(
        "Mach dort die Lichter aus.", list(world.entities), second_context, world
    )

    assert third is not None and third.plan is not None
    assert third.plan.entity_id == "light.bed"


def test_multiturn_area_set_exclusion_uses_difference(world):
    engine = NluEngine()
    first = engine.understand(
        "Welche Räume haben offene Fenster?", list(world.entities), world
    )
    context = _query_context(first)

    followup = engine.match_query_followup(
        "Außer im Schlafzimmer.", list(world.entities), context, world
    )

    assert followup is not None and followup.command is not None
    command = followup.command.parameters["query_command"]
    assert isinstance(command.algebra, SetExpression)
    assert command.algebra.operator is SetOperator.DIFFERENCE
    result = followup.command.parameters["query_result"]
    assert tuple(area.area_id for area in result.areas) == ("kitchen",)


def test_multiturn_area_set_accepts_nested_relation_then_floor_filter(world):
    adjusted = tuple(
        replace(entity, state="on")
        if entity.entity_id == "binary_sensor.office_window"
        else replace(entity, state="75")
        if entity.entity_id == "sensor.kitchen_temp"
        else replace(entity, state="23")
        if entity.entity_id == "sensor.office_temp"
        else entity
        for entity in world.entities
    )
    adjusted_world = build_world_model(adjusted, [])
    engine = NluEngine()
    first = engine.understand(
        "Welche Räume sind wärmer als das Schlafzimmer?",
        list(adjusted), adjusted_world,
    )
    first_context = _query_context(first)

    second = engine.match_query_followup(
        "Welche davon haben offene Fenster?",
        list(adjusted), first_context, adjusted_world,
    )

    assert second is not None and second.command is not None
    second_result = second.command.parameters["query_result"]
    assert tuple(area.area_id for area in second_result.areas) == (
        "kitchen", "office",
    )
    second_context = _query_context(
        type("Outcome", (), {"payload": second})(), first_context
    )
    third = engine.match_query_followup(
        "Und davon nur die oben.",
        list(adjusted), second_context, adjusted_world,
    )
    assert third is not None and third.command is not None
    third_result = third.command.parameters["query_result"]
    assert tuple(area.area_id for area in third_result.areas) == ("office",)


def test_multiturn_entity_set_exclusion_uses_normal_command_pipeline(world):
    standing = _entity(
        "light.standing", "Stehlampe", "light", "on",
        area="office", area_name="Büro",
        floor="upper", floor_name="Obergeschoss",
    )
    entities = [*world.entities, standing]
    expanded_world = build_world_model(entities, [])
    engine = NluEngine()
    first = engine.understand("Welche Lampen sind an?", entities, expanded_world)
    context = _query_context(first)

    second = engine.match_reference(
        "Alle außer der Stehlampe aus.", entities, context, expanded_world
    )

    assert second is not None and second.plan is not None
    assert sorted(second.plan.entity_id) == ["light.kitchen", "light.office"]


def test_multiturn_entity_set_can_add_state_filter(world):
    entities = [
        replace(entity, state="off")
        if entity.entity_id == "light.kitchen"
        else entity
        for entity in world.entities
    ]
    adjusted_world = build_world_model(entities, [])
    engine = NluEngine()
    first = engine.understand("Welche Lampen gibt es?", entities, adjusted_world)
    context = _query_context(first)

    second = engine.match_query_followup(
        "Und davon nur die, die noch an sind.",
        entities,
        context,
        adjusted_world,
    )

    assert second is not None and second.command is not None
    command = second.command.parameters["query_command"]
    assert isinstance(command.algebra, StateFilterExpression)
    result = second.command.parameters["query_result"]
    assert tuple(entity.entity_id for entity in result.entities) == ("light.office",)


def test_meaning_changing_quantifier_and_temporal_forms_stay_distinct(world):
    engine = NluEngine()
    more_than = engine.understand(
        "Welche Räume haben mehr als zwei offene Fenster?",
        list(world.entities), world,
    )
    at_least = engine.understand(
        "Welche Räume haben mindestens zwei offene Fenster?",
        list(world.entities), world,
    )
    duration = engine.understand(
        "Welche Fenster sind seit fünf Minuten offen?",
        list(world.entities), world,
    )
    history = engine.understand(
        "Welche Fenster wurden in den letzten fünf Minuten geöffnet?",
        list(world.entities), world,
    )

    assert more_than.payload is not None and more_than.payload.command is not None
    assert at_least.payload is not None and at_least.payload.command is not None
    left = more_than.payload.command.parameters["query_command"].algebra
    right = at_least.payload.command.parameters["query_command"].algebra
    assert isinstance(left, ThresholdExpression)
    assert isinstance(right, ThresholdExpression)
    assert left.operator is RelationalOperator.GT
    assert right.operator is RelationalOperator.GTE
    assert duration.kind.name == "UNSUPPORTED"
    assert duration.payload is not None and duration.payload.command is not None
    assert isinstance(
        duration.payload.command.parameters["query_command"].algebra,
        StateDurationFilterExpression,
    )
    assert history.kind.name == "UNSUPPORTED"
    assert history.payload is None or history.payload.command is None


def test_multiple_measurements_for_area_are_ambiguous():
    entities = [
        _entity("sensor.a", "Temperatur A", "sensor", "21", area="living", area_name="Wohnzimmer", floor="ground", floor_name="Erdgeschoss", device_class="temperature", unit="°C"),
        _entity("sensor.b", "Temperatur B", "sensor", "23", area="living", area_name="Wohnzimmer", floor="ground", floor_name="Erdgeschoss", device_class="temperature", unit="°C"),
    ]
    world = build_world_model(entities, [])
    result = _run(
        MeasurementExpression(_source(QueryTargetKind.AREA), SemanticProperty.TEMPERATURE),
        world,
    )

    assert result.status is QueryResultStatus.AMBIGUOUS
    assert result.entities == ()


def test_confirmed_preferred_measurement_resolves_sensor_ambiguity():
    entities = [
        _entity("sensor.a", "Temperatur A", "sensor", "21", area="living", area_name="Wohnzimmer", floor="ground", floor_name="Erdgeschoss", device_class="temperature", unit="°C"),
        _entity("sensor.b", "Temperatur B", "sensor", "23", area="living", area_name="Wohnzimmer", floor="ground", floor_name="Erdgeschoss", device_class="temperature", unit="°C"),
    ]
    base = build_world_model(entities, [])
    configured = base.build_house_graph((
        RelationSpec(
            "area:living", RelationKind.PREFERRED_MEASUREMENT, "entity:sensor.b"
        ),
    ))
    world = base.with_house_graph(configured)
    result = _run(
        MeasurementExpression(_source(QueryTargetKind.AREA), SemanticProperty.TEMPERATURE),
        world,
    )

    assert result.status is QueryResultStatus.MATCHED
    assert result.member_ids == ("area:living",)


def test_bounded_traversal_excludes_statistical_edges_and_cycles():
    graph = HouseGraph()
    for node_id in ("area:a", "area:b", "area:c"):
        graph.add_node(GraphNode(node_id, NodeKind.AREA, node_id))
    graph.add_relation("area:a", RelationKind.ADJACENT_TO, "area:b", provenance=FactProvenance.CONFIGURED, confidence=ConfidenceClass.CONFIRMED)
    graph.add_relation("area:b", RelationKind.ADJACENT_TO, "area:a", provenance=FactProvenance.DERIVED, confidence=ConfidenceClass.DERIVED)
    graph.add_relation("area:b", RelationKind.ADJACENT_TO, "area:c", provenance=FactProvenance.STATISTICAL, confidence=ConfidenceClass.ESTIMATE)

    steps = (TraversalStep(RelationKind.ADJACENT_TO), TraversalStep(RelationKind.ADJACENT_TO))
    assert graph.traverse(("area:a",), steps) == ()
    assert tuple(item.node.node_id for item in graph.traverse(("area:a",), steps, asserted_only=False)) == ("area:c",)
    with pytest.raises(ValueError):
        graph.traverse(("area:a",), steps, max_depth=1)


def test_registry_backed_four_hop_sensor_to_floor_traversal():
    sensor = _entity(
        "sensor.device_temperature", "Gerätetemperatur", "sensor", "21",
        area="upper_room", area_name="Zimmer oben",
        floor="upper", floor_name="Obergeschoss",
        device_class="temperature", unit="°C",
    )
    device = DeviceSnapshot(
        "device.thermostat", "Thermostat", area_id="upper_room",
        area_name="Zimmer oben", floor_id="upper", floor_name="Obergeschoss",
        entity_ids=(sensor.entity_id,),
    )
    graph = build_world_model([sensor], [device]).house_graph
    matches = graph.traverse(
        ("entity:sensor.device_temperature",),
        (
            TraversalStep(RelationKind.BELONGS_TO),
            TraversalStep(RelationKind.LOCATED_IN),
            TraversalStep(RelationKind.LOCATED_IN),
        ),
    )

    assert tuple(item.node.node_id for item in matches) == ("floor:upper",)
    assert len(matches[0].path) == 3


def test_graph_frontier_bounds_fail_atomically():
    graph = HouseGraph()
    graph.add_node(GraphNode("area:root", NodeKind.AREA, "Root"))
    for index in range(4):
        node_id = f"area:{index}"
        graph.add_node(GraphNode(node_id, NodeKind.AREA, node_id))
        graph.add_relation(
            "area:root", RelationKind.ADJACENT_TO, node_id,
            provenance=FactProvenance.CONFIGURED,
            confidence=ConfidenceClass.CONFIRMED,
        )

    with pytest.raises(TraversalLimitExceeded):
        graph.traverse(
            ("area:root",), (TraversalStep(RelationKind.ADJACENT_TO),),
            max_frontier_size=3,
        )


def test_state_duration_uses_last_changed_not_event_history():
    old = EntitySnapshot(
        "binary_sensor.old", "Altes Fenster", "binary_sensor", "on",
        device_class="window", last_changed=datetime.now(timezone.utc) - timedelta(minutes=8),
    )
    recent = EntitySnapshot(
        "binary_sensor.recent", "Neues Fenster", "binary_sensor", "on",
        device_class="window", last_changed=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    world = build_world_model([old, recent], [])
    expression = StateDurationFilterExpression(
        StateFilterExpression(
            _source(QueryTargetKind.ENTITY, domain="binary_sensor", device_class="window"),
            SemanticState.OPEN,
        ),
        300,
    )

    result = _run(expression, world)

    assert result.status is QueryResultStatus.MATCHED
    assert result.member_ids == ("entity:binary_sensor.old",)
    assert result.trace is not None
    assert result.trace.steps[-1].operation == "filter_duration"


def test_state_duration_requires_complete_last_changed_evidence():
    entity = EntitySnapshot(
        "binary_sensor.window", "Fenster", "binary_sensor", "on",
        device_class="window",
    )
    result = _run(
        StateDurationFilterExpression(
            StateFilterExpression(
                _source(QueryTargetKind.ENTITY, domain="binary_sensor", device_class="window"),
                SemanticState.OPEN,
            ),
            300,
        ),
        build_world_model([entity], []),
    )

    assert result.status is QueryResultStatus.UNSUPPORTED
    assert result.member_ids == ()


def test_unit_reasoning_is_closed_and_dimension_safe():
    fahrenheit = normalize_measurement(68, "°F", SemanticProperty.TEMPERATURE)
    kilowatts = normalize_measurement(1.5, "kW", SemanticProperty.POWER)

    assert fahrenheit is not None and fahrenheit.value == pytest.approx(20)
    assert kilowatts is not None and kilowatts.value == 1500
    assert normalize_measurement(20, "mystery", SemanticProperty.TEMPERATURE) is None
    assert normalize_measurement(55, "mystery", SemanticProperty.HUMIDITY) is None


@pytest.mark.parametrize(
    "text",
    (
        "Welche Räume haben ein offenes Fenster?",
        "In welchen Räumen ist ein Fenster offen?",
        "Wo gibt es offene Fenster?",
    ),
)
def test_room_with_open_window_paraphrases_are_read_only(text, world):
    outcome = NluEngine().understand(text, list(world.entities), world)

    assert outcome.kind.name == "QUERY"
    assert not outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is None
    assert outcome.payload.frame is not None
    assert outcome.payload.frame.parameters["query_command"].algebra is not None


def test_room_paraphrases_share_algebra_but_window_query_does_not(world):
    engine = NluEngine()
    texts = (
        "Welche Räume haben ein offenes Fenster?",
        "In welchen Räumen ist ein Fenster offen?",
        "Wo gibt es offene Fenster?",
    )
    algebras = []
    for text in texts:
        outcome = engine.understand(text, list(world.entities), world)
        assert outcome.payload is not None and outcome.payload.frame is not None
        algebras.append(outcome.payload.frame.parameters["query_command"].algebra)
    window_outcome = engine.understand(
        "Welche Fenster sind offen?", list(world.entities), world
    )
    assert window_outcome.payload is not None and window_outcome.payload.frame is not None
    window_algebra = window_outcome.payload.frame.parameters["query_command"].algebra

    assert algebras[0] == algebras[1] == algebras[2]
    assert window_algebra != algebras[0]


def test_nested_relational_query_is_productive_end_to_end(world):
    outcome = NluEngine().understand(
        "Welche Lampen in Räumen mit offenem Fenster sind an?",
        list(world.entities),
        world,
    )

    assert outcome.kind.name == "QUERY"
    assert outcome.payload is not None and outcome.payload.frame is not None
    result = outcome.payload.frame.parameters["query_result"]
    assert tuple(entity.entity_id for entity in result.entities) == ("light.kitchen",)
    assert outcome.payload.plan is None


def test_relational_projection_is_not_window_specific():
    door = _entity(
        "binary_sensor.kitchen_door", "Küchentür", "binary_sensor", "on",
        area="kitchen", area_name="Küche", floor="ground",
        floor_name="Erdgeschoss", device_class="door",
    )
    world = build_world_model([door], [])
    outcome = NluEngine().understand(
        "Welche Räume haben eine offene Tür?", [door], world
    )

    assert outcome.kind.name == "QUERY"
    assert outcome.payload is not None and outcome.payload.frame is not None
    result = outcome.payload.frame.parameters["query_result"]
    assert tuple(area.area_id for area in result.areas) == ("kitchen",)


def test_group_threshold_projects_from_quantifier_components(world):
    outcome = NluEngine().understand(
        "Welche Räume haben mindestens zwei offene Fenster?",
        list(world.entities), world,
    )

    assert outcome.kind.name == "QUERY"
    assert outcome.payload is not None and outcome.payload.frame is not None
    expression = outcome.payload.frame.parameters["query_command"].algebra
    assert isinstance(expression, ThresholdExpression)


def test_negative_relational_scope_projects_to_difference(world):
    outcome = NluEngine().understand(
        "Welche Räume haben offene Fenster aber kein eingeschaltetes Licht?",
        list(world.entities), world,
    )

    assert outcome.kind.name == "QUERY"
    assert outcome.payload is not None and outcome.payload.frame is not None
    expression = outcome.payload.frame.parameters["query_command"].algebra
    assert isinstance(expression, SetExpression)
    assert expression.operator is SetOperator.DIFFERENCE
    result = outcome.payload.frame.parameters["query_result"]
    assert tuple(area.area_id for area in result.areas) == ("bed",)


def test_reasoning_ambiguity_is_never_actionable():
    entities = [
        _entity("sensor.a", "Temperatur A", "sensor", "21", area="living", area_name="Wohnzimmer", floor="ground", floor_name="Erdgeschoss", device_class="temperature", unit="°C"),
        _entity("sensor.b", "Temperatur B", "sensor", "23", area="living", area_name="Wohnzimmer", floor="ground", floor_name="Erdgeschoss", device_class="temperature", unit="°C"),
    ]
    world = build_world_model(entities, [])
    outcome = NluEngine().understand("Welcher Raum ist am wärmsten?", entities, world)

    assert outcome.kind.name == "AMBIGUOUS"
    assert not outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is None


def test_relational_command_reuses_selection_but_passes_normal_action_pipeline(world):
    outcome = NluEngine().understand(
        "Mach in allen Räumen mit offenem Fenster das Licht aus.",
        list(world.entities),
        world,
    )

    assert outcome.kind.name == "COMMAND"
    assert outcome.payload is not None and outcome.payload.plan is not None
    assert outcome.payload.plan.entity_id == ["light.bed", "light.kitchen"]
    assert outcome.payload.command is not None
    assert outcome.payload.command.parameters["selection_query"].algebra is not None


def test_empty_relational_selection_never_falls_back_to_all_domain_entities():
    entities = [
        _entity(
            "binary_sensor.window", "Fenster", "binary_sensor", "off",
            area="living", area_name="Wohnzimmer",
            floor="ground", floor_name="Erdgeschoss", device_class="window",
        ),
        _entity(
            "light.living", "Wohnzimmerlicht", "light", "on",
            area="living", area_name="Wohnzimmer",
            floor="ground", floor_name="Erdgeschoss",
        ),
    ]
    outcome = NluEngine().understand(
        "Mach in allen Räumen mit offenem Fenster das Licht aus.",
        entities,
        build_world_model(entities, []),
    )

    assert not outcome.actionable
    assert outcome.payload is None or outcome.payload.plan is None


@pytest.mark.parametrize(
    "text",
    (
        "Mach nicht alle Lichter in Räumen mit offenen Fenstern aus.",
        "Entriegle nicht die Türen in Räumen mit offenen Fenstern.",
    ),
)
def test_negated_relational_commands_never_produce_a_service_plan(text, world):
    outcome = NluEngine().understand(text, list(world.entities), world)

    assert not outcome.actionable
    assert outcome.payload is None or outcome.payload.plan is None


def test_handwritten_v9_ood_corpus_runs_end_to_end(world):
    cases = json.loads(
        (Path(__file__).parent / "data" / "v9_reasoning_ood_de.json").read_text()
    )
    engine = NluEngine()
    for case in cases:
        outcome = engine.understand(case["text"], list(world.entities), world)
        assert outcome.actionable is (
            "expected_action_entity_ids" in case
        ), case["text"]
        if "expected_kind" in case:
            assert outcome.kind.name.casefold() == case["expected_kind"], case["text"]
            continue
        assert outcome.payload is not None and outcome.payload.frame is not None, case["text"]
        if "expected_action_entity_ids" in case:
            assert outcome.payload.plan is not None
            actual = outcome.payload.plan.entity_id
            assert sorted(actual if isinstance(actual, list) else [actual]) == case["expected_action_entity_ids"]
            continue
        result = outcome.payload.frame.parameters["query_result"]
        if "expected_area_ids" in case:
            assert [area.area_id for area in result.areas] == case["expected_area_ids"], case["text"]
        if "expected_entity_ids" in case:
            assert [entity.entity_id for entity in result.entities] == case["expected_entity_ids"], case["text"]


def test_handwritten_v9_ood_corpus_is_large_unique_and_oracled():
    cases = json.loads(
        (Path(__file__).parent / "data" / "v9_reasoning_ood_de.json").read_text()
    )

    assert len(cases) >= 150
    assert len({case["text"] for case in cases}) == len(cases)
    assert all(
        isinstance(case.get("category"), str) and case["category"]
        for case in cases
    )
    assert all(
        "expected_kind" in case
        or "expected_area_ids" in case
        or "expected_entity_ids" in case
        or "expected_action_entity_ids" in case
        for case in cases
    )
    categories = {case.get("category") for case in cases}
    assert {
        "free_order", "colloquial", "relative", "quantifier", "negation",
        "aggregate", "measurement", "superlative", "state_duration",
        "event_history", "hypothetical", "safety", "invalid_repair",
    } <= categories


@pytest.mark.parametrize(
    ("text", "entity", "expected_data"),
    (
        (
            "Stell die Heizung auf 22, nein 21 Grad.",
            EntitySnapshot(
                "climate.heating", "Heizung", "climate", "heat",
                attributes={"temperature": 20},
                capabilities=frozenset({"TEMPERATURE"}),
            ),
            {"temperature": 21.0},
        ),
        (
            "Fahr den Rollladen auf 50, nein 30 Prozent.",
            EntitySnapshot(
                "cover.blind", "Rollladen", "cover", "open",
                capabilities=frozenset({"POSITION"}),
            ),
            {"position": 30.0},
        ),
    ),
)
def test_value_repair_replaces_instead_of_accumulating(text, entity, expected_data):
    world = build_world_model([entity], [])
    outcome = NluEngine().understand(text, [entity], world)

    assert outcome.kind.name == "COMMAND"
    assert outcome.payload is not None and outcome.payload.plan is not None
    assert outcome.payload.plan.data == expected_data
    assert 22 not in outcome.payload.plan.data.values()
    assert 50 not in outcome.payload.plan.data.values()


def test_incomplete_property_repair_never_keeps_old_percentage():
    entity = EntitySnapshot(
        "light.main", "Licht", "light", "on",
        capabilities=frozenset({"BRIGHTNESS", "COLOR_TEMPERATURE"}),
    )
    outcome = NluEngine().understand(
        "Stell das Licht auf 50 Prozent Helligkeit – nein, Farbtemperatur.",
        [entity],
        build_world_model([entity], []),
    )

    assert not outcome.actionable
    assert outcome.payload is None or outcome.payload.plan is None
