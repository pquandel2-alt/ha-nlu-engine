"""HomeIntent v4.2.1 plan, Phase 5 (Section 12): nlu/query_executor.py's
QueryExecutor - QueryCommand -> QueryResult. Hass-free, no engine involved
(mirrors tests/test_semantic_state.py's style). Not yet wired into
engine.py/parsers.py (Phase 7 does that) - exercised directly here.
"""

from __future__ import annotations

from ha_nlu.automation_summary import AutomationSummary
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.query_command import (
    QueryCommand,
    QueryFilter,
    QueryResultStatus,
    QueryScope,
    QueryTarget,
    QueryTargetKind,
)
from ha_nlu.nlu.query_executor import QueryExecutor
from ha_nlu.nlu.semantic_state import SemanticState

executor = QueryExecutor()


def _window(entity_id: str, state: str) -> EntitySnapshot:
    return EntitySnapshot(entity_id, entity_id, "binary_sensor", state, device_class="window")


# --- LIST/COUNT/EXISTS (plural) -----------------------------------------


def test_list_filters_candidates_by_requested_state():
    open_window = _window("binary_sensor.a", "on")
    closed_window = _window("binary_sensor.b", "off")
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [open_window, closed_window])
    assert result.status is QueryResultStatus.MATCHED
    assert result.entities == (open_window,)
    assert result.command is command


def test_list_with_zero_matches_is_empty_not_an_error():
    closed_window = _window("binary_sensor.b", "off")
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [closed_window])
    assert result.status is QueryResultStatus.EMPTY
    assert result.entities == ()


def test_list_with_zero_candidates_at_all_is_empty():
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [])
    assert result.status is QueryResultStatus.EMPTY


def test_count_scope_applies_the_same_filter_as_list():
    open_window = _window("binary_sensor.a", "on")
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.COUNT,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [open_window])
    assert result.status is QueryResultStatus.MATCHED
    assert result.entities == (open_window,)


def test_exists_with_no_state_filter_matches_every_candidate():
    a = _window("binary_sensor.a", "on")
    b = _window("binary_sensor.b", "off")
    command = QueryCommand(
        intent="HassExistsQuery",
        scope=QueryScope.EXISTS,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=None),
    )
    result = executor.execute(command, [a, b])
    assert result.status is QueryResultStatus.MATCHED
    assert result.entities == (a, b)


def test_unknown_semantic_state_never_matches_a_requested_filter():
    # matches_semantic_state's own "never guess" rule (Regel 4) must still
    # hold when reached through the executor.
    unavailable = _window("binary_sensor.a", "unavailable")
    command = QueryCommand(
        intent="HassStateQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain="binary_sensor", device_class="window"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [unavailable])
    assert result.status is QueryResultStatus.EMPTY


# --- SINGLE (HassCheckState) ---------------------------------------------


def test_single_with_pre_resolved_entity_id_matches_regardless_of_current_state():
    closed_window = _window("binary_sensor.a", "off")
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor", entity_id="binary_sensor.a"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [closed_window])
    # The answer ("Nein, ... ist nicht offen.") is a ResponseGenerator
    # concern (Phase 6) - the executor still reports MATCHED, since the
    # named entity itself was found.
    assert result.status is QueryResultStatus.MATCHED
    assert result.entities == (closed_window,)


def test_single_with_pre_resolved_entity_id_not_among_candidates_is_target_not_found():
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor", entity_id="binary_sensor.missing"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [_window("binary_sensor.a", "on")])
    assert result.status is QueryResultStatus.TARGET_NOT_FOUND
    assert result.entities == ()


def test_single_without_pre_resolved_entity_id_and_no_candidates_is_target_not_found():
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [])
    assert result.status is QueryResultStatus.TARGET_NOT_FOUND


def test_single_without_pre_resolved_entity_id_and_multiple_candidates_is_ambiguous():
    a = _window("binary_sensor.a", "on")
    b = _window("binary_sensor.b", "off")
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [a, b])
    assert result.status is QueryResultStatus.AMBIGUOUS
    assert result.entities == (a, b)


def test_single_without_pre_resolved_entity_id_and_exactly_one_candidate_matches():
    a = _window("binary_sensor.a", "on")
    command = QueryCommand(
        intent="HassCheckState",
        scope=QueryScope.SINGLE,
        target=QueryTarget(domain="binary_sensor"),
        filter=QueryFilter(state=SemanticState.OPEN),
    )
    result = executor.execute(command, [a])
    assert result.status is QueryResultStatus.MATCHED
    assert result.entities == (a,)


# --- AUTOMATION (V5.29, "Automation Query") --------------------------------


KUECHE_AUTOMATION = AutomationSummary(
    automation_id="a1",
    alias="Küchenlicht-Automation",
    referenced_entity_ids=frozenset({"light.kueche_licht"}),
)
BUERO_AUTOMATION = AutomationSummary(
    automation_id="a2",
    alias="Büro-Automation",
    referenced_entity_ids=frozenset({"switch.buero_steckdose"}),
)


def _automation_command(entity_id: str | None) -> QueryCommand:
    return QueryCommand(
        intent="HassAutomationQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(kind=QueryTargetKind.AUTOMATION, entity_id=entity_id),
        filter=QueryFilter(),
    )


def test_automation_query_with_no_entity_id_lists_every_automation():
    command = _automation_command(None)
    result = executor.execute(command, [], automations=(KUECHE_AUTOMATION, BUERO_AUTOMATION))
    assert result.status is QueryResultStatus.MATCHED
    assert result.automations == (KUECHE_AUTOMATION, BUERO_AUTOMATION)


def test_automation_query_with_no_automations_at_all_is_empty():
    command = _automation_command(None)
    result = executor.execute(command, [], automations=())
    assert result.status is QueryResultStatus.EMPTY
    assert result.automations == ()


def test_automation_query_filters_by_referenced_entity_id():
    command = _automation_command("light.kueche_licht")
    result = executor.execute(
        command, [_window("light.kueche_licht", "on")], automations=(KUECHE_AUTOMATION, BUERO_AUTOMATION)
    )
    assert result.status is QueryResultStatus.MATCHED
    assert result.automations == (KUECHE_AUTOMATION,)


def test_automation_query_with_no_matching_automation_is_empty():
    command = _automation_command("light.schlafzimmer")
    result = executor.execute(
        command, [_window("light.schlafzimmer", "on")], automations=(KUECHE_AUTOMATION, BUERO_AUTOMATION)
    )
    assert result.status is QueryResultStatus.EMPTY
    assert result.automations == ()
