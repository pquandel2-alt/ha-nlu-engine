"""Entity resolution: spoken/friendly name -> entity_id.

Algorithm ported from xiaozhi_entity_mcp's ``_name_map()``/``_resolve()``
(https://github.com/pquandel2-alt/xiaozhi_entity_mcp): exact match on the
lowercased friendly name first, then an unambiguous "contains" match,
otherwise an explicit AMBIGUOUS/NOT_FOUND result. Kept hass-free (works on
plain ``EntitySnapshot`` values) so it is unit-testable without a running
Home Assistant instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Mapping


@dataclass(frozen=True)
class EntitySnapshot:
    """Hass-free view of a Home Assistant entity.

    ``aliases`` and ``capabilities`` are structurally present from here on
    (v2 plan Phase 4) but populated empty until their own phases build the
    logic that fills them - the alias system (Phase 5) and the Capability
    concept (Phase 9). ``attributes`` holds the raw HA state attributes for
    later domain-specific extensions (e.g. Phase 14+) to read from, without
    needing new EntitySnapshot fields per attribute.
    """

    entity_id: str
    friendly_name: str
    domain: str
    state: str
    area_id: str | None = None
    area_name: str | None = None
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    aliases: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    capabilities: frozenset[str] = field(default_factory=frozenset)


class ResolveStatus(Enum):
    OK = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class ResolveResult:
    status: ResolveStatus
    entity: EntitySnapshot | None = None
    candidates: tuple[EntitySnapshot, ...] = ()


@dataclass(frozen=True)
class EntityAlias:
    """One alternate name candidate for an entity, with its provenance.

    ``source`` is kept (rather than discarded once generated) because Phase
    6 (Entity Resolver 2.0) scores candidates differently per source - a
    configured alias and a derived entity-id name are not equally strong
    evidence.
    """

    entity_id: str
    text: str
    source: str


def _humanize_object_id(entity_id: str) -> str:
    """'light.wohnzimmer_decke' -> 'Wohnzimmer Decke'.

    Pure formatting (underscore -> space, title case), not a translation -
    safe to apply to any entity_id without risking a wrong guess.
    """
    object_id = entity_id.split(".", 1)[1]
    return object_id.replace("_", " ").strip().title()


def generate_aliases(entity: EntitySnapshot) -> tuple[EntityAlias, ...]:
    """Alternate name candidates for an entity, beyond its friendly_name.

    Sources: the entity_id itself (raw and humanized "Entity Name" form) and
    the aliases configured in HA's entity registry (``EntitySnapshot.aliases``,
    wired from ``entry.aliases`` in hass_entities.py - the same field HA's
    own Assist feature uses). Area and Device Class are deliberately *not*
    turned into text candidates here: Phase 6 (Entity Resolver 2.0) already
    scores them as their own dimensions (matching area +30, matching device
    class +15), and translating a device_class into German text for an
    unknown/future HA device class would be a guess, not a lookup.
    """
    seen: set[str] = {entity.friendly_name.strip().lower()}
    aliases: list[EntityAlias] = []

    def add(text: str | None, source: str) -> None:
        if not text:
            return
        text = text.strip()
        key = text.lower()
        if not text or key in seen:
            return
        seen.add(key)
        aliases.append(EntityAlias(entity_id=entity.entity_id, text=text, source=source))

    add(_humanize_object_id(entity.entity_id), "entity_name")
    add(entity.entity_id, "entity_id")
    for configured in entity.aliases:
        add(configured, "configured")

    return tuple(aliases)


class ResolutionStatus(Enum):
    RESOLVED = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class ResolutionResult:
    status: ResolutionStatus
    entity: EntitySnapshot | None = None
    candidates: tuple[EntitySnapshot, ...] = ()
    score: float | None = None


# Scoring weights (v2 plan Phase 6, "Beispielwerte, experimentell, durch
# Tests zu validieren" - kept exactly as specified, validated by
# tests/test_resolver.py rather than tuned further).
_SCORE_EXACT_FRIENDLY_NAME = 100
_SCORE_EXACT_ALIAS = 90
_SCORE_NORMALIZED_EXACT = 85
_SCORE_ENTITY_ID_MATCH = 70
_SCORE_CONTAINS = 50
_SCORE_REVERSE_CONTAINS = 40
_SCORE_MATCHING_AREA = 30
_SCORE_MATCHING_DOMAIN = 20
_SCORE_MATCHING_DEVICE_CLASS = 15

# Two candidates within this many points of each other are "practically
# equivalent" (plan's Schritt 4, Ambiguity Detection) - report AMBIGUOUS
# instead of guessing the higher-scored one.
_AMBIGUITY_MARGIN = 5


def _normalize_for_compare(text: str) -> str:
    """Lowercase + collapse whitespace, for the 'Normalized exact' tier.

    Deliberately does not fold umlauts/punctuation - normalize.py already
    documents that boundary (semantic decisions belong in resolution, not
    normalization, but *guessing* a folding of "ß"/"ü" etc. would itself be
    exactly the kind of guess this project avoids).
    """
    return " ".join(text.strip().lower().split())


def _score_name_pair(spoken: str, spoken_norm: str, candidate_text: str, source: str) -> float | None:
    """Best tier score for one (spoken text, candidate name) pair, or None
    if they don't match under any tier at all."""
    if not candidate_text or not spoken_norm:
        return None
    candidate_norm = _normalize_for_compare(candidate_text)
    if not candidate_norm:
        return None

    if source == "entity_id":
        # Raw entity_ids are lowercase by HA convention - no natural-language
        # "contains" fragment matching for them, just a dedicated tier.
        return _SCORE_ENTITY_ID_MATCH if candidate_norm == spoken_norm else None

    if candidate_text == spoken:
        return _SCORE_EXACT_FRIENDLY_NAME if source == "friendly_name" else _SCORE_EXACT_ALIAS
    if candidate_norm == spoken_norm:
        return _SCORE_NORMALIZED_EXACT
    if spoken_norm in candidate_norm:
        return _SCORE_CONTAINS
    if candidate_norm in spoken_norm:
        return _SCORE_REVERSE_CONTAINS
    return None


