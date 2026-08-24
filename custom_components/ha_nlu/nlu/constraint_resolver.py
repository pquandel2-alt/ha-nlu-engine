"""Constraint Resolver (V6 architecture plan, V6.9): finds every entity that
satisfies ALL given constraints, before any Quantity is applied - "search
first, then take N" rather than "take N, then check" (see
docs/architecture-v6.md section 6 and Brain node
755ef579-e0ba-43b7-bba9-1596c11854cd's V6.9 worked description: "Resolver
sucht zuerst Entities, die ALLE Constraints erfuellen - erst danach wird
Quantity angewendet").

Deliberately does not duplicate ``entities.resolve_entities_by_domain()``'s
domain/area/floor filtering (Regel 6, "no parallel search system" - see
parsers.py's own precedent comment at its ``resolve_entity_scored`` call
site) - reuses it, adding only the ``device_class``/capability filters that
function doesn't have. Capability Reasoning (V6.8): the required
``Capability`` is derived from a ``SemanticProperty`` via
``capabilities.required_capability_for_property()``, the exact same
``Capability`` enum ``validator.py`` already checks.

Deliberately out of scope here (owned elsewhere, not duplicated - Regel 6
again): name-based candidate scoring/ambiguity detection stays
``resolve_entity_scored()``'s job (V6.10, already the most mature reasoning
piece in this codebase - see docs/architecture-v6.md section 4); state
filtering stays ``nlu/semantic_state.py``/``StateQueryParser``'s job (later
Query Semantics work, V6.18); Quantity application (ALL/EXACTLY(n)/SOME/
EXCLUDE) is a caller's job on this function's result, not this resolver's.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..entities import EntitySnapshot, resolve_entities_by_domain
from .capabilities import required_capability_for_property
from .primitives import SemanticProperty


@dataclass(frozen=True)
class Constraints:
    """Which fields are set narrows the candidate search; unset (``None``)
    fields are not filtered on at all. Restricted to the constraints this
    resolver actually implements today out of the plan's full list (domain,
    device_class, area, floor, capability, state, property, quantity,
    comparison, alias, context) - state/comparison/alias/context/quantity
    stay the job of their existing owners (see module docstring)."""

    domain: str | None = None
    entity_id: str | None = None
    area_id: str | None = None
    floor_id: str | None = None
    device_class: str | None = None
    property: SemanticProperty | None = None


def resolve_candidates(
    entities: list[EntitySnapshot], constraints: Constraints
) -> list[EntitySnapshot]:
    """Every entity satisfying ALL of ``constraints`` - AND semantics, never
    OR. An all-``None`` ``Constraints`` matches every entity unchanged."""
    candidates = entities
    if constraints.entity_id is not None:
        candidates = [e for e in candidates if e.entity_id == constraints.entity_id]
    if constraints.domain is not None:
        candidates = resolve_entities_by_domain(
            constraints.domain, candidates, area_id=constraints.area_id, floor_id=constraints.floor_id
        )
    else:
        if constraints.area_id is not None:
            candidates = [e for e in candidates if e.area_id == constraints.area_id]
        if constraints.floor_id is not None:
            candidates = [e for e in candidates if e.floor_id == constraints.floor_id]

    if constraints.device_class is not None:
        candidates = [e for e in candidates if e.device_class == constraints.device_class]

    if constraints.property is not None:
        required = required_capability_for_property(constraints.property)
        if required is not None:
            candidates = [e for e in candidates if required.name in e.capabilities]

    return candidates
