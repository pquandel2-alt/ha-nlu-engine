"""Area name resolution: spoken/friendly room name -> area_id.

Phase 7 (v2 plan, "Area Resolver 2.0"): scored resolution mirroring
``entities.resolve_entity_scored`` (Phase 6) - the same tier structure
(exact, normalized exact, contains, reverse contains), adapted to areas
(no aliases/entity_id/domain/device_class dimension - those don't apply to
rooms). Built from the already-fetched entity list's area_id/area_name (no
separate registry access), so this stays hass-free like the rest of the
engine and needs no mocking to unit-test.
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
# alias/entity_id/domain/device_class dimension, so only the four name tiers
# apply.
_SCORE_EXACT = 100
_SCORE_NORMALIZED_EXACT = 85
_SCORE_CONTAINS = 50
_SCORE_REVERSE_CONTAINS = 40
_AMBIGUITY_MARGIN = 5


def _area_snapshots(entities: list[EntitySnapshot]) -> tuple[AreaSnapshot, ...]:
    """Distinct areas referenced by the given entities, deduplicated by area_id."""
    seen: dict[str, AreaSnapshot] = {}
    for e in entities:
        if e.area_id is None or e.area_name is None:
            continue
        seen.setdefault(e.area_id, AreaSnapshot(area_id=e.area_id, name=e.area_name))
    return tuple(seen.values())


def _score_area_name(spoken: str, spoken_norm: str, area_name: str) -> float | None:
    area_norm = normalize_for_compare(area_name)
    if not area_norm or not spoken_norm:
        return None
    if area_name == spoken:
        return _SCORE_EXACT
    if area_norm == spoken_norm:
        return _SCORE_NORMALIZED_EXACT
    if spoken_norm in area_norm:
        return _SCORE_CONTAINS
    if area_norm in spoken_norm:
        return _SCORE_REVERSE_CONTAINS
    return None


def resolve_area_scored(name: str, entities: list[EntitySnapshot]) -> AreaResolutionResult:
    """Scored area resolution (v2 plan Phase 7): same candidate generation +
    scoring + ambiguity detection pattern as resolve_entity_scored (Phase 6),
    just without the entity-only dimensions (aliases, entity_id, domain,
    device_class) - a room only has its name(s).
    """
    spoken = (name or "").strip()
    if not spoken:
        return AreaResolutionResult(status=AreaResolutionStatus.NOT_FOUND)
    spoken_norm = normalize_for_compare(spoken)

    ranked: list[tuple[AreaSnapshot, float]] = []
    for area in _area_snapshots(entities):
        score = _score_area_name(spoken, spoken_norm, area.name)
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
