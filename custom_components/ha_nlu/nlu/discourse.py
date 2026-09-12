"""Deterministic multi-referent discourse memory and salience ranking.

The module stores stable entity identifiers plus grounded registry metadata.
It does not resolve entity names, call services, or infer unknown relations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Iterable

from ..entities import EntitySnapshot, normalize_for_compare
from .german_morphology import GrammaticalGender, entity_name_gender
from .primitives import SemanticProperty

if TYPE_CHECKING:
    from .query_command import QueryCommand, QueryResult
    from .semantic_graph import SemanticGraph


class DiscourseRole(Enum):
    SUBJECT = auto()
    OBJECT = auto()
    QUERY_RESULT = auto()
    ACTION_TARGET = auto()
    EXCLUDED = auto()


class ReferenceStatus(Enum):
    RESOLVED = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class DiscourseReferent:
    entity_id: str
    semantic_type: str
    grammatical_gender: GrammaticalGender | None
    grammatical_number: str
    area_id: str | None
    floor_id: str | None
    last_mentioned_turn: int
    salience: int
    role: DiscourseRole
    active_property: SemanticProperty | None = None
    active_state: str | None = None
    active_action: str | None = None


@dataclass(frozen=True)
class DiscourseGroup:
    group_id: str
    semantic_type: str
    member_ids: tuple[str, ...]
    origin_query: QueryCommand
    graph_fragment: SemanticGraph | None
    filters: tuple[str, ...]
    relation_provenance: tuple[str, ...]
    turn: int
    salience: int


@dataclass(frozen=True)
class DiscourseState:
    turn_index: int = 0
    referents: tuple[DiscourseReferent, ...] = ()
    focus_entity_ids: tuple[str, ...] = ()
    active_area_ids: tuple[str, ...] = ()
    active_floor_ids: tuple[str, ...] = ()
    current_graph: SemanticGraph | None = None
    groups: tuple[DiscourseGroup, ...] = ()


@dataclass(frozen=True)
class ReferenceResolution:
    status: ReferenceStatus
    entities: tuple[EntitySnapshot, ...] = ()
    ranked: tuple[tuple[str, int], ...] = ()
    margin: int | None = None


_PLURAL_REFERENCES = frozenset({"die", "diese", "jene", "dieselben", "anderen"})
_MASCULINE_REFERENCES = frozenset({"er", "der", "dieser", "jener"})
_FEMININE_REFERENCES = frozenset({"sie", "diese", "jene"})
_NEUTER_REFERENCES = frozenset({"es", "das", "dies", "dieses", "jenes"})


def remember_entities(
    previous: DiscourseState | None,
    entities: Iterable[EntitySnapshot],
    *,
    role: DiscourseRole,
    active_property: SemanticProperty | None = None,
    active_action: str | None = None,
    semantic_graph: SemanticGraph | None = None,
    max_referents: int = 32,
) -> DiscourseState:
    """Return a bounded state with this turn's grounded entities promoted."""
    prior = previous or DiscourseState()
    turn = prior.turn_index + 1
    promoted = {entity.entity_id: entity for entity in entities}
    referents = [
        DiscourseReferent(
            entity_id=entity.entity_id,
            semantic_type=entity.domain,
            grammatical_gender=entity_name_gender(entity.friendly_name),
            grammatical_number="singular",
            area_id=entity.area_id,
            floor_id=entity.floor_id,
            last_mentioned_turn=turn,
            salience=100,
            role=role,
            active_property=active_property,
            active_state=entity.state,
            active_action=active_action,
        )
        for entity in promoted.values()
    ]
    referents.extend(
        DiscourseReferent(
            **{
                **item.__dict__,
                "salience": max(0, item.salience - 20),
            }
        )
        for item in prior.referents
        if item.entity_id not in promoted and item.salience > 20
    )
    ordered = sorted(
        referents,
        key=lambda item: (-item.salience, -item.last_mentioned_turn, item.entity_id),
    )[:max_referents]
    focus_entities = tuple(sorted(promoted))
    active_areas = tuple(sorted({
        entity.area_id for entity in promoted.values() if entity.area_id is not None
    }))
    active_floors = tuple(sorted({
        entity.floor_id for entity in promoted.values() if entity.floor_id is not None
    }))
    return DiscourseState(
        turn_index=turn,
        referents=tuple(ordered),
        focus_entity_ids=focus_entities,
        active_area_ids=active_areas,
        active_floor_ids=active_floors,
        current_graph=semantic_graph,
        groups=prior.groups,
    )


