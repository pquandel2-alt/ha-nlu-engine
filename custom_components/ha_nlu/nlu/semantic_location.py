"""Deterministic resolution of a location mentioned anywhere in a sentence."""

from __future__ import annotations

import re

from ..areas import AreaResolutionStatus, resolve_area_scored
from ..entities import EntitySnapshot, generate_aliases
from ..floors import (
    FloorResolutionStatus,
    FloorResolveStatus,
    resolve_floor_by_level_keyword,
    resolve_floor_scored,
)


_LEVEL_CUE_RE = re.compile(r"(?<!nach\s)\b(?:oben|unten)\b", re.I)


def resolve_location_name(
    name: str, entities: list[EntitySnapshot]
) -> tuple[str | None, str | None] | None:
    """Resolve one registry location using the strongest exact evidence.

    Areas and floors share one namespace in natural language.  Comparing
    their scores prevents a partial area name (``Flur Erdgeschoss``) from
    stealing an exact floor name (``Erdgeschoss``), while an exact area name
    still beats a merely contained floor name.
    """
    area = resolve_area_scored(name, entities)
    floor = resolve_floor_scored(name, entities)
    area_score = (
        area.score if area.status is AreaResolutionStatus.RESOLVED else None
    )
    floor_score = (
        floor.score if floor.status is FloorResolutionStatus.RESOLVED else None
    )
    if area_score is None and floor_score is None:
        return None
    if area_score is not None and floor_score is not None and area_score == floor_score:
        # An exact floor and exact area with the same spoken name denotes the
        # broader floor scope. This is the useful and least surprising
        # interpretation for queries and group commands.
        return None, floor.floor.floor_id
    if floor_score is not None and (area_score is None or floor_score > area_score):
        return None, floor.floor.floor_id
    if area_score is not None and (floor_score is None or area_score > floor_score):
        return area.area.area_id, None
    return None


def _inside_entity_name(
    text: str, start: int, end: int, entities: list[EntitySnapshot]
) -> bool:
    """Whether a directional word belongs to a registered entity name."""
    for entity in entities:
        names = (entity.friendly_name, *(alias.text for alias in generate_aliases(entity)))
        for name in names:
            for match in re.finditer(rf"\b{re.escape(name)}\b", text, re.I):
                if match.start() <= start and end <= match.end():
                    return True
    return False


def has_explicit_location_cue(text: str, entities: list[EntitySnapshot]) -> bool:
    """Whether text contains a locative or standalone level direction."""
    if re.search(r"\b(?:im|in\s+der|in\s+dem|am|beim)\s+", text, re.I):
        return True
    return any(
        not _inside_entity_name(text, match.start(), match.end(), entities)
        for match in _LEVEL_CUE_RE.finditer(text)
    )


def resolve_semantic_location(
    text: str, entities: list[EntitySnapshot]
) -> tuple[str, str | None, str | None] | None:
    """Return ``(spoken_text, area_id, floor_id)`` for one clear location."""
    level = next(
        (
            match for match in _LEVEL_CUE_RE.finditer(text)
            if not _inside_entity_name(text, match.start(), match.end(), entities)
        ),
        None,
    )
    if level is not None:
        resolved_level = resolve_floor_by_level_keyword(
            "up" if level.group(0).casefold() == "oben" else "down", entities
        )
        if resolved_level.status is not FloorResolveStatus.OK:
            return None
        return level.group(0), None, resolved_level.floor_id

    names = {
        name
        for entity in entities
        for name in (entity.area_name, *entity.area_aliases, entity.floor_name)
        if name
    }
    mentioned = [
        name for name in sorted(names, key=len, reverse=True)
        if re.search(rf"\b{re.escape(name)}\b", text, re.I)
    ]
    if not mentioned:
        return None
    longest = len(mentioned[0])
    selected = [name for name in mentioned if len(name) == longest]
    resolved = {resolve_location_name(name, entities) for name in selected}
    resolved.discard(None)
    if len(resolved) != 1:
        return None
    area_id, floor_id = resolved.pop()
    return selected[0], area_id, floor_id