def _best_name_score(spoken: str, spoken_norm: str, entity: EntitySnapshot) -> float | None:
    """Highest tier score across friendly_name and all generated aliases -
    Schritt 1+2 of the plan (Candidate Generation + Scoring) for one entity."""
    best: float | None = None
    for text, source in [(entity.friendly_name, "friendly_name"), *(
        (a.text, a.source) for a in generate_aliases(entity)
    )]:
        score = _score_name_pair(spoken, spoken_norm, text, source)
        if score is not None and (best is None or score > best):
            best = score
    return best


def resolve_entity_scored(
    name: str,
    entities: list[EntitySnapshot],
    *,
    area_id: str | None = None,
    domain: str | None = None,
    device_class: str | None = None,
) -> ResolutionResult:
    """Multi-stage scored entity resolution (v2 plan Phase 6, "Entity
    Resolver 2.0"): candidate generation + scoring across friendly_name/
    aliases/entity_id, optional context bonuses (Schritt 3, Context
    Filtering - only applied when the caller actually knows the area/domain/
    device_class it's looking for), then ambiguity detection (Schritt 4) on
    the final ranking.
    """
    spoken = (name or "").strip()
    if not spoken:
        return ResolutionResult(status=ResolutionStatus.NOT_FOUND)
    spoken_norm = _normalize_for_compare(spoken)

    ranked: list[tuple[EntitySnapshot, float]] = []
    for entity in entities:
        name_score = _best_name_score(spoken, spoken_norm, entity)
        if name_score is None:
            continue
        total = name_score
        if area_id is not None and entity.area_id == area_id:
            total += _SCORE_MATCHING_AREA
        if domain is not None and entity.domain == domain:
            total += _SCORE_MATCHING_DOMAIN
        if device_class is not None and entity.device_class == device_class:
            total += _SCORE_MATCHING_DEVICE_CLASS
        ranked.append((entity, total))

    if not ranked:
        return ResolutionResult(status=ResolutionStatus.NOT_FOUND)

    ranked.sort(key=lambda pair: pair[1], reverse=True)
    top_score = ranked[0][1]
    tied = [entity for entity, score in ranked if top_score - score <= _AMBIGUITY_MARGIN]

    if len(tied) > 1:
        return ResolutionResult(status=ResolutionStatus.AMBIGUOUS, candidates=tuple(tied))
    return ResolutionResult(status=ResolutionStatus.RESOLVED, entity=tied[0], score=top_score)


def resolve_entity(name: str, entities: list[EntitySnapshot]) -> ResolveResult:
    """Resolve a spoken name to an entity within the given entity set.

    Thin, context-free wrapper around ``resolve_entity_scored`` (v2 plan
    Phase 6) for callers that don't need scores/context bonuses - exact and
    normalized-exact matches win outright (their score gap to any
    contains-tier competitor always exceeds the ambiguity margin), duplicate
    names/aliases surface as AMBIGUOUS rather than "first one wins".
    """
    result = resolve_entity_scored(name, entities)
    if result.status is ResolutionStatus.RESOLVED:
        return ResolveResult(status=ResolveStatus.OK, entity=result.entity)
    if result.status is ResolutionStatus.AMBIGUOUS:
        return ResolveResult(status=ResolveStatus.AMBIGUOUS, candidates=result.candidates)
    return ResolveResult(status=ResolveStatus.NOT_FOUND)


def resolve_entities_by_domain(
    domain: str, entities: list[EntitySnapshot], area_id: str | None = None
) -> list[EntitySnapshot]:
    """All entities of a domain, optionally filtered to one area.

    Unlike ``resolve_entity`` there is no ambiguity concept here - a
    quantifier ("alle"/"beide") is explicitly asking for every matching
    entity, so this returns everything that matches rather than requiring
    a single unambiguous hit. Sorted by entity_id for deterministic output.
    """
    matches = [e for e in entities if e.domain == domain and (area_id is None or e.area_id == area_id)]
    return sorted(matches, key=lambda e: e.entity_id)
