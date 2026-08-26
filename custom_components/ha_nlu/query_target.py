"""Shared, HA-free target resolution for read-only capability questions."""

from __future__ import annotations

import re
from typing import cast

from .entities import EntitySnapshot, normalize_for_compare
from .entity_scope import resolve_entity_scope
from .nlu.domain_operations import DOMAIN_WORDS


def mentioned_entities(
    text: str, entities: list[EntitySnapshot]
) -> tuple[EntitySnapshot, ...]:
    """Return the unique longest explicit registry-name mentions."""
    normalized = normalize_for_compare(text)
    found: list[tuple[int, EntitySnapshot]] = []
    for entity in entities:
        score = max(
            (
                len(key)
                for name in (entity.friendly_name, *entity.aliases)
                if (key := normalize_for_compare(name))
                and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", normalized)
            ),
            default=0,
        )
        if score:
            found.append((score, entity))
    if not found:
        return ()
    best = max(score for score, _ in found)
    return tuple(entity for score, entity in found if score == best)


def resolve_query_targets(
    text: str,
    entities: list[EntitySnapshot],
    allowed_domains: frozenset[str],
) -> tuple[EntitySnapshot, ...]:
    """Compose explicit name, domain and location for a read-only query."""
    mentioned = mentioned_entities(text, entities)
    if mentioned:
        return tuple(entity for entity in mentioned if entity.domain in allowed_domains)
    scope = resolve_entity_scope(text, entities, allowed_domains)
    if scope is not None:
        return tuple(scope.entities)
    normalized = normalize_for_compare(text)
    spoken_domains = {
        domain
        for domain, words in DOMAIN_WORDS.items()
        if domain in allowed_domains
        and any(
            re.search(
                rf"(?<!\w){re.escape(normalize_for_compare(word))}(?!\w)",
                normalized,
            )
            for word in words
        )
    }
    candidates = [entity for entity in entities if entity.domain in spoken_domains]
    spoken_areas = {
        entity.area_id
        for entity in candidates
        if entity.area_id
        and any(
            area
            and re.search(
                rf"(?<!\w){re.escape(normalize_for_compare(area))}(?!\w)",
                normalized,
            )
            for area in (entity.area_name, *entity.area_aliases)
        )
    }
    if spoken_areas:
        candidates = [entity for entity in candidates if entity.area_id in spoken_areas]
    return tuple(candidates)


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
