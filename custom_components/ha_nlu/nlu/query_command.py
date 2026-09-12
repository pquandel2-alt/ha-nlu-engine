"""Typed query model shared by HomeIntent's parser and read-only executor.

    Parser -> QueryCommand
    QueryCommand -> QueryExecutor -> QueryResult   (Phase 5)
    QueryResult -> ResponseGenerator -> text        (Phase 6)

V9 extends the established ``QueryCommand`` rather than introducing another
query engine. Simple V8 commands retain their compact target/filter fields;
relational, aggregate and set queries optionally carry the compositional
``algebra`` tree below. No node contains source-language snippets or an
untyped expression dictionary.

Kept free of Home Assistant/hassil imports, same boundary as ``frame.py``/
``command.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..areas import AreaSnapshot
from ..automation_summary import AutomationSummary
from ..devices import DeviceSnapshot
from ..entities import EntitySnapshot
from ..floors import FloorSnapshot
from ..house_graph import RelationKind, TraversalDirection
from .semantic_state import SemanticState
from .primitives import SemanticProperty


class QueryScope(Enum):
    """Cardinality expectation of a query - mirrors the singular/plural split
    ``StateQueryParser``'s own docstring already documents."""

    SINGLE = auto()  # HassCheckState - exactly one entity expected, never guess (Regel 4)
    LIST = auto()  # HassStateQuery "welche ..." - list every matching entity
    COUNT = auto()  # HassStateQuery "wie viele ..." - count matching entities
    EXISTS = auto()  # HassExistsQuery - existence only, no per-entity detail
    ALL = auto()  # "Sind alle Rollläden oben?" - universal state check
    NONE = auto()  # "Ist kein Fenster offen?" - negated existence check
    LOCATIONS = auto()  # "Wo sind Fenster offen?" - unique matching rooms


class QueryTargetKind(Enum):
    """What kind of object a query searches over - ``ENTITY`` (the only kind
    before the WorldModelQuery wave) vs. ``DEVICE`` (HassDeviceQuery, "welche
    Geräte sind im Büro?" - answered from the WorldModel's device list, not
    an entity/state filter) vs. ``AUTOMATION`` (HassAutomationQuery/
    HassAutomationWhyQuery, V5.29 - answered from ``automations.yaml`` plus
    its metadata sidecar, not an entity/state filter either). Cut so a
    future further value could be added without restructuring
    ``QueryExecutor``/``ResponseGenerator`` - the ``DEVICE`` case already
    proved this extension point out before ``AUTOMATION`` reused it.
    """

    ENTITY = auto()
    DEVICE = auto()
    AUTOMATION = auto()
    AREA = auto()
    FLOOR = auto()


class RelationalOperator(Enum):
    LT = auto()
    LTE = auto()
    EQ = auto()
    GTE = auto()
    GT = auto()


@dataclass(frozen=True)
class PropertyOperand:
    """One fully grounded side of an entity-to-entity comparison."""

    entity_id: str
    property: SemanticProperty


@dataclass(frozen=True)
class RelationalComparison:
    left: PropertyOperand
    operator: RelationalOperator
    right: PropertyOperand


class QueryRelationKind(Enum):
    SAME_AREA = auto()


class SetOperator(Enum):
    INTERSECTION = auto()
    UNION = auto()
    DIFFERENCE = auto()


class AggregateKind(Enum):
    COUNT = auto()
    EXISTS = auto()
    ANY = auto()
    ALL = auto()
    MIN = auto()
    MAX = auto()
    AVG = auto()


class SortDirection(Enum):
    ASCENDING = auto()
    DESCENDING = auto()


@dataclass(frozen=True)
class QueryTraversal:
    """One bounded, explicitly directed HouseGraph relation path."""

    steps: tuple[tuple[RelationKind, TraversalDirection], ...]
    max_depth: int = 4
    asserted_only: bool = True

    def __post_init__(self) -> None:
        if not self.steps or len(self.steps) > self.max_depth or self.max_depth > 8:
            raise ValueError("Query traversal must contain 1..max_depth (<=8) hops")


class QueryExpression:
    """Marker base for the closed set of typed algebra nodes."""


@dataclass(frozen=True)
class SourceExpression(QueryExpression):
    target: "QueryTarget"


@dataclass(frozen=True)
class StateFilterExpression(QueryExpression):
    source: "QueryExpression"
    state: SemanticState


@dataclass(frozen=True)
class RelationFilterExpression(QueryExpression):
    """Keep source members reaching at least one nested-query member."""

    source: "QueryExpression"
    traversal: QueryTraversal
    nested: "QueryExpression"


@dataclass(frozen=True)
class TraverseExpression(QueryExpression):
    source: "QueryExpression"
    traversal: QueryTraversal
    target_kind: QueryTargetKind


@dataclass(frozen=True)
class SetExpression(QueryExpression):
    left: "QueryExpression"
    operator: SetOperator
    right: "QueryExpression"


@dataclass(frozen=True)
class AggregateExpression(QueryExpression):
    source: "QueryExpression"
    kind: AggregateKind


@dataclass(frozen=True)
class QuantifiedExpression(QueryExpression):
    """Evaluate ANY/ALL against an explicit matching subset."""

    source: "QueryExpression"
    matching: "QueryExpression"
    kind: AggregateKind

    def __post_init__(self) -> None:
        if self.kind not in {AggregateKind.ANY, AggregateKind.ALL}:
            raise ValueError("QuantifiedExpression supports only ANY or ALL")


