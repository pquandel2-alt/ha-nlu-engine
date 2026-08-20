"""QueryExecutor (HomeIntent v4.2.1 plan, Section 12/Phase 5): the second
stage of the Query pipeline - ``QueryCommand`` -> ``QueryResult``.

Read-only by construction: this module has no Home Assistant import and
never calls (nor could call) ``hass.services.async_call()`` - Regel 3/
Sections 16+46 ("Queries never execute a service call"). It only filters an
already-resolved candidate list by live entity state
(``matches_semantic_state``, Regel 5 - never cached) and classifies the
outcome into a ``QueryResultStatus``.

Candidate resolution itself (name/area/domain/device_class -> a list of
``EntitySnapshot``) stays where it already lives (``areas.py``/
``entities.py``, Regel 6 - no parallel search system) and is the caller's
job, same division of labor ``StateQueryParser`` already follows internally
today. Phase 7 wires a caller onto this class non-destructively; until then
nothing in ``engine.py``/``parsers.py`` constructs a ``QueryExecutor``.
"""

from __future__ import annotations

from ..automation_summary import AutomationSummary
from ..entities import EntitySnapshot
from ..world_model import WorldModel
from .query_command import QueryCommand, QueryResult, QueryResultStatus, QueryScope, QueryTargetKind
from .semantic_state import matches_semantic_state


class QueryExecutor:
    """Stateless - one shared instance is fine, same as ``NluEngine``'s other
    parser-adjacent helpers. ``execute()`` takes the caller's already-scoped
    candidate list (domain/device_class/area already applied) and applies
    only the state filter plus cardinality classification.
    """

    def execute(
        self,
        command: QueryCommand,
        candidates: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        automations: tuple[AutomationSummary, ...] = (),
    ) -> QueryResult:
        if command.target.kind is QueryTargetKind.DEVICE:
            return self._execute_device(command, world_model)
        if command.target.kind is QueryTargetKind.AUTOMATION:
            return self._execute_automation(command, candidates, automations)
        if command.scope is QueryScope.SINGLE:
            return self._execute_single(command, candidates)
        return self._execute_plural(command, candidates)

    @staticmethod
    def _execute_automation(
        command: QueryCommand,
        candidates: list[EntitySnapshot],
        automations: tuple[AutomationSummary, ...],
    ) -> QueryResult:
        """AUTOMATION-scope queries (HassAutomationQuery/HassAutomationWhyQuery,
        V5.29). No ``target.entity_id`` ("welche Automationen gibt es?")
        lists every automation the caller read; a resolved ``entity_id``
        ("was schaltet X?"/"warum geht X an?") narrows to automations whose
        ``referenced_entity_ids`` mention it - see ``AutomationSummary``'s
        own docstring for why that's a deliberately shallow "mentions X
        somewhere", not a re-derivation of actual trigger/action causation.

        ``candidates`` carries the already-resolved target entity (same
        calling shape ``_execute_single`` uses for its own ``entity_id``
        membership check) purely so the response can name it - membership
        itself is decided by ``entity_id in referenced_entity_ids`` alone.
        Zero matches is EMPTY, not an error - same "0 is a normal answer"
        precedent ``_execute_plural`` already establishes.
        """
        entity_id = command.target.entity_id
        if entity_id is None:
            matched = automations
        else:
            matched = tuple(a for a in automations if entity_id in a.referenced_entity_ids)
        status = QueryResultStatus.MATCHED if matched else QueryResultStatus.EMPTY
        entity = candidates[0] if entity_id is not None and candidates else None
        return QueryResult(
            status=status,
            entities=(entity,) if entity is not None else (),
            automations=tuple(matched),
            command=command,
        )

    @staticmethod
    def _execute_device(command: QueryCommand, world_model: WorldModel | None) -> QueryResult:
        """DEVICE-scope queries (HassDeviceQuery, "welche Geräte sind im
        Büro?") answer from the WorldModel's device list, not an entity/state
        filter - no world_model or no resolved area means no answer, never a
        crash or an invented "all devices" fallback (Regel: niemals raten).
        """
        if world_model is None or command.target.area is None:
            return QueryResult(status=QueryResultStatus.EMPTY, command=command)
        devices = world_model.devices_in_area(command.target.area.area_id)
        if command.filter.state is not None:
            state = command.filter.state
            devices = tuple(
                d
                for d in devices
                if any(
                    matches_semantic_state(e, state)
                    for e in world_model.entities_for_device(d.device_id)
                )
            )
        status = QueryResultStatus.MATCHED if devices else QueryResultStatus.EMPTY
        return QueryResult(status=status, devices=tuple(devices), command=command)

    @staticmethod
    def _execute_single(command: QueryCommand, candidates: list[EntitySnapshot]) -> QueryResult:
        """SINGLE queries (HassCheckState) always resolve to exactly one
        entity - whether or not its *current* state satisfies the requested
        filter is the answer itself (``Nein, ... ist nicht offen.`` is a
        MATCHED result, not EMPTY), so no state filtering happens here.

        Two calling shapes are supported: the target already carries a
        resolved ``entity_id`` (today's ``StateQueryParser`` - it already
        did the ambiguity check itself via ``resolve_entity_scored``, Regel
        4), or it doesn't, in which case this method does that cardinality
        check itself directly against ``candidates`` - lets a future caller
        skip duplicating that logic and gives ``AMBIGUOUS``/``TARGET_NOT_FOUND``
        real, independently testable code paths.
        """
        if command.target.entity_id is not None:
            match = next(
                (e for e in candidates if e.entity_id == command.target.entity_id), None
            )
            if match is None:
                return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
            return QueryResult(status=QueryResultStatus.MATCHED, entities=(match,), command=command)

        if not candidates:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        if len(candidates) > 1:
            return QueryResult(
                status=QueryResultStatus.AMBIGUOUS, entities=tuple(candidates), command=command
            )
        return QueryResult(status=QueryResultStatus.MATCHED, entities=(candidates[0],), command=command)

    @staticmethod
    def _execute_plural(command: QueryCommand, candidates: list[EntitySnapshot]) -> QueryResult:
        """LIST/COUNT/EXISTS all share one filtering rule: keep candidates
        whose live state matches the requested filter (or every candidate,
        for EXISTS's bare-existence form with no {state}/{state_adj} word -
        ``filter.state is None``). COUNT differs from LIST only in how
        ``ResponseGenerator`` (Phase 6) phrases the same matched set, not in
        which entities match - so both take this one branch.

        Zero matches is EMPTY, not an error - HomeIntent v4.2.1 Section 19,
        "Keine Fenster sind offen." is a normal answer.
        """
        state = command.filter.state
        matched = (
            candidates
            if state is None
            else [e for e in candidates if matches_semantic_state(e, state)]
        )
        status = QueryResultStatus.MATCHED if matched else QueryResultStatus.EMPTY
        return QueryResult(status=status, entities=tuple(matched), command=command)
