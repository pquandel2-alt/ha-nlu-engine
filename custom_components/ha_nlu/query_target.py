"""Shared, HA-free target resolution for read-only capability questions."""

from __future__ import annotations

from typing import cast

from .entities import EntitySnapshot
from .nlu.entity_resolution import mentioned_entities, resolve_query_targets

__all__ = ("list_attribute_values", "mentioned_entities", "resolve_query_targets")


def list_attribute_values(
    entity: EntitySnapshot, keys: tuple[str, ...]
) -> tuple[str, ...]:
    """Read the first declared list-like HA attribute without guessing."""
    for key in keys:
        raw = entity.attributes.get(key)
        if isinstance(raw, (list, tuple)):
            values = cast(list[object] | tuple[object, ...], raw)
            return tuple(str(value) for value in values if str(value).strip())
    return ()