@dataclass(frozen=True)
class GroupExpression(QueryExpression):
    source: "QueryExpression"
    traversal: QueryTraversal
    group_kind: QueryTargetKind
    aggregate: AggregateKind = AggregateKind.COUNT


@dataclass(frozen=True)
class ThresholdExpression(QueryExpression):
    """Select groups whose typed aggregate satisfies a numeric threshold."""

    source: GroupExpression
    operator: RelationalOperator
    value: float


@dataclass(frozen=True)
class MeasurementExpression(QueryExpression):
    source: "QueryExpression"
    property: SemanticProperty


@dataclass(frozen=True)
class CompareExpression(QueryExpression):
    left: "QueryExpression"
    operator: RelationalOperator
    right: "QueryExpression"


@dataclass(frozen=True)
class OrderExpression(QueryExpression):
    source: "QueryExpression"
    key: MeasurementExpression | GroupExpression
    direction: SortDirection


@dataclass(frozen=True)
class LimitExpression(QueryExpression):
    source: "QueryExpression"
    count: int

    def __post_init__(self) -> None:
        if self.count < 1 or self.count > 1000:
            raise ValueError("Query limit must be between 1 and 1000")


@dataclass(frozen=True)
class RelationConstraint:
    """A registry-proven relationship anchored at one live entity."""

    kind: QueryRelationKind
    anchor_entity_id: str


@dataclass(frozen=True)
class QueryTarget:
    """What a query searches over, before any state filter is applied.

    ``entity_id`` is set for ``QueryScope.SINGLE`` (HassCheckState's resolved
    ``{name}``) and, optionally, for ``QueryTargetKind.AUTOMATION`` targets
    (HassAutomationQuery/HassAutomationWhyQuery's resolved ``{name}`` - "was
    schaltet X?"/"warum geht X an?" - filters to automations referencing
    that entity; unset means "list every automation", V5.29).
    ``device_class`` narrows ``domain`` further, same "domain:device_class"
    split ``StateQueryParser._device_class_candidates`` already performs.
    ``domain`` is ``None`` for ``QueryTargetKind.DEVICE``/``AUTOMATION``
    targets - both are cross-domain, there is no single domain to name.
    """

    domain: str | None = None
    device_class: str | None = None
    area: AreaSnapshot | None = None
    floor_id: str | None = None
    entity_id: str | None = None
    kind: QueryTargetKind = QueryTargetKind.ENTITY


@dataclass(frozen=True)
class QueryFilter:
    """The state condition candidate entities must satisfy.

    ``state`` is ``None`` only for HassExistsQuery's bare-existence form
    ("gibt es Fenster?", no {state}/{state_adj} word at all) - every match
    passes, cardinality alone is the answer.
    """

    state: SemanticState | None = None
    relational: RelationalComparison | None = None
    relationship: RelationConstraint | None = None


@dataclass(frozen=True)
class QueryCommand:
    """The fully-resolved counterpart to a query ``SemanticFrame`` - mirrors
    ``nlu/command.py``'s ``SemanticCommand`` split for ordinary commands."""

    intent: str
    scope: QueryScope
    target: QueryTarget
    filter: QueryFilter
    algebra: QueryExpression | None = None


class QueryResultStatus(Enum):
    """Distinguishes "not found" from "found but nothing matched" (Sections
    19-20) - collapsed into a single ``None``/miss in today's pre-Phase-7
    ``StateQueryParser``/``QUERY_INTENTS`` pipeline."""

    MATCHED = auto()  # 1+ entities passed the filter (or, for EXISTS, existence confirmed)
    EMPTY = auto()  # target resolved fine, 0 entities passed the filter - a normal answer, not an error
    TARGET_NOT_FOUND = auto()  # the named {name}/{area} itself didn't resolve to anything known
    AMBIGUOUS = auto()  # SINGLE scope, 2+ candidates, no quantifier - never guess (Regel 4)


@dataclass(frozen=True)
class GroupedValue:
    group_id: str
    label: str
    member_ids: tuple[str, ...]
    value: int | float | bool


@dataclass(frozen=True)
class ReasoningStep:
    operation: str
    input_ids: tuple[str, ...] = ()
    output_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True)
class ReasoningTrace:
    steps: tuple[ReasoningStep, ...]


@dataclass(frozen=True)
class QueryResult:
    status: QueryResultStatus
    entities: tuple[EntitySnapshot, ...] = ()
    # Complete registry-backed set examined before state filtering. This is
    # deliberately separate from ``entities`` so surface realization can say
    # "all" or "only" only when completeness is actually proven.
    considered_entities: tuple[EntitySnapshot, ...] = ()
    devices: tuple[DeviceSnapshot, ...] = ()
    automations: tuple[AutomationSummary, ...] = ()
    command: QueryCommand | None = None
    areas: tuple[AreaSnapshot, ...] = ()
    floors: tuple[FloorSnapshot, ...] = ()
    member_ids: tuple[str, ...] = ()
    scalar: int | float | bool | None = None
    groups: tuple[GroupedValue, ...] = ()
    trace: ReasoningTrace | None = None
