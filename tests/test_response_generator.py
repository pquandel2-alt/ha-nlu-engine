"""HomeIntent v4.2.1 plan, Phase 6 (Section 12): nlu/response_generator.py's
ResponseGenerator - QueryResult -> German text. Hass-free (mirrors
tests/test_query_executor.py's style).

WorldModelQuery wave: ResponseGenerator is now the live response source for
StateQueryParser's intents (engine.py::_build_match_result calls respond()
whenever frame.parameters["query_result"] is set) - the wording here is no
longer required to mirror service_call.py's old lambdas, it is the primary
source.
"""

from __future__ import annotations

from ha_nlu.areas import AreaSnapshot
from ha_nlu.devices import DeviceSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.query_command import (
    QueryCommand,
    QueryFilter,
    QueryResult,
    QueryResultStatus,
    QueryScope,
    QueryTarget,
    QueryTargetKind,
)
from ha_nlu.nlu.response_generator import ResponseGenerator
from ha_nlu.nlu.semantic_state import SemanticState

respond = ResponseGenerator().respond


def _window(entity_id: str, name: str, state: str) -> EntitySnapshot:
    return EntitySnapshot(entity_id, name, "binary_sensor", state, device_class="window")


def _list_command(scope: QueryScope, device_class: str = "window") -> QueryCommand:
    return QueryCommand(
        intent="HassStateQuery",
        scope=scope,
        target=QueryTarget(domain="binary_sensor", device_class=device_class),
        filter=QueryFilter(state=SemanticState.OPEN),
    )


# --- TARGET_NOT_FOUND / AMBIGUOUS (no equivalent in today's pipeline) ----


def test_target_not_found_gets_its_own_text():
    command = _list_command(QueryScope.LIST)
    result = QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
    assert respond(result) == "Ich konnte keine passenden Fenster finden."


def test_ambiguous_gets_its_own_text():
    command = _list_command(QueryScope.LIST)
    a = _window("binary_sensor.a", "A", "on")
    b = _window("binary_sensor.b", "B", "off")
    result = QueryResult(status=QueryResultStatus.AMBIGUOUS, entities=(a, b), command=command)
    assert respond(result) == "Ich habe mehrere passende Fenster gefunden."


# --- LIST -----------------------------------------------------------------


def test_list_empty_is_a_normal_sentence_not_an_error():
    command = _list_command(QueryScope.LIST)
    result = QueryResult(status=QueryResultStatus.EMPTY, entities=(), command=command)
    assert respond(result) == "Es sind keine Fenster geöffnet."


