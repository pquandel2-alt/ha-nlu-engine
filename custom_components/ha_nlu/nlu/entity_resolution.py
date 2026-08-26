"""Canonical HA-free entity resolution for semantic language consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

from ..entities import EntitySnapshot, normalize_for_compare
from ..entity_scope import resolve_entity_scope
from .domain_operations import DOMAIN_WORDS


class GroundingStatus(Enum):
    RESOLVED = auto()
    GROUP = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class GroundedEntities:
    status: GroundingStatus
    entities: tuple[EntitySnapshot, ...] = ()
    evidence: str | None = None


def mentioned_entities(
    text: str, entities: list[EntitySnapshot]
) -> tuple[EntitySnapshot, ...]:
    """Return unique longest explicit registry-name or alias mentions."""
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


def ground_entities(
    text: str,
    entities: list[EntitySnapshot],
    allowed_domains: frozenset[str],
) -> GroundedEntities:
    """Compose explicit name, domain, area and floor into one outcome."""
    mentioned = tuple(
        entity for entity in mentioned_entities(text, entities)
        if entity.domain in allowed_domains
    )
    if mentioned:
        status = (
            GroundingStatus.RESOLVED
            if len(mentioned) == 1
            else GroundingStatus.AMBIGUOUS
        )
        return GroundedEntities(status, mentioned, "explicit_name")

    scope = resolve_entity_scope(text, entities, allowed_domains)
    if scope is not None:
        status = (
            GroundingStatus.RESOLVED
            if len(scope.entities) == 1
            else GroundingStatus.GROUP
        )
        return GroundedEntities(status, tuple(scope.entities), scope.kind)

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
    if not candidates:
        return GroundedEntities(GroundingStatus.NOT_FOUND)
    status = (
        GroundingStatus.RESOLVED
        if len(candidates) == 1
        else GroundingStatus.GROUP
    )
    return GroundedEntities(status, tuple(candidates), "domain_location")


def resolve_query_targets(
    text: str,
    entities: list[EntitySnapshot],
    allowed_domains: frozenset[str],
) -> tuple[EntitySnapshot, ...]:
    """Compatibility view for existing read-only query consumers."""
    return ground_entities(text, entities, allowed_domains).entities
