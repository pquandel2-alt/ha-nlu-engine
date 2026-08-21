"""Entity resolution: spoken/friendly name -> entity_id.

Algorithm ported from xiaozhi_entity_mcp's ``_name_map()``/``_resolve()``
(https://github.com/pquandel2-alt/xiaozhi_entity_mcp): exact match on the
lowercased friendly name first, then an unambiguous "contains" match,
otherwise an explicit AMBIGUOUS/NOT_FOUND result. Kept hass-free (works on
plain ``EntitySnapshot`` values) so it is unit-testable without a running
Home Assistant instance.
"""

from __future__ import annotations

import re
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
    floor_id: str | None = None
    floor_name: str | None = None
    floor_level: int | None = None
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    aliases: tuple[str, ...] = ()
    # HA Area Registry aliases (e.g. "draußen" for area "Garten") - the
    # area-level counterpart to ``aliases`` above (entity-level). Carried per
    # entity (not a separate area->aliases map) since EntitySnapshot is
    # already the only hass-free channel areas.py's resolver reads from - see
    # hass_entities.py::_area_aliases() for how this is populated live.
    area_aliases: tuple[str, ...] = ()
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

    # Common spoken device words are derived from the entity's real name,
    # preserving its distinguishing suffix (for example "Rollo Büro").
    if entity.domain == "cover":
        for source in (entity.friendly_name, *entity.aliases):
            if re.search(r"\brolll?ad(?:e|en)\b", source, re.IGNORECASE):
                for replacement in ("Rollladen", "Rollade", "Rollo", "Jalousie"):
                    add(
                        re.sub(r"\brolll?ad(?:e|en)\b", replacement, source, flags=re.IGNORECASE),
                        "derived",
                    )
    elif entity.domain == "light":
        for source in (entity.friendly_name, *entity.aliases):
            if re.search(r"\b(?:lampe|leuchte|licht)\b", source, re.IGNORECASE):
                for replacement in ("Lampe", "Leuchte", "Licht"):
                    add(
                        re.sub(r"\b(?:lampe|leuchte|licht)\b", replacement, source, flags=re.IGNORECASE),
                        "derived",
                    )

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


def normalize_for_compare(text: str) -> str:
    """Lowercase + collapse whitespace, for the 'Normalized exact' tier.

    Deliberately does not fold umlauts/punctuation - normalize.py already
    documents that boundary (semantic decisions belong in resolution, not
    normalization, but *guessing* a folding of "ß"/"ü" etc. would itself be
    exactly the kind of guess this project avoids).
    """
    folded = text.strip().casefold()
    folded = folded.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return " ".join(folded.split())


def _score_name_pair(spoken: str, spoken_norm: str, candidate_text: str, source: str) -> float | None:
    """Best tier score for one (spoken text, candidate name) pair, or None
    if they don't match under any tier at all."""
    if not candidate_text or not spoken_norm:
        return None
    candidate_norm = normalize_for_compare(candidate_text)
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
    index: EntityIndex | None = None,
) -> ResolutionResult:
    """Multi-stage scored entity resolution (v2 plan Phase 6, "Entity
    Resolver 2.0"): candidate generation + scoring across friendly_name/
    aliases/entity_id, optional context bonuses (Schritt 3, Context
    Filtering - only applied when the caller actually knows the area/domain/
    device_class it's looking for), then ambiguity detection (Schritt 4) on
    the final ranking.

    ``index`` (World Model Wave 1, building on Phase 23's ``EntityIndex``):
    an optional prebuilt index (see ``build_entity_index()``) used to narrow
    the candidate list scanned below via ``by_domain``/``by_area`` *before*
    scoring runs, for callers that already know the ``domain``/``area_id``
    they're resolving within and can build one index per conversation turn
    instead of paying an O(n) scan per resolution call. Omitted (the
    default): behaves exactly as before, scanning the full ``entities``
    list - fully backward compatible for every existing caller.

    Caveat: unlike the ``area_id``/``domain`` *bonuses* applied below (which
    only nudge a candidate's score, never exclude it), the ``index``-based
    prefilter is a hard filter - an entity outside the requested domain/area
    is dropped before scoring even runs, so it can never be picked no matter
    how well its name matches. Every current caller that passes both
    ``index`` and ``domain``/``area_id`` already only wants matches within
    that domain/area (see test_entity_index.py's
    ``test_index_prefilter_matches_full_scan_result`` for a worked example
    where prefiltering and full-scan agree), but this is a real, documented
    semantic narrowing versus the index-less path for the pathological case
    of a strong name match sitting entirely outside the given domain/area -
    flagged here rather than silently accepted.
    """
    spoken = (name or "").strip()
    if not spoken:
        return ResolutionResult(status=ResolutionStatus.NOT_FOUND)
    spoken_norm = normalize_for_compare(spoken)

    candidates: list[EntitySnapshot] = entities
    if index is not None and (domain is not None or area_id is not None):
        if domain is not None:
            candidates = list(index.by_domain.get(domain, ()))
            if area_id is not None:
                candidates = [e for e in candidates if e.area_id == area_id]
        else:
            candidates = list(index.by_area.get(area_id, ()))

    ranked: list[tuple[EntitySnapshot, float]] = []
    for entity in candidates:
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
    domain: str,
    entities: list[EntitySnapshot],
    area_id: str | None = None,
    floor_id: str | None = None,
) -> list[EntitySnapshot]:
    """All entities of a domain, optionally filtered to one area and/or floor.

    Unlike ``resolve_entity`` there is no ambiguity concept here - a
    quantifier ("alle"/"beide") is explicitly asking for every matching
    entity, so this returns everything that matches rather than requiring
    a single unambiguous hit. Sorted by entity_id for deterministic output.
    """
    matches = [
        e for e in entities
        if e.domain == domain
        and (area_id is None or e.area_id == area_id)
        and (floor_id is None or e.floor_id == floor_id)
    ]
    return sorted(matches, key=lambda e: e.entity_id)