def test_list_single_match_names_the_entity():
    command = _list_command(QueryScope.LIST)
    entity = _window("binary_sensor.a", "Küchenfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Küchenfenster ist geöffnet."


def test_list_multiple_matches_lists_names():
    command = _list_command(QueryScope.LIST)
    a = _window("binary_sensor.a", "Küchenfenster", "on")
    b = _window("binary_sensor.b", "Badfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(a, b), command=command)
    assert respond(result) == "Küchenfenster und Badfenster sind geöffnet."


# --- COUNT ------------------------------------------------------------------


def test_count_single_match_still_names_the_entity():
    command = _list_command(QueryScope.COUNT)
    entity = _window("binary_sensor.a", "Küchenfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Küchenfenster ist geöffnet."


def test_count_multiple_matches_speaks_a_count_not_names():
    command = _list_command(QueryScope.COUNT)
    a = _window("binary_sensor.a", "Küchenfenster", "on")
    b = _window("binary_sensor.b", "Badfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(a, b), command=command)
    assert respond(result) == "2 Fenster sind geöffnet."


# --- EXISTS -------------------------------------------------------------


def test_exists_empty_is_a_clean_no():
    command = QueryCommand(
        intent="HassExistsQuery",
        scope=QueryScope.EXISTS,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = QueryResult(status=QueryResultStatus.EMPTY, entities=(), command=command)
    assert respond(result) == "Nein, es gibt keine Fenster."


def test_exists_with_matches_speaks_a_count():
    command = QueryCommand(
        intent="HassExistsQuery",
        scope=QueryScope.EXISTS,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=None),
    )
    a = _window("binary_sensor.a", "Küchenfenster", "on")
    b = _window("binary_sensor.b", "Badfenster", "off")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(a, b), command=command)
    assert respond(result) == "Ja, es gibt 2 Fenster."


# --- SINGLE (HassCheckState) ----------------------------------------------


def test_single_matched_entity_currently_satisfying_filter_says_ja():
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor", entity_id="binary_sensor.a"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    entity = _window("binary_sensor.a", "Küchenfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Ja, Küchenfenster ist geöffnet."


def test_single_matched_entity_not_currently_satisfying_filter_says_nein():
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor", entity_id="binary_sensor.a"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    entity = _window("binary_sensor.a", "Küchenfenster", "off")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Nein, Küchenfenster ist nicht geöffnet."


# --- device_class-less domain falls back to the generic domain noun ------


def test_list_falls_back_to_domain_plural_noun_when_no_device_class():
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="light"),
        filter=QueryFilter(state=SemanticState.ON),
    )
    result = QueryResult(status=QueryResultStatus.EMPTY, entities=(), command=command)
    assert respond(result) == "Es sind keine Lichter eingeschaltet."


# --- DEVICE scope (HassDeviceQuery, "welche Geräte sind im Büro?") -------


_BUERO = AreaSnapshot(area_id="area.buero", name="Büro")


def _device_command() -> QueryCommand:
    return QueryCommand(
        intent="HassDeviceQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(kind=QueryTargetKind.DEVICE, area=_BUERO),
        filter=QueryFilter(),
    )


def test_device_list_empty_names_the_area():
    command = _device_command()
    result = QueryResult(status=QueryResultStatus.EMPTY, devices=(), command=command)
    assert respond(result) == "Im Büro sind keine Geräte bekannt."


def test_device_list_single_device():
    command = _device_command()
    device = DeviceSnapshot(device_id="device.a", name="Schreibtischlampe")
    result = QueryResult(status=QueryResultStatus.MATCHED, devices=(device,), command=command)
    assert respond(result) == "Schreibtischlampe ist im Büro."


def test_device_list_multiple_devices():
    command = _device_command()
    a = DeviceSnapshot(device_id="device.a", name="Schreibtischlampe")
    b = DeviceSnapshot(device_id="device.b", name="Drucker")
    result = QueryResult(status=QueryResultStatus.MATCHED, devices=(a, b), command=command)
    assert respond(result) == "Schreibtischlampe und Drucker sind im Büro."


# --- stateless listing (HassStateQuery without a {state} slot) -----------


def test_list_no_state_empty_without_area():
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="light"),
        filter=QueryFilter(state=None),
    )
    result = QueryResult(status=QueryResultStatus.EMPTY, entities=(), command=command)
    assert respond(result) == "Keine Lichter gefunden."


def test_list_no_state_single_match_with_area():
    wohnzimmer = AreaSnapshot(area_id="area.wohnzimmer", name="Wohnzimmer")
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="light", area=wohnzimmer),
        filter=QueryFilter(state=None),
    )
    entity = EntitySnapshot("light.a", "Stehlampe", "light", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Stehlampe ist im Wohnzimmer."


def test_list_no_state_multiple_matches_with_area():
    wohnzimmer = AreaSnapshot(area_id="area.wohnzimmer", name="Wohnzimmer")
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="light", area=wohnzimmer),
        filter=QueryFilter(state=None),
    )
    a = EntitySnapshot("light.a", "Stehlampe", "light", "on")
    b = EntitySnapshot("light.b", "Deckenlampe", "light", "off")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(a, b), command=command)
    assert respond(result) == "Stehlampe und Deckenlampe sind im Wohnzimmer."
