"""Typed query-delta compiler for deterministic conversational follow-ups."""

from __future__ import annotations

from dataclasses import replace

from ..areas import AreaSnapshot
from ..entities import EntitySnapshot
from ..world_model import WorldModel
from .constraint_resolver import Constraints, resolve_candidates
from .frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from .parser import ParseResult
from .primitives import SemanticAction
from .query_command import (
    QueryCommand,
    QueryFilter,
    QueryResultStatus,
    QueryScope,
    QueryTarget,
    QueryTargetKind,
)
from .query_executor import QueryExecutor
from .semantic_lexicon import SemanticKind, analyse_semantics
from .semantic_location import resolve_semantic_location
from .semantic_state import SemanticState


_EXECUTOR = QueryExecutor()


def _location(
    text: str, entities: list[EntitySnapshot], world_model: WorldModel | None
) -> tuple[str, str | None, str | None] | None:
    return resolve_semantic_location(text, entities, world_model)


def _state_delta(text: str) -> SemanticState | None:
    values = {
        span.value
        for span in analyse_semantics(text).matching(SemanticKind.STATE)
        if isinstance(span.value, SemanticState)
        and span.text.casefold() not in {"ein", "eine"}
    }
    return next(iter(values)) if len(values) == 1 else None


def _class_delta(text: str) -> tuple[str, str | None] | None:
    values = {
        value
        for value in analyse_semantics(text).values(SemanticKind.DEVICE_CLASS)
        if isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and (value[1] is None or isinstance(value[1], str))
    }
    return next(iter(values)) if len(values) == 1 else None


def _candidates(
    entities: list[EntitySnapshot],
    world_model: WorldModel | None,
    *,
    domain: str,
    device_class: str | None,
    area_id: str | None,
    floor_id: str | None,
) -> list[EntitySnapshot]:
    if world_model is not None:
        return list(
            world_model.select_entities(
                domain=domain,
                device_class=device_class,
                area_id=area_id,
                floor_id=floor_id,
            )
        )
    return resolve_candidates(
        entities,
        Constraints(
            domain=domain,
            device_class=device_class,
            area_id=area_id,
            floor_id=floor_id,
        ),
    )


def compile_query_followup(
    text: str,
    entities: list[EntitySnapshot],
    last_entities: tuple[EntitySnapshot, ...],
    previous: QueryCommand | None,
    world_model: WorldModel | None = None,
) -> ParseResult | None:
    """Apply explicit location/class/state deltas to a prior typed query."""
    location = _location(text, entities, world_model)
    state = _state_delta(text)
    target_delta = _class_delta(text)

    if previous is None:
        if location is None or not last_entities:
            return None
        reference = last_entities[0]
        device_class = None if reference.domain == "light" else reference.device_class
        if reference.domain != "light" and device_class is None:
            return None
        candidates = _candidates(
            entities,
            world_model,
            domain=reference.domain,
            device_class=device_class,
            area_id=location[1],
            floor_id=location[2],
        )
        if len(candidates) != 1:
            return None
        entity = candidates[0]
        return ParseResult(
            frame=SemanticFrame(
                intent="HassGetState",
                target=TargetReference(
                    location[0], entity.entity_id, entity.domain, entity.device_class
                ),
                area=(
                    AreaReference(location[0], location[1], location[0])
                    if location[1] is not None
                    else None
                ),
                source_text=text,
                action=SemanticAction.QUERY,
            ),
            resolved_entities=[entity],
        )

    if location is None and state is None and target_delta is None:
        return None
    if previous.target.kind is QueryTargetKind.DEVICE:
        if location is None or location[1] is None or location[2] is not None:
            return None
        area = AreaSnapshot(location[1], location[0])
        command = replace(previous, target=replace(previous.target, area=area))
        result = _EXECUTOR.execute(command, [], world_model)
        return ParseResult(
            frame=SemanticFrame(
                intent=command.intent,
                target=None,
                area=AreaReference(location[0], location[1], location[0]),
                quantifier=Quantifier("all"),
                parameters={"query_command": command, "query_result": result},
                source_text=text,
                action=SemanticAction.QUERY,
            ),
            resolved_entities=[],
        )

    domain = target_delta[0] if target_delta is not None else previous.target.domain
    device_class = (
        target_delta[1] if target_delta is not None else previous.target.device_class
    )
    if domain is None:
        return None
    if location is not None:
        area_id, floor_id, location_name = location[1], location[2], location[0]
    elif previous.target.area is not None:
        area_id, floor_id = previous.target.area.area_id, None
        location_name = previous.target.area.name
    else:
        area_id, floor_id = None, previous.target.floor_id
        location_name = None
    candidates = _candidates(
        entities,
        world_model,
        domain=domain,
        device_class=device_class,
        area_id=area_id,
        floor_id=floor_id,
    )
    entity_id = previous.target.entity_id if location is None and target_delta is None else None
    if previous.scope is QueryScope.SINGLE:
        if entity_id is None:
            if len(candidates) != 1:
                return None
            entity_id = candidates[0].entity_id
        candidates = [item for item in candidates if item.entity_id == entity_id]
    area = (
        AreaSnapshot(area_id, location_name)
        if area_id is not None and location_name is not None
        else None
    )
    command = QueryCommand(
        intent=previous.intent,
        scope=previous.scope,
        target=QueryTarget(
            domain=domain,
            device_class=device_class,
            area=area,
            floor_id=floor_id,
            entity_id=entity_id,
        ),
        filter=QueryFilter(state=state or previous.filter.state),
    )
    result = _EXECUTOR.execute(command, candidates)
    if result.status in {
        QueryResultStatus.TARGET_NOT_FOUND,
        QueryResultStatus.AMBIGUOUS,
    }:
        return None
    return ParseResult(
        frame=SemanticFrame(
            intent=command.intent,
            target=TargetReference(
                location_name or text,
                entity_id,
                domain,
                device_class,
            ),
            area=(
                AreaReference(location_name, area_id, location_name)
                if area_id is not None and location_name is not None
                else None
            ),
            quantifier=(
                None if command.scope is QueryScope.SINGLE else Quantifier("all")
            ),
            parameters={
                "semantic_state": command.filter.state,
                "count_only": command.scope is QueryScope.COUNT,
                "device_class": device_class,
                "domain": domain,
                "query_command": command,
                "query_result": result,
            },
            source_text=text,
            action=SemanticAction.QUERY,
        ),
        resolved_entities=list(result.entities),
    )
