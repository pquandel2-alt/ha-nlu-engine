"""Area name resolution: spoken/friendly room name -> area_id.

Mirrors the algorithm in ``entities.resolve_entity`` (exact match first,
then an unambiguous "contains" match, otherwise AMBIGUOUS/NOT_FOUND) but
matches against the area names carried on ``EntitySnapshot`` rather than
entity friendly names. Built from the already-fetched entity list (no
separate registry access), so this stays hass-free like the rest of the
engine and needs no mocking to unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .entities import EntitySnapshot


class AreaResolveStatus(Enum):
    OK = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class AreaResolveResult:
    status: AreaResolveStatus
    area_id: str | None = None
    candidates: tuple[str, ...] = ()


def _area_name_map(entities: list[EntitySnapshot]) -> dict[str, set[str]]:
    """Lowercased area name -> set of area_ids sharing that name."""
    groups: dict[str, set[str]] = {}
    for e in entities:
        if e.area_id is None or e.area_name is None:
            continue
        groups.setdefault(e.area_name.strip().lower(), set()).add(e.area_id)
    return groups


def resolve_area_name(name: str, entities: list[EntitySnapshot]) -> AreaResolveResult:
    """Resolve a spoken room name to an area_id within the given entity set."""
    key = (name or "").strip().lower()
    if not key:
        return AreaResolveResult(status=AreaResolveStatus.NOT_FOUND)

    groups = _area_name_map(entities)

    exact = groups.get(key)
    if exact:
        if len(exact) == 1:
            return AreaResolveResult(status=AreaResolveStatus.OK, area_id=next(iter(exact)))
        return AreaResolveResult(status=AreaResolveStatus.AMBIGUOUS, candidates=tuple(exact))

    hits: set[str] = set()
    for area_name, area_ids in groups.items():
        if key in area_name or area_name in key:
            hits.update(area_ids)

    if len(hits) == 1:
        return AreaResolveResult(status=AreaResolveStatus.OK, area_id=next(iter(hits)))
    if len(hits) > 1:
        return AreaResolveResult(status=AreaResolveStatus.AMBIGUOUS, candidates=tuple(hits))
    return AreaResolveResult(status=AreaResolveStatus.NOT_FOUND)
