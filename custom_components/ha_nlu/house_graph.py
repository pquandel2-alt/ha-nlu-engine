"""Typed, local house graph shared by reasoning, memory and planning.

The graph is deliberately descriptive: it can resolve relationships and
explain evidence, but it cannot create or execute a Home Assistant service
call.  Stable HA ids are retained internally; diagnostics use redacted ids.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable, Mapping

from .world_model import WorldModel


class NodeKind(StrEnum):
    PERSON = "person"
    FLOOR = "floor"
    AREA = "area"
    DEVICE = "device"
    ENTITY = "entity"
    GROUP = "group"
    MODE = "mode"


class RelationKind(StrEnum):
    ADJACENT_TO = "adjacent_to"
    ABOVE = "above"
    BELOW = "below"
    BELONGS_TO = "belongs_to"
    OBSERVED_BY = "observed_by"
    INFLUENCES = "influences"
    PREFERRED_DEVICE = "preferred_device"
    VOICE_ORIGIN = "voice_origin"
    LOCATED_IN = "located_in"
    CONTAINS = "contains"


class FactProvenance(StrEnum):
    OBSERVED = "observed"
    CONFIGURED = "configured"
    CONFIRMED_MEMORY = "confirmed_memory"
    DERIVED = "derived"
    STATISTICAL = "statistical"


class ConfidenceClass(StrEnum):
    CERTAIN = "certain"
    CONFIRMED = "confirmed"
    DERIVED = "derived"
    ESTIMATE = "estimate"


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: NodeKind
    label: str
    attributes: Mapping[str, object] = field(default_factory=lambda: _empty_attributes())


@dataclass(frozen=True)
class GraphRelation:
    relation_id: str
    source_id: str
    kind: RelationKind
    target_id: str
    provenance: FactProvenance
    confidence: ConfidenceClass
    observed_at: datetime | None = None

    @property
    def is_asserted_fact(self) -> bool:
        """Statistical evidence is never promoted to an asserted fact."""
        return self.provenance is not FactProvenance.STATISTICAL


@dataclass(frozen=True)
class RelationSpec:
    source_id: str
    kind: RelationKind
    target_id: str


class HouseGraph:
    """Immutable-id graph with deterministic traversal and explanations."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._relations: dict[str, GraphRelation] = {}

    @property
    def nodes(self) -> tuple[GraphNode, ...]:
        return tuple(self._nodes[key] for key in sorted(self._nodes))

    @property
    def relations(self) -> tuple[GraphRelation, ...]:
        return tuple(self._relations[key] for key in sorted(self._relations))

    def add_node(self, node: GraphNode) -> None:
        existing = self._nodes.get(node.node_id)
        if existing is not None and existing.kind is not node.kind:
            raise ValueError(f"Stabile ID {node.node_id!r} hat widersprüchliche Typen")
        self._nodes[node.node_id] = node

    def add_relation(
        self,
        source_id: str,
        kind: RelationKind,
        target_id: str,
        *,
        provenance: FactProvenance,
        confidence: ConfidenceClass,
        observed_at: datetime | None = None,
    ) -> GraphRelation:
        if source_id not in self._nodes or target_id not in self._nodes:
            raise ValueError("Beide Endpunkte einer Hausbeziehung müssen existieren")
        key = f"{source_id}\0{kind.value}\0{target_id}"
        relation_id = "rel_" + hashlib.sha256(key.encode()).hexdigest()[:20]
        relation = GraphRelation(
            relation_id,
            source_id,
            kind,
            target_id,
            provenance,
            confidence,
            observed_at,
        )
        self._relations[relation_id] = relation
        return relation

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def related(
        self,
        node_id: str,
        kind: RelationKind | None = None,
        *,
        asserted_only: bool = True,
    ) -> tuple[GraphNode, ...]:
        target_ids = {
            relation.target_id
            for relation in self._relations.values()
            if relation.source_id == node_id
            and (kind is None or relation.kind is kind)
            and (not asserted_only or relation.is_asserted_fact)
        }
        return tuple(self._nodes[item] for item in sorted(target_ids))

    def evidence(
        self, source_id: str, kind: RelationKind, target_id: str
    ) -> GraphRelation | None:
        return next(
            (
                relation
                for relation in self._relations.values()
                if relation.source_id == source_id
                and relation.kind is kind
                and relation.target_id == target_id
            ),
            None,
        )

    def redacted_diagnostics(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for node in self._nodes.values():
            counts[node.kind.value] = counts.get(node.kind.value, 0) + 1
        return {
            "node_counts": counts,
            "relation_count": len(self._relations),
            "statistical_relation_count": sum(
                relation.provenance is FactProvenance.STATISTICAL
                for relation in self._relations.values()
            ),
        }


def build_house_graph(
    world: WorldModel,
    configured_relations: Iterable[RelationSpec] = (),
) -> HouseGraph:
    """Build one graph from the same snapshots used by the language turn."""
    graph = HouseGraph()
    for floor in world.floors:
        graph.add_node(GraphNode(f"floor:{floor.floor_id}", NodeKind.FLOOR, floor.name))
    for area in world.areas:
        graph.add_node(GraphNode(f"area:{area.area_id}", NodeKind.AREA, area.name))
        floor_ids = {
            entity.floor_id
            for entity in world.entities_by_area_id.get(area.area_id, ())
            if entity.floor_id is not None
        }
        if len(floor_ids) == 1:
            floor_id = next(iter(floor_ids))
            graph.add_relation(
                f"area:{area.area_id}",
                RelationKind.LOCATED_IN,
                f"floor:{floor_id}",
                provenance=FactProvenance.OBSERVED,
                confidence=ConfidenceClass.CERTAIN,
            )
    for device in world.devices:
        graph.add_node(GraphNode(f"device:{device.device_id}", NodeKind.DEVICE, device.name))
        if device.area_id is not None and graph.node(f"area:{device.area_id}") is not None:
            graph.add_relation(
                f"device:{device.device_id}",
                RelationKind.LOCATED_IN,
                f"area:{device.area_id}",
                provenance=FactProvenance.OBSERVED,
                confidence=ConfidenceClass.CERTAIN,
            )
    now = datetime.now(timezone.utc)
    for entity in world.entities:
        kind = NodeKind.PERSON if entity.domain == "person" else NodeKind.ENTITY
        graph.add_node(
            GraphNode(
                f"entity:{entity.entity_id}",
                kind,
                entity.friendly_name,
                {
                    "domain": entity.domain,
                    "state": entity.state,
                    "capabilities": tuple(sorted(entity.capabilities)),
                    "quality": "available" if entity.state not in {"unknown", "unavailable"} else entity.state,
                },
            )
        )
        area_id = entity.area_id
        if area_id is not None and graph.node(f"area:{area_id}") is not None:
            graph.add_relation(
                f"entity:{entity.entity_id}",
                RelationKind.LOCATED_IN,
                f"area:{area_id}",
                provenance=FactProvenance.OBSERVED,
                confidence=ConfidenceClass.CERTAIN,
                observed_at=entity.last_updated or now,
            )
        device = world.device_for_entity(entity.entity_id)
        if device is not None:
            graph.add_relation(
                f"entity:{entity.entity_id}",
                RelationKind.BELONGS_TO,
                f"device:{device.device_id}",
                provenance=FactProvenance.OBSERVED,
                confidence=ConfidenceClass.CERTAIN,
                observed_at=entity.last_updated or now,
            )
    for spec in configured_relations:
        graph.add_relation(
            spec.source_id,
            spec.kind,
            spec.target_id,
            provenance=FactProvenance.CONFIGURED,
            confidence=ConfidenceClass.CONFIRMED,
        )
        if spec.kind is RelationKind.ADJACENT_TO:
            graph.add_relation(
                spec.target_id,
                spec.kind,
                spec.source_id,
                provenance=FactProvenance.DERIVED,
                confidence=ConfidenceClass.DERIVED,
            )
    return graph


def _empty_attributes() -> dict[str, object]:
    return {}


def parse_relation_specs(raw: object) -> tuple[RelationSpec, ...]:
    """Parse configured ``source | relation | target`` lines."""
    if raw is None or raw == "":
        return ()
    if not isinstance(raw, str):
        raise ValueError("Hausbeziehungen müssen Textzeilen sein")
    specs: list[RelationSpec] = []
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = tuple(part.strip() for part in line.split("|"))
        if len(parts) != 3 or not parts[0] or not parts[2]:
            raise ValueError(f"Ungültige Hausbeziehung in Zeile {line_number}")
        try:
            kind = RelationKind(parts[1])
        except ValueError as err:
            raise ValueError(
                f"Unbekannter Beziehungstyp in Zeile {line_number}"
            ) from err
        specs.append(RelationSpec(parts[0], kind, parts[2]))
        if len(specs) > 500:
            raise ValueError("Es sind höchstens 500 Hausbeziehungen erlaubt")
    return tuple(specs)
