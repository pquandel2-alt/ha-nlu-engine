"""Canonical HA-free entity resolution for semantic language consumers."""

from __future__ import annotations

import re

from ..entities import (
    EntitySnapshot,
    ResolutionResult,
    ResolutionStatus,
    ResolveResult,
    ResolveStatus,
    normalize_for_compare,
    resolve_entities_by_domain,
    resolve_entity,
    resolve_entity_scored,
)
from ..entity_scope import resolve_entity_scope
from .domain_operations import DOMAIN_WORDS

__all__ = (
    "ResolutionResult", "ResolutionStatus", "ResolveResult", "ResolveStatus",
    "all_mentioned_entities", "mentioned_entities", "resolve_entities_by_domain", "resolve_entity",
    "resolve_entity_scored", "resolve_mentioned_target", "resolve_named_target",
    "resolve_query_targets",
)


def _rank_mentions(
    text: str, entities: list[EntitySnapshot]
) -> list[tuple[int, EntitySnapshot]]:
    """Rank explicit registry-name and alias mentions once for all consumers."""
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
    return found


def all_mentioned_entities(
    text: str, entities: list[EntitySnapshot]
) -> tuple[EntitySnapshot, ...]:
    """Return every explicitly named entity, longest names first."""
    found = _rank_mentions(text, entities)
    found.sort(key=lambda item: (-item[0], item[1].entity_id))
    return tuple(entity for _, entity in found)


def mentioned_entities(
    text: str, entities: list[EntitySnapshot]
) -> tuple[EntitySnapshot, ...]:
    """Return unique longest explicit registry-name or alias mentions."""
    found = _rank_mentions(text, entities)
    if not found:
        return ()
    best = max(score for score, _ in found)
    return tuple(entity for score, entity in found if score == best)


def resolve_named_target(
    name: str,
    entities: list[EntitySnapshot],
    allowed_domains: frozenset[str] | None = None,
) -> ResolutionResult:
    """Resolve one complete spoken target through the canonical scorer."""
    candidates = (
        entities
        if allowed_domains is None
        else [entity for entity in entities if entity.domain in allowed_domains]
    )
    return resolve_entity_scored(name.strip(), candidates)


def resolve_mentioned_target(
    text: str,
    entities: list[EntitySnapshot],
    allowed_domains: frozenset[str],
) -> ResolutionResult:
    """Resolve one registry name embedded anywhere in a larger utterance."""
    matches = mentioned_entities(
        text, [entity for entity in entities if entity.domain in allowed_domains]
    )
    if not matches:
        return ResolutionResult(status=ResolutionStatus.NOT_FOUND)
    if len(matches) > 1:
        return ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS, candidates=matches
        )
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity=next(iter(matches)),
        score=100,
    )


def resolve_query_targets(
    text: str,
    entities: list[EntitySnapshot],
    allowed_domains: frozenset[str],
) -> tuple[EntitySnapshot, ...]:
    """Compose explicit name, domain, area and floor into concrete targets."""
    mentioned = tuple(
        entity for entity in mentioned_entities(text, entities)
        if entity.domain in allowed_domains
    )
    if mentioned:
        return mentioned

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
    if not candidates:
        return ()
    return tuple(candidates)
