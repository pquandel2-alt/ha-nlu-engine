"""Deterministic resolution of a location mentioned anywhere in a sentence."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..areas import AreaResolutionStatus, resolve_area_scored
from ..entities import EntitySnapshot, generate_aliases
from ..floors import (
    FloorResolutionStatus,
    FloorResolveStatus,
    resolve_floor_by_level_keyword,
    resolve_floor_scored,
)

if TYPE_CHECKING:
    from ..world_model import WorldModel


_LEVEL_CUE_RE = re.compile(r"(?<!nach\s)\b(?:oben|unten)\b", re.I)


def resolve_location_name(
    name: str,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None = None,
) -> tuple[str | None, str | None] | None:
    """Resolve one registry location using the strongest exact evidence.

    Areas and floors share one namespace in natural language.  Comparing
    their scores prevents a partial area name (``Flur Erdgeschoss``) from
    stealing an exact floor name (``Erdgeschoss``), while an exact area name
    still beats a merely contained floor name.
    """
    area = resolve_area_scored(
        name,
        entities,
        snapshots=world_model.areas if world_model is not None else None,
    )
    floor = resolve_floor_scored(
        name,
        entities,
        snapshots=world_model.floors if world_model is not None else None,
    )
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
    text: str,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None = None,
) -> tuple[str, str | None, str | None] | None:
    """Return ``(spoken_text, area_id, floor_id)`` for one clear location."""
    whole_home = re.search(
        r"\b(?:(?:im|in\s+dem)\s+)?(?:ganzen|gesamten)\s+haus\b", text, re.I
    )
    if whole_home is not None:
        return whole_home.group(0), None, None
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

    names = (
        {
            name
            for area in world_model.areas
            for name in (area.name, *area.aliases)
        }
        | {floor.name for floor in world_model.floors}
        if world_model is not None
        else {
            name
            for entity in entities
            for name in (
                entity.area_name,
                *entity.area_aliases,
                entity.floor_name,
            )
            if name
        }
    )
    # HA registry names may contain orthographic word boundaries that spoken
    # compounds naturally omit ("Pole Raum" -> "Poleraum").  Treat only the
    # whitespace-free form of the *same registered location* as equivalent;
    # this is deterministic normalization, not fuzzy guessing.
    search_names = {
        (spoken, canonical)
        for canonical in names
        for spoken in {
            canonical,
            re.sub(r"\s+", "", canonical),
        }
        if spoken
    }
    mentioned = [
        (match.group(0), canonical)
        for spoken, canonical in sorted(
            search_names, key=lambda item: len(item[0]), reverse=True
        )
        if (match := re.search(rf"\b{re.escape(spoken)}\b", text, re.I))
    ]
    if not mentioned:
        return None
    longest = len(mentioned[0][0])
    selected = [item for item in mentioned if len(item[0]) == longest]
    resolved = {
        resolve_location_name(canonical, entities, world_model)
        for _, canonical in selected
    }
    resolved.discard(None)
    if len(resolved) != 1:
        return None
    area_id, floor_id = resolved.pop()
    return selected[0][0], area_id, floor_id


def resolve_coordinated_locations(
    text: str,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None = None,
) -> tuple[tuple[str, str | None, str | None], ...] | None:
    """Resolve an explicit ``A und B`` location union.

    This is deliberately narrower than :func:`resolve_semantic_location`:
    two registry locations are combined only when the source text actually
    coordinates their non-overlapping mentions with ``und``.  Merely naming
    an area and its floor in the same phrase therefore does not silently turn
    an intersection into a union, and ``oder`` remains ambiguous instead of
    being interpreted as "both".
    """
    names = (
        {
            name
            for area in world_model.areas
            for name in (area.name, *area.aliases)
        }
        | {floor.name for floor in world_model.floors}
        if world_model is not None
        else {
            name
            for entity in entities
            for name in (
                entity.area_name,
                *entity.area_aliases,
                entity.floor_name,
            )
            if name
        }
    )
    mentions: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for name in sorted(names, key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(name)}\b", text, re.I):
            if any(start < match.end() and match.start() < end for start, end in occupied):
                continue
            mentions.append((match.start(), match.end(), match.group(0)))
            occupied.append((match.start(), match.end()))
    mentions.sort()
    if len(mentions) < 2:
        return None

    resolved: list[tuple[str, str | None, str | None]] = []
    for index, (_, end, spoken) in enumerate(mentions):
        location = resolve_location_name(spoken, entities, world_model)
        if location is None:
            return None
        if index < len(mentions) - 1:
            next_start = mentions[index + 1][0]
            connector = text[end:next_start]
            if re.search(r"\bund\b", connector, re.I) is None:
                return None
        area_id, floor_id = location
        item = (spoken, area_id, floor_id)
        if item not in resolved:
            resolved.append(item)
    return tuple(resolved) if len(resolved) >= 2 else None
