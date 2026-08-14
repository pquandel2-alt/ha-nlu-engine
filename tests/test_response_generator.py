"""HomeIntent v4.2.1 plan, Phase 6 (Section 12): nlu/response_generator.py's
ResponseGenerator - QueryResult -> German text. Hass-free (mirrors
tests/test_query_executor.py's style). Not yet wired into engine.py/
parsers.py (Phase 7 does that) - exercised directly here.

Wording pinned to match service_call.py's existing _speak_state_query/
_speak_check_state/_speak_exists lambdas exactly - these are the same
sentences today's production pipeline already speaks.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.query_command import QueryCommand, QueryFilter, QueryResult, QueryResultStatus, QueryScope, QueryTarget
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
    result = QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND)
    assert respond(result) == "Das habe ich nicht gefunden."


def test_ambiguous_gets_its_own_text():
    a = _window("binary_sensor.a", "A", "on")
    b = _window("binary_sensor.b", "B", "off")
    result = QueryResult(status=QueryResultStatus.AMBIGUOUS, entities=(a, b))
    assert respond(result) == "Das ist nicht eindeutig - mehrere Geräte passen darauf."


# --- LIST -----------------------------------------------------------------


def test_list_empty_is_a_normal_sentence_not_an_error():
    command = _list_command(QueryScope.LIST)
    result = QueryResult(status=QueryResultStatus.EMPTY, entities=(), command=command)
    assert respond(result) == "Keine Fenster sind offen."


def test_list_single_match_names_the_entity():
    command = _list_command(QueryScope.LIST)
    entity = _window("binary_sensor.a", "Küchenfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Küchenfenster ist offen."


def test_list_multiple_matches_lists_names():
    command = _list_command(QueryScope.LIST)
    a = _window("binary_sensor.a", "Küchenfenster", "on")
    b = _window("binary_sensor.b", "Badfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(a, b), command=command)
    assert respond(result) == "Küchenfenster, Badfenster sind offen."


# --- COUNT ------------------------------------------------------------------


def test_count_single_match_still_names_the_entity():
    command = _list_command(QueryScope.COUNT)
    entity = _window("binary_sensor.a", "Küchenfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Küchenfenster ist offen."


def test_count_multiple_matches_speaks_a_count_not_names():
    command = _list_command(QueryScope.COUNT)
    a = _window("binary_sensor.a", "Küchenfenster", "on")
    b = _window("binary_sensor.b", "Badfenster", "on")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(a, b), command=command)
    assert respond(result) == "2 Fenster sind offen."


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
    assert respond(result) == "Ja, Küchenfenster ist offen."


def test_single_matched_entity_not_currently_satisfying_filter_says_nein():
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor", entity_id="binary_sensor.a"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    entity = _window("binary_sensor.a", "Küchenfenster", "off")
    result = QueryResult(status=QueryResultStatus.MATCHED, entities=(entity,), command=command)
    assert respond(result) == "Nein, Küchenfenster ist nicht offen."


# --- device_class-less domain falls back to the generic domain noun ------


def test_list_falls_back_to_domain_plural_noun_when_no_device_class():
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="light"),
        filter=QueryFilter(state=SemanticState.ON),
    )
    result = QueryResult(status=QueryResultStatus.EMPTY, entities=(), command=command)
    assert respond(result) == "Keine Lichter sind eingeschaltet."
