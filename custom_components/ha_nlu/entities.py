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


def build_name_map(entities: list[EntitySnapshot]) -> dict[str, list[EntitySnapshot]]:
    """Group entities by lowercased friendly name.

    A list (not a single entity) per name, because real HA instances do have
    duplicate friendly names (e.g. the same device exposed by two
    integrations) - collapsing those to "last one wins" would silently
    resolve to the wrong entity instead of surfacing them as AMBIGUOUS.
    """
    groups: dict[str, list[EntitySnapshot]] = {}
    for e in entities:
        groups.setdefault(e.friendly_name.strip().lower(), []).append(e)
    return groups


def resolve_entity(name: str, entities: list[EntitySnapshot]) -> ResolveResult:
    """Resolve a spoken name to an entity within the given entity set.

    Exact match wins, but only if it is unambiguous (duplicate friendly
    names count as AMBIGUOUS, not "first/last wins"). Otherwise, a
    case-insensitive "contains" match is accepted, checked in both
    directions - the spoken name inside the friendly name (e.g. "Büro"
    matches "Rolllade Büro") or the friendly name inside the spoken name
    (e.g. "Rollladen Wohnzimmer" matches a cover just called "Wohnzimmer") -
    and only if that is unambiguous too. Mirrors ``_resolve()`` in
    xiaozhi_entity_mcp so both integrations agree on what counts as a safe
    match for entities like ``switch.garagentor``.
    """
    key = (name or "").strip().lower()
    if not key:
        return ResolveResult(status=ResolveStatus.NOT_FOUND)

    groups = build_name_map(entities)

    exact = groups.get(key)
    if exact:
        if len(exact) == 1:
            return ResolveResult(status=ResolveStatus.OK, entity=exact[0])
        return ResolveResult(status=ResolveStatus.AMBIGUOUS, candidates=tuple(exact))

    hits: dict[str, EntitySnapshot] = {}
    for friendly_name, group in groups.items():
        if key in friendly_name or friendly_name in key:
            for e in group:
                hits[e.entity_id] = e

    if len(hits) == 1:
        return ResolveResult(status=ResolveStatus.OK, entity=next(iter(hits.values())))
    if len(hits) > 1:
        return ResolveResult(status=ResolveStatus.AMBIGUOUS, candidates=tuple(hits.values()))
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