def remember_query_group(
    previous: DiscourseState | None,
    result: QueryResult,
    *,
    semantic_graph: SemanticGraph | None = None,
    max_groups: int = 8,
) -> DiscourseState:
    """Remember typed result membership, never a future execution target."""
    prior = previous or DiscourseState()
    if result.command is None:
        return prior
    turn = prior.turn_index or 1
    member_types = {
        member_id.split(":", 1)[0]
        for member_id in result.member_ids
        if ":" in member_id
    }
    semantic_type = (
        next(iter(member_types))
        if len(member_types) == 1
        else result.command.target.kind.name.lower()
    )
    relation_ids = tuple(sorted({
        relation_id
        for step in (result.trace.steps if result.trace is not None else ())
        for relation_id in step.relation_ids
    }))
    digest = hashlib.sha256(
        (f"{turn}\0{semantic_type}\0" + "\0".join(result.member_ids)).encode()
    ).hexdigest()[:16]
    group = DiscourseGroup(
        group_id=f"group:{digest}",
        semantic_type=semantic_type,
        member_ids=result.member_ids,
        origin_query=result.command,
        graph_fragment=semantic_graph,
        filters=tuple(
            step.operation for step in (result.trace.steps if result.trace is not None else ())
            if step.operation.startswith("filter")
        ),
        relation_provenance=relation_ids,
        turn=turn,
        salience=100,
    )
    decayed = tuple(
        DiscourseGroup(**{**item.__dict__, "salience": max(0, item.salience - 20)})
        for item in prior.groups
        if item.salience > 20
    )
    return DiscourseState(
        turn_index=turn,
        referents=prior.referents,
        focus_entity_ids=prior.focus_entity_ids,
        active_area_ids=prior.active_area_ids,
        active_floor_ids=prior.active_floor_ids,
        current_graph=semantic_graph or prior.current_graph,
        groups=(group, *decayed)[:max_groups],
    )


def current_discourse_group(
    state: DiscourseState | None, *, semantic_type: str | None = None
) -> DiscourseGroup | None:
    """Return the most salient compatible typed group deterministically."""
    if state is None:
        return None
    compatible = tuple(
        group for group in state.groups
        if semantic_type is None or group.semantic_type == semantic_type
    )
    return min(
        compatible,
        key=lambda group: (-group.salience, -group.turn, group.group_id),
        default=None,
    )


def _reference_features(text: str) -> tuple[str | None, bool, bool]:
    words = tuple(normalize_for_compare(text).replace(".", " ").split())
    gender: str | None = None
    if any(word in _MASCULINE_REFERENCES for word in words):
        gender = GrammaticalGender.MASCULINE.value
    if any(word in _NEUTER_REFERENCES for word in words):
        gender = GrammaticalGender.NEUTER.value
    # ``sie``/``die`` are ambiguous between feminine singular and plural;
    # explicit plural expressions are required before filtering by number.
    explicit_plural = any(word in {"anderen", "dieselben"} for word in words)
    if not explicit_plural and any(word in _FEMININE_REFERENCES for word in words):
        gender = GrammaticalGender.FEMININE.value
    wants_location = any(word in {"dort", "hier", "da"} for word in words)
    return gender, explicit_plural, wants_location


def resolve_reference(
    text: str,
    state: DiscourseState | None,
    live_entities: Iterable[EntitySnapshot],
    *,
    domain: str | None = None,
    area_id: str | None = None,
    floor_id: str | None = None,
    property: SemanticProperty | None = None,
    ambiguity_margin: int = 8,
) -> ReferenceResolution:
    """Rank grounded referents; tied singular references require clarification."""
    if state is None or not state.referents:
        return ReferenceResolution(ReferenceStatus.NOT_FOUND)
    live = {entity.entity_id: entity for entity in live_entities}
    gender, plural, location_reference = _reference_features(text)
    words = frozenset(normalize_for_compare(text).replace(".", " ").split())
    # Feminine articles/pronouns are morphologically ambiguous. A currently
    # focused group supplies deterministic number evidence for ``die dort``
    # or ``mach die auch ...``; without such a group the singular ambiguity
    # handling below remains unchanged.
    if len(state.focus_entity_ids) > 1 and (
        words & {"die", "diese", "jene", "anderen", "dieselben"}
        or location_reference
    ):
        plural = True
        gender = None
    ranked: list[tuple[EntitySnapshot, int]] = []
    for referent in state.referents:
        entity = live.get(referent.entity_id)
        if entity is None:
            continue
        if domain is not None and referent.semantic_type != domain:
            continue
        if area_id is not None and referent.area_id != area_id:
            continue
        if floor_id is not None and referent.floor_id != floor_id:
            continue
        if gender is not None and (
            referent.grammatical_gender is None
            or referent.grammatical_gender.value != gender
        ):
            continue
        score = referent.salience
        score += max(0, 30 - (state.turn_index - referent.last_mentioned_turn) * 10)
        score += 20 if referent.role in {DiscourseRole.OBJECT, DiscourseRole.ACTION_TARGET} else 10
        if property is not None and referent.active_property is property:
            score += 12
        if location_reference and (referent.area_id is not None or referent.floor_id is not None):
            score += 8
        ranked.append((entity, score))
    ranked.sort(key=lambda item: (-item[1], item[0].entity_id))
    if not ranked:
        return ReferenceResolution(ReferenceStatus.NOT_FOUND)
    signature = tuple((entity.entity_id, score) for entity, score in ranked)
    if plural:
        top_score = ranked[0][1]
        selected = tuple(entity for entity, score in ranked if top_score - score <= ambiguity_margin)
        return ReferenceResolution(ReferenceStatus.RESOLVED, selected, signature)
    if len(ranked) > 1:
        margin = ranked[0][1] - ranked[1][1]
        if margin <= ambiguity_margin:
            return ReferenceResolution(
                ReferenceStatus.AMBIGUOUS,
                tuple(entity for entity, _ in ranked if ranked[0][1] - _ <= ambiguity_margin),
                signature,
                margin,
            )
    return ReferenceResolution(
        ReferenceStatus.RESOLVED, (ranked[0][0],), signature,
        ranked[0][1] - ranked[1][1] if len(ranked) > 1 else None,
    )
