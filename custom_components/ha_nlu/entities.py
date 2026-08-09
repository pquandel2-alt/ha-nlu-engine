"""Entity resolution: spoken/friendly name -> entity_id.

Algorithm ported from xiaozhi_entity_mcp's ``_name_map()``/``_resolve()``
(https://github.com/pquandel2-alt/xiaozhi_entity_mcp): exact match on the
lowercased friendly name first, then an unambiguous "contains" match,
otherwise an explicit AMBIGUOUS/NOT_FOUND result. Kept hass-free (works on
plain ``EntitySnapshot`` values) so it is unit-testable without a running
Home Assistant instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


@dataclass(frozen=True)
class EntitySnapshot:
    """Minimal, hass-free view of a Home Assistant entity."""

    entity_id: str
    friendly_name: str
    domain: str
    state: str


class ResolveStatus(Enum):
    OK = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()


@dataclass(frozen=True)
class ResolveResult:
    status: ResolveStatus
    entity: EntitySnapshot | None = None
    candidates: tuple[EntitySnapshot, ...] = ()


def build_name_map(entities: list[EntitySnapshot]) -> dict[str, EntitySnapshot]:
    """Map lowercased friendly name -> EntitySnapshot."""
    return {e.friendly_name.strip().lower(): e for e in entities}


def resolve_entity(name: str, entities: list[EntitySnapshot]) -> ResolveResult:
    """Resolve a spoken name to an entity within the given entity set.

    Exact match wins. Otherwise, a case-insensitive "contains" match is
    accepted only if it is unambiguous (exactly one candidate) - mirrors
    ``_resolve()`` in xiaozhi_entity_mcp so both integrations agree on what
    counts as a safe match for entities like ``switch.garagentor``.
    """
    key = (name or "").strip().lower()
    if not key:
        return ResolveResult(status=ResolveStatus.NOT_FOUND)

    name_map = build_name_map(entities)
    exact = name_map.get(key)
    if exact is not None:
        return ResolveResult(status=ResolveStatus.OK, entity=exact)

    hits = [e for friendly_name, e in name_map.items() if key in friendly_name]
    if len(hits) == 1:
        return ResolveResult(status=ResolveStatus.OK, entity=hits[0])
    if len(hits) > 1:
        return ResolveResult(status=ResolveStatus.AMBIGUOUS, candidates=tuple(hits))
    return ResolveResult(status=ResolveStatus.NOT_FOUND)