@dataclass(frozen=True)
class EntityIndex:
    """Precomputed candidate lookups (v2 plan Phase 23, "Performance"):
    normalized_name/alias/area/domain -> matching entities.

    Building this costs the same O(n) scan ``resolve_entity_scored()``
    already does per call, so it only pays off once a single conversation
    turn needs *multiple* resolutions against the same entity list - not yet
    the case, since every parser today (see ``engine.py``'s
    ``_select_parser()``) calls ``resolve_entity``/``resolve_entities_by_domain``/
    ``resolve_area_name`` at most once per utterance. Built and tested now,
    ahead of its consumer - the same additive pattern already established
    for ``SemanticFrame``/``SemanticCommand``/``respond()`` (see their
    phases' docstrings): a future multi-target phase (Pronomen/Referenzen,
    Hierarchische Orte) can build one ``EntityIndex`` per turn and reuse it
    instead of rescanning ``entities`` for every candidate, rather than
    every future phase inventing its own indexing scheme ad hoc.
    """

    by_domain: Mapping[str, tuple[EntitySnapshot, ...]]
    by_area: Mapping[str, tuple[EntitySnapshot, ...]]
    by_normalized_name: Mapping[str, tuple[EntitySnapshot, ...]]
    by_normalized_alias: Mapping[str, tuple[EntitySnapshot, ...]]


def build_entity_index(entities: list[EntitySnapshot]) -> EntityIndex:
    """Group ``entities`` into the four lookups ``EntityIndex`` exposes.

    ``by_normalized_name`` covers the friendly name; ``by_normalized_alias``
    covers every ``generate_aliases()`` candidate (entity_id, humanized
    entity_id, configured aliases) - ``generate_aliases()`` already excludes
    the friendly name via its own ``seen`` set, so the two indices together,
    without overlap, cover every name tier ``resolve_entity_scored`` scores -
    just grouped for O(1) exact-tier lookup instead of a fresh scan.
    """
    by_domain: dict[str, list[EntitySnapshot]] = {}
    by_area: dict[str, list[EntitySnapshot]] = {}
    by_normalized_name: dict[str, list[EntitySnapshot]] = {}
    by_normalized_alias: dict[str, list[EntitySnapshot]] = {}

    for entity in entities:
        by_domain.setdefault(entity.domain, []).append(entity)
        if entity.area_id is not None:
            by_area.setdefault(entity.area_id, []).append(entity)
        by_normalized_name.setdefault(normalize_for_compare(entity.friendly_name), []).append(entity)
        for alias in generate_aliases(entity):
            by_normalized_alias.setdefault(normalize_for_compare(alias.text), []).append(entity)

    return EntityIndex(
        by_domain={key: tuple(value) for key, value in by_domain.items()},
        by_area={key: tuple(value) for key, value in by_area.items()},
        by_normalized_name={key: tuple(value) for key, value in by_normalized_name.items()},
        by_normalized_alias={key: tuple(value) for key, value in by_normalized_alias.items()},
    )
