"""HomeIntent v4.2.1 plan, Phase 4 (Sections 6-11): nlu/query_command.py's
new QueryCommand/QueryResult type system. Hass-free, no engine involved
(mirrors tests/test_semantic_state.py's style).

Pure construction/shape tests only - nothing here is wired into
engine.py/parsers.py yet (Phase 7 does that non-destructively), so there is
no "real" producer/consumer to exercise. These tests exist to pin the
dataclass shapes/defaults so Phase 5 (QueryExecutor) and Phase 7 (migration)
can build on them without re-deriving what fields mean.
"""

from __future__ import annotations

from ha_nlu.areas import AreaSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.query_command import (
    QueryCommand,
    QueryFilter,
    QueryResult,
    QueryResultStatus,
    QueryScope,
    QueryTarget,
)
from ha_nlu.nlu.semantic_state import SemanticState


def test_query_target_defaults_to_no_device_class_area_or_entity():
    target = QueryTarget(domain="binary_sensor")
    assert target.device_class is None
    assert target.area is None
    assert target.entity_id is None


def test_query_target_can_carry_device_class_area_and_entity_id():
    area = AreaSnapshot(area_id="wohnzimmer", name="Wohnzimmer")
    target = QueryTarget(domain="binary_sensor", device_class="window", area=area, entity_id="binary_sensor.fenster")
    assert target.domain == "binary_sensor"
    assert target.device_class == "window"
    assert target.area is area
    assert target.entity_id == "binary_sensor.fenster"


def test_query_filter_state_defaults_to_none_for_bare_existence_queries():
    assert QueryFilter().state is None


def test_query_filter_can_carry_a_requested_semantic_state():
    assert QueryFilter(state=SemanticState.OPEN).state is SemanticState.OPEN


def test_query_command_assembles_intent_scope_target_and_filter():
    target = QueryTarget(domain="cover")
    query_filter = QueryFilter(state=SemanticState.OPEN)
    command = QueryCommand(intent="HassStateQuery", scope=QueryScope.LIST, target=target, filter=query_filter)
    assert command.intent == "HassStateQuery"
    assert command.scope is QueryScope.LIST
    assert command.target is target
    assert command.filter is query_filter


def test_query_result_defaults_to_empty_entities_and_no_command():
    result = QueryResult(status=QueryResultStatus.EMPTY)
    assert result.entities == ()
    assert result.command is None


def test_query_result_can_carry_matched_entities_and_its_originating_command():
    entity = EntitySnapshot("cover.fenster", "Fenster", "cover", "open")
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="cover"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert result.entities == (entity,)
    assert result.command is command


def test_query_result_status_members_cover_the_four_documented_cases():
    assert {s.name for s in QueryResultStatus} == {"MATCHED", "EMPTY", "TARGET_NOT_FOUND", "AMBIGUOUS"}


def test_query_scope_members_cover_the_four_documented_cardinalities():
    assert {s.name for s in QueryScope} == {"SINGLE", "LIST", "COUNT", "EXISTS"}


def test_dataclasses_are_frozen():
    target = QueryTarget(domain="light")
    try:
        target.domain = "switch"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("QueryTarget must be frozen")
