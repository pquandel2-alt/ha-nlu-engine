"""Area name resolution: spoken/friendly room name -> area_id.

Phase 7 (v2 plan, "Area Resolver 2.0"): scored resolution mirroring
``entities.resolve_entity_scored`` (Phase 6) - the same tier structure
(exact, normalized exact, contains, reverse contains), adapted to areas
(no entity_id/domain/device_class dimension - those don't apply to rooms).
Built from the already-fetched entity list's area_id/area_name/area_aliases
(no separate registry access), so this stays hass-free like the rest of the
engine and needs no mocking to unit-test.

Area aliases (e.g. "draußen" configured as an alias for area "Garten" in
HA's own Area Registry) are the area-level counterpart to
``entities.py``'s entity aliases - same "user configured an alternative
spoken name" concept, just one level up. Populated live via
``hass_entities.py``'s ``_area_info()`` reading ``AreaEntry.aliases``, and
carried per-entity on ``EntitySnapshot.area_aliases`` (there is no
hass-free "all areas" list to read otherwise).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .entities import EntitySnapshot, normalize_for_compare


class AreaResolveStatus(Enum):
    OK = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class AreaResolveResult:
    status: AreaResolveStatus
    area_id: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class AreaSnapshot:
    area_id: str
    name: str
    aliases: tuple[str, ...] = ()


class AreaResolutionStatus(Enum):
    RESOLVED = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class AreaResolutionResult:
    status: AreaResolutionStatus
    area: AreaSnapshot | None = None
    candidates: tuple[AreaSnapshot, ...] = ()
    score: float | None = None


# Same tier shape as entities.resolve_entity_scored (Phase 6) - areas have no
# entity_id/domain/device_class dimension, so only the name + alias tiers
# apply. An exact alias match (_SCORE_EXACT_ALIAS) ranks just below an exact
# name match, same as entities.py's _SCORE_EXACT_ALIAS < _SCORE_EXACT_FRIENDLY_NAME -
# a configured alias is a strong, deliberate signal but the canonical area
# name still wins ties.
_SCORE_EXACT = 100
_SCORE_EXACT_ALIAS = 90
_SCORE_NORMALIZED_EXACT = 85
_SCORE_CONTAINS = 50
_SCORE_REVERSE_CONTAINS = 40
_AMBIGUITY_MARGIN = 5


def area_snapshots(entities: list[EntitySnapshot]) -> tuple[AreaSnapshot, ...]:
    """Distinct areas referenced by the given entities, deduplicated by
    area_id. Aliases are unioned across every entity in the area (all
    entities sharing an area_id carry the same ``area_aliases``, sourced
    from the one Area Registry entry - unioning is just a defensive merge,
    not expected to combine actually-different values)."""
    names: dict[str, str] = {}
    aliases: dict[str, set[str]] = {}
    for e in entities:
        if e.area_id is None or e.area_name is None:
            continue
        names.setdefault(e.area_id, e.area_name)
        aliases.setdefault(e.area_id, set()).update(e.area_aliases)
    return tuple(
        AreaSnapshot(area_id=area_id, name=name, aliases=tuple(sorted(aliases.get(area_id, ()))))
        for area_id, name in names.items()
    )


def _score_area_candidate(spoken: str, spoken_norm: str, candidate: str, *, is_alias: bool) -> float | None:
    candidate_norm = normalize_for_compare(candidate)
    if not candidate_norm or not spoken_norm:
        return None
    if candidate == spoken:
        return _SCORE_EXACT_ALIAS if is_alias else _SCORE_EXACT
    if candidate_norm == spoken_norm:
        return _SCORE_NORMALIZED_EXACT
    if spoken_norm in candidate_norm:
        return _SCORE_CONTAINS
    if candidate_norm in spoken_norm:
        return _SCORE_REVERSE_CONTAINS
    return None


def _score_area(spoken: str, spoken_norm: str, area: AreaSnapshot) -> float | None:
    """Highest tier score across the area's name and all configured
    aliases - mirrors entities.py's ``_best_score`` (best-of across
    friendly_name + generated aliases)."""
    best: float | None = None
    candidates = ((area.name, False),) + tuple((alias, True) for alias in area.aliases)
    for candidate, is_alias in candidates:
        score = _score_area_candidate(spoken, spoken_norm, candidate, is_alias=is_alias)
        if score is not None and (best is None or score > best):
            best = score
    return best


def resolve_area_scored(
    name: str,
    entities: list[EntitySnapshot],
    *,
    snapshots: tuple[AreaSnapshot, ...] | None = None,
) -> AreaResolutionResult:
    """Scored area resolution (v2 plan Phase 7, alias support added later):
    same candidate generation + scoring + ambiguity detection pattern as
    resolve_entity_scored (Phase 6), just without the entity-only
    dimensions (entity_id, domain, device_class) - a room only has its
    name and configured aliases.
    """
    spoken = (name or "").strip()
    if not spoken:
        return AreaResolutionResult(status=AreaResolutionStatus.NOT_FOUND)
    spoken_norm = normalize_for_compare(spoken)

    ranked: list[tuple[AreaSnapshot, float]] = []
    for area in snapshots if snapshots is not None else area_snapshots(entities):
        score = _score_area(spoken, spoken_norm, area)
        if score is not None:
            ranked.append((area, score))

    if not ranked:
        return AreaResolutionResult(status=AreaResolutionStatus.NOT_FOUND)

    ranked.sort(key=lambda pair: pair[1], reverse=True)
    top_score = ranked[0][1]
    tied = [area for area, score in ranked if top_score - score <= _AMBIGUITY_MARGIN]

    if len(tied) > 1:
        return AreaResolutionResult(status=AreaResolutionStatus.AMBIGUOUS, candidates=tuple(tied))
    return AreaResolutionResult(status=AreaResolutionStatus.RESOLVED, area=tied[0], score=top_score)


def resolve_area_name(name: str, entities: list[EntitySnapshot]) -> AreaResolveResult:
    """Resolve a spoken room name to an area_id within the given entity set.

    Thin wrapper around ``resolve_area_scored`` (v2 plan Phase 7), kept for
    existing callers (``parsers.QuantifierParser``) that only need the
    area_id, not the full scored result.
    """
    result = resolve_area_scored(name, entities)
    if result.status is AreaResolutionStatus.RESOLVED:
        return AreaResolveResult(status=AreaResolveStatus.OK, area_id=result.area.area_id)
    if result.status is AreaResolutionStatus.AMBIGUOUS:
        return AreaResolveResult(
            status=AreaResolveStatus.AMBIGUOUS,
            candidates=tuple(a.area_id for a in result.candidates),
        )
    return AreaResolveResult(status=AreaResolveStatus.NOT_FOUND)
