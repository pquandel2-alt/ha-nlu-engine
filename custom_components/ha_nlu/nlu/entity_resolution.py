"""Canonical HA-free entity resolution for semantic language consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..entities import (
    EntitySnapshot,
    EntityIndex,
    ResolutionResult,
    ResolutionStatus,
    ResolveResult,
    ResolveStatus,
    normalize_for_compare,
    resolve_entities_by_domain,
    resolve_entity,
    resolve_entity_scored,
    generate_aliases,
)
from ..entity_scope import resolve_entity_scope
from .domain_operations import DOMAIN_WORDS

__all__ = (
    "ResolutionResult", "ResolutionStatus", "ResolveResult", "ResolveStatus",
    "all_mentioned_entities", "mentioned_entities", "resolve_entities_by_domain", "resolve_entity",
    "resolve_entity_scored", "resolve_mentioned_target", "resolve_named_target",
    "resolve_query_targets", "rank_semantic_targets", "RankedTarget",
)


@dataclass(frozen=True)
class RankedTarget:
    """One explainable candidate from the shared semantic name resolver."""

    entity: EntitySnapshot
    score: int
    source: str
    matched_name: str


_WORD_RE = re.compile(r"[\wäöüß]+", re.I)


def _word_set(text: str, ignored: frozenset[str]) -> set[str]:
    return {
        token
        for raw in _WORD_RE.findall(text)
        if (token := normalize_for_compare(raw)) not in ignored
    }


def rank_semantic_targets(
    text: str,
    entities: Iterable[EntitySnapshot],
    *,
    domains: frozenset[str] = frozenset(),
    area_id: str | None = None,
    floor_id: str | None = None,
    ignored_tokens: frozenset[str] = frozenset(),
    index: EntityIndex | None = None,
) -> tuple[RankedTarget, ...]:
    """Rank embedded registry names once for every semantic consumer.

    Complete friendly/configured names outrank token-subset matches. Generic
    domain words may be omitted from a registry name only after the caller
    supplies the shared ignored-token set. Equal top scores remain equal so
    the caller can produce an ambiguity rather than selecting by iteration
    order.
    """
    normalized_text = normalize_for_compare(text)
    utterance = _word_set(text, ignored_tokens)
    if index is not None and len(domains) == 1:
        pool: Iterable[EntitySnapshot] = index.by_domain.get(next(iter(domains)), ())
    else:
        pool = entities
    ranked: list[RankedTarget] = []
    for entity in pool:
        if domains and entity.domain not in domains:
            continue
        if area_id is not None and entity.area_id != area_id:
            continue
        if floor_id is not None and entity.floor_id != floor_id:
            continue
        best: RankedTarget | None = None
        names = (
            ((entity.friendly_name, "friendly_name"),)
            + tuple((alias, "configured") for alias in entity.aliases)
            + tuple((alias.text, alias.source) for alias in generate_aliases(entity))
        )
        for name, source in names:
            normalized_name = normalize_for_compare(name)
            score = 0
            if normalized_name and re.search(
                rf"(?<!\w){re.escape(normalized_name)}(?!\w)", normalized_text
            ):
                source_bonus = 30 if source in {"friendly_name", "configured"} else 0
                score = 1000 + source_bonus + len(normalized_name)
            else:
                name_tokens = _word_set(name, frozenset())
                generic = {
                    normalize_for_compare(word)
                    for words in DOMAIN_WORDS.values()
                    for word in words
                }
                distinctive = name_tokens - generic
                required = (
                    name_tokens
                    if source in {"entity_name", "entity_id"}
                    else distinctive or name_tokens
                )
                if required and required <= utterance:
                    score = len(required) * 10 + len(name_tokens)
            if score and (best is None or score > best.score):
                best = RankedTarget(entity, score, source, name)
        if best is not None:
            ranked.append(best)
    return tuple(sorted(ranked, key=lambda item: (-item.score, item.entity.entity_id)))


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
