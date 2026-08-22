"""Deterministic resolution of a location mentioned anywhere in a sentence."""

from __future__ import annotations

import re

from ..entities import EntitySnapshot
from ..floors import FloorResolveStatus, resolve_floor_by_level_keyword
from .group_semantics import resolve_group_location


_LEVEL_CUE_RE = re.compile(r"(?<!nach\s)\b(?:oben|unten)\b", re.I)


def resolve_semantic_location(
    text: str, entities: list[EntitySnapshot]
) -> tuple[str, str | None, str | None] | None:
    """Return ``(spoken_text, area_id, floor_id)`` for one clear location."""
    level = _LEVEL_CUE_RE.search(text)
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
    resolved = {resolve_group_location(name, entities) for name in selected}
    resolved.discard(None)
    if len(resolved) != 1:
        return None
    area_id, floor_id = resolved.pop()
    return selected[0], area_id, floor_id
