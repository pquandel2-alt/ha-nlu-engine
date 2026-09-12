"""QueryExecutor (HomeIntent v4.2.1 plan, Section 12/Phase 5): the second
stage of the Query pipeline - ``QueryCommand`` -> ``QueryResult``.

Read-only by construction: this module has no Home Assistant import and
never calls (nor could call) ``hass.services.async_call()`` - Regel 3/
Sections 16+46 ("Queries never execute a service call"). It only filters an
already-resolved candidate list by live entity state
(``matches_semantic_state``, Regel 5 - never cached) and classifies the
outcome into a ``QueryResultStatus``.

Candidate resolution itself (name/area/domain/device_class -> a list of
``EntitySnapshot``) stays where it already lives (``areas.py``/
``entities.py``, Regel 6 - no parallel search system) and is the caller's
job, same division of labor ``StateQueryParser`` already follows internally
today. Phase 7 wires a caller onto this class non-destructively; until then
nothing in ``engine.py``/``parsers.py`` constructs a ``QueryExecutor``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..automation_summary import AutomationSummary
from ..entities import EntitySnapshot
from ..world_model import WorldModel
from ..house_graph import (
    RelationKind,
    TraversalDirection,
    TraversalMatch,
    TraversalStep,
)
from .query_command import (
    AggregateExpression,
    AggregateKind,
    CompareExpression,
    GroupExpression,
    GroupedValue,
    LimitExpression,
    MeasurementExpression,
    OrderExpression,
    PropertyOperand,
    QueryCommand,
    QueryExpression,
    QuantifiedExpression,
    QueryRelationKind,
    QueryResult,
    QueryResultStatus,
    QueryScope,
    QueryTargetKind,
    ReasoningStep,
    ReasoningTrace,
    RelationFilterExpression,
    RelationalOperator,
    SetExpression,
    SetOperator,
    SortDirection,
    SourceExpression,
    StateFilterExpression,
    ThresholdExpression,
    TraverseExpression,
)
from .primitives import SemanticProperty
from .semantic_state import matches_semantic_state
from .unit_reasoning import normalize_measurement


@dataclass
class _Evaluation:
    kind: QueryTargetKind
    member_ids: tuple[str, ...] = ()
    scalar: int | float | bool | None = None
    groups: tuple[GroupedValue, ...] = ()
    values: dict[str, float] = field(default_factory=dict)
    steps: list[ReasoningStep] = field(default_factory=list)
    ambiguous: bool = False
    unsupported: bool = False


class QueryExecutor:
    """Stateless - one shared instance is fine, same as ``NluEngine``'s other
    parser-adjacent helpers. ``execute()`` takes the caller's already-scoped
    candidate list (domain/device_class/area already applied) and applies
    only the state filter plus cardinality classification.
    """

    def execute(
        self,
        command: QueryCommand,
        candidates: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        automations: tuple[AutomationSummary, ...] = (),
    ) -> QueryResult:
        if command.algebra is not None:
            return self._execute_algebra(command, world_model)
        if command.filter.relational is not None:
            return self._execute_relational(command, candidates, world_model)
        if command.filter.relationship is not None:
            return self._execute_relationship(command, candidates, world_model)
        if command.target.kind is QueryTargetKind.DEVICE:
            return self._execute_device(command, world_model)
        if command.target.kind is QueryTargetKind.AUTOMATION:
            return self._execute_automation(command, candidates, automations)
        if command.scope is QueryScope.SINGLE:
            return self._execute_single(command, candidates)
        return self._execute_plural(command, candidates)

    @classmethod
    def _execute_algebra(
        cls, command: QueryCommand, world_model: WorldModel | None
    ) -> QueryResult:
        if world_model is None:
            return QueryResult(QueryResultStatus.TARGET_NOT_FOUND, command=command)
        algebra = command.algebra
        if algebra is None:
            return QueryResult(QueryResultStatus.TARGET_NOT_FOUND, command=command)
        cost = cls._query_cost(algebra, len(world_model.entities))
        if cost > 100_000:
            return QueryResult(
                QueryResultStatus.TARGET_NOT_FOUND,
                trace=ReasoningTrace((ReasoningStep("cost", detail=str(cost)),)),
                command=command,
            )
        evaluated = cls._evaluate(algebra, world_model)
        trace = ReasoningTrace(tuple(evaluated.steps))
        if evaluated.ambiguous:
            return QueryResult(QueryResultStatus.AMBIGUOUS, trace=trace, command=command)
        if evaluated.unsupported:
            return QueryResult(QueryResultStatus.TARGET_NOT_FOUND, trace=trace, command=command)
        entities = tuple(
            entity
            for member_id in evaluated.member_ids
            if member_id.startswith("entity:")
            and (entity := world_model.entities_by_id.get(member_id.removeprefix("entity:")))
            is not None
        )
        area_by_id = {area.area_id: area for area in world_model.areas}
        floor_by_id = {floor.floor_id: floor for floor in world_model.floors}
        areas = tuple(
            area
            for member_id in evaluated.member_ids
            if member_id.startswith("area:")
            and (area := area_by_id.get(member_id.removeprefix("area:"))) is not None
        )
        floors = tuple(
            floor
            for member_id in evaluated.member_ids
            if member_id.startswith("floor:")
            and (floor := floor_by_id.get(member_id.removeprefix("floor:"))) is not None
        )
        matched = bool(evaluated.member_ids) or bool(evaluated.groups)
        if isinstance(evaluated.scalar, bool):
            matched = evaluated.scalar
        elif evaluated.scalar is not None:
            matched = True
        return QueryResult(
            QueryResultStatus.MATCHED if matched else QueryResultStatus.EMPTY,
            entities=entities,
            areas=areas,
            floors=floors,
            member_ids=evaluated.member_ids,
            scalar=evaluated.scalar,
            groups=evaluated.groups,
            trace=trace,
            command=command,
        )

    @classmethod
    def _evaluate(cls, expression: QueryExpression, world: WorldModel) -> _Evaluation:
        graph = world.house_graph
        if isinstance(expression, SourceExpression):
            target = expression.target
            if target.kind is QueryTargetKind.ENTITY:
                members = tuple(
                    f"entity:{entity.entity_id}"
                    for entity in world.select_entities(
                        domain=target.domain,
                        device_class=target.device_class,
                        area_id=target.area.area_id if target.area is not None else None,
                        floor_id=target.floor_id,
                    )
                    if target.entity_id is None or entity.entity_id == target.entity_id
                )
            elif target.kind is QueryTargetKind.AREA:
                members = tuple(
                    f"area:{area.area_id}" for area in world.areas
                    if target.area is None or area.area_id == target.area.area_id
                )
                if target.floor_id is not None:
                    floor_node = f"floor:{target.floor_id}"
                    members = tuple(
                        member for member in members
                        if graph.traverse(
                            (member,),
                            (TraversalStep(RelationKind.LOCATED_IN),),
                        )
                        and graph.traverse(
                            (member,),
                            (TraversalStep(RelationKind.LOCATED_IN),),
                        )[0].node.node_id == floor_node
                    )
            elif target.kind is QueryTargetKind.FLOOR:
                members = tuple(
                    f"floor:{floor.floor_id}" for floor in world.floors
                    if target.floor_id is None or floor.floor_id == target.floor_id
                )
            elif target.kind is QueryTargetKind.DEVICE:
                members = tuple(
                    f"device:{device.device_id}" for device in world.devices
                    if target.area is None or device.area_id == target.area.area_id
                )
            else:
                return _Evaluation(target.kind, unsupported=True)
            members = tuple(sorted(members))
            return _Evaluation(
                target.kind,
                members,
                steps=[ReasoningStep("source", output_ids=members, detail=target.kind.name.lower())],
            )

        if isinstance(expression, StateFilterExpression):
            source = cls._evaluate(expression.source, world)
            state_matches = tuple(
                member_id for member_id in source.member_ids
                if member_id.startswith("entity:")
                and (entity := world.entities_by_id.get(member_id.removeprefix("entity:")))
                is not None
                and matches_semantic_state(entity, expression.state)
            )
            source.steps.append(ReasoningStep(
                "filter_state", source.member_ids, state_matches,
                detail=expression.state.name.lower(),
            ))
            source.member_ids = state_matches
            return source

        if isinstance(expression, TraverseExpression):
            source = cls._evaluate(expression.source, world)
            matches = graph.traverse(
                source.member_ids,
                tuple(TraversalStep(kind, direction) for kind, direction in expression.traversal.steps),
                asserted_only=expression.traversal.asserted_only,
                max_depth=expression.traversal.max_depth,
            )
            members = tuple(match.node.node_id for match in matches)
            source.steps.append(ReasoningStep(
                "traverse", source.member_ids, members,
                tuple(edge.relation_id for match in matches for edge in match.path),
                detail="/".join(kind.value for kind, _ in expression.traversal.steps),
            ))
            source.kind = expression.target_kind
            source.member_ids = members
            return source

        if isinstance(expression, RelationFilterExpression):
            source = cls._evaluate(expression.source, world)
            nested = cls._evaluate(expression.nested, world)
            accepted = set(nested.member_ids)
            matched_ids: list[str] = []
            filter_relation_ids: list[str] = []
            steps = tuple(
                TraversalStep(kind, direction)
                for kind, direction in expression.traversal.steps
            )
            for member_id in source.member_ids:
                if len(steps) == 1:
                    step = steps[0]
                    nodes = (
                        graph.related(
                            member_id,
                            step.kind,
                            asserted_only=expression.traversal.asserted_only,
                        )
                        if step.direction is TraversalDirection.OUTGOING
                        else graph.sources(
                            member_id,
                            step.kind,
                            asserted_only=expression.traversal.asserted_only,
                        )
                    )
                    reached = tuple(
                        TraversalMatch(
                            node,
                            (
                                relation,
                            ) if (
                                relation := graph.evidence(
                                    member_id if step.direction is TraversalDirection.OUTGOING else node.node_id,
                                    step.kind,
                                    node.node_id if step.direction is TraversalDirection.OUTGOING else member_id,
                                )
                            ) is not None else (),
                        )
                        for node in nodes
                    )
                else:
                    reached = graph.traverse(
                        (member_id,), steps,
                        asserted_only=expression.traversal.asserted_only,
                        max_depth=expression.traversal.max_depth,
                    )
                proving = tuple(item for item in reached if item.node.node_id in accepted)
                if proving:
                    matched_ids.append(member_id)
                    filter_relation_ids.extend(
                        edge.relation_id for item in proving for edge in item.path
                    )
            source.steps.extend(nested.steps)
            source.steps.append(ReasoningStep(
                "filter_relation", source.member_ids, tuple(matched_ids),
                tuple(sorted(set(filter_relation_ids))),
            ))
            source.member_ids = tuple(matched_ids)
            source.ambiguous = source.ambiguous or nested.ambiguous
            source.unsupported = source.unsupported or nested.unsupported
            return source

        if isinstance(expression, SetExpression):
            left = cls._evaluate(expression.left, world)
            right = cls._evaluate(expression.right, world)
            left_set, right_set = set(left.member_ids), set(right.member_ids)
            if expression.operator is SetOperator.INTERSECTION:
                result = left_set & right_set
            elif expression.operator is SetOperator.UNION:
                result = left_set | right_set
            else:
                result = left_set - right_set
            members = tuple(sorted(result))
            return _Evaluation(
                left.kind,
                members,
                steps=[*left.steps, *right.steps, ReasoningStep(
                    f"set_{expression.operator.name.lower()}",
                    (*left.member_ids, *right.member_ids), members,
                )],
                ambiguous=left.ambiguous or right.ambiguous,
                unsupported=left.unsupported or right.unsupported,
            )

        if isinstance(expression, AggregateExpression):
            source = cls._evaluate(expression.source, world)
            count = len(source.member_ids)
            if expression.kind is AggregateKind.COUNT:
                scalar: int | float | bool = count
            elif expression.kind is AggregateKind.EXISTS:
                scalar = count > 0
            elif source.values and expression.kind is AggregateKind.MIN:
                scalar = min(source.values.values())
            elif source.values and expression.kind is AggregateKind.MAX:
                scalar = max(source.values.values())
            elif source.values and expression.kind is AggregateKind.AVG:
                scalar = sum(source.values.values()) / len(source.values)
            else:
                source.unsupported = True
                return source
            source.scalar = scalar
            source.steps.append(ReasoningStep(
                f"aggregate_{expression.kind.name.lower()}",
                source.member_ids,
                detail=str(scalar),
            ))
            return source

        if isinstance(expression, QuantifiedExpression):
            source = cls._evaluate(expression.source, world)
            matching = cls._evaluate(expression.matching, world)
            source_ids = set(source.member_ids)
            matching_ids = source_ids & set(matching.member_ids)
            scalar = (
                bool(matching_ids)
                if expression.kind is AggregateKind.ANY
                else bool(source_ids) and source_ids <= matching_ids
            )
            source.scalar = scalar
            source.steps.extend(matching.steps)
            source.steps.append(ReasoningStep(
                f"quantifier_{expression.kind.name.lower()}",
                source.member_ids,
                tuple(sorted(matching_ids)),
                detail=str(scalar),
            ))
            source.ambiguous = source.ambiguous or matching.ambiguous
            source.unsupported = source.unsupported or matching.unsupported
            return source

        if isinstance(expression, GroupExpression):
            source = cls._evaluate(expression.source, world)
            grouped: dict[str, list[str]] = {}
            group_relation_ids: set[str] = set()
            traversal_steps = tuple(
                TraversalStep(kind, direction)
                for kind, direction in expression.traversal.steps
            )
            for member_id in source.member_ids:
                if len(traversal_steps) == 1:
                    step = traversal_steps[0]
                    nodes = (
                        graph.related(member_id, step.kind)
                        if step.direction is TraversalDirection.OUTGOING
                        else graph.sources(member_id, step.kind)
                    )
                    matches = tuple(
                        TraversalMatch(
                            node,
                            (
                                relation,
                            ) if (
                                relation := graph.evidence(
                                    member_id if step.direction is TraversalDirection.OUTGOING else node.node_id,
                                    step.kind,
                                    node.node_id if step.direction is TraversalDirection.OUTGOING else member_id,
                                )
                            ) is not None else (),
                        )
                        for node in nodes
                    )
                else:
                    matches = graph.traverse(
                        (member_id,), traversal_steps,
                        asserted_only=expression.traversal.asserted_only,
                        max_depth=expression.traversal.max_depth,
                    )
                for match in matches:
                    grouped.setdefault(match.node.node_id, []).append(member_id)
                    group_relation_ids.update(edge.relation_id for edge in match.path)
            if expression.aggregate is not AggregateKind.COUNT:
                source.unsupported = True
                return source
            group_values: list[GroupedValue] = []
            for group_id, group_members in sorted(grouped.items()):
                group_node = graph.node(group_id)
                unique_members = tuple(sorted(set(group_members)))
                group_values.append(GroupedValue(
                    group_id,
                    group_node.label if group_node is not None else group_id,
                    unique_members,
                    len(unique_members),
                ))
            groups = tuple(group_values)
            source.groups = groups
            source.values = {group.group_id: float(group.value) for group in groups}
            source.steps.append(ReasoningStep(
                "group_count", source.member_ids,
                tuple(group.group_id for group in groups),
                tuple(sorted(group_relation_ids)),
            ))
            return source

        if isinstance(expression, MeasurementExpression):
            source = cls._evaluate(expression.source, world)
            property_node = f"property:{expression.property.name.lower()}"
            measuring = {
                node.node_id
                for node in graph.sources(property_node, RelationKind.MEASURES)
            }
            values: dict[str, float] = {}
            for member_id in source.member_ids:
                candidates: set[str]
                if member_id.startswith("entity:"):
                    candidates = {member_id} & measuring
                elif member_id.startswith("area:"):
                    candidates = {
                        node.node_id
                        for node in graph.sources(member_id, RelationKind.LOCATED_IN)
                    } & measuring
                elif member_id.startswith("device:"):
                    candidates = {
                        node.node_id
                        for node in graph.sources(member_id, RelationKind.BELONGS_TO)
                    } & measuring
                elif member_id.startswith("floor:"):
                    area_ids = {
                        node.node_id
                        for node in graph.sources(member_id, RelationKind.LOCATED_IN)
                        if node.node_id.startswith("area:")
                    }
                    candidates = {
                        node.node_id
                        for area_id in area_ids
                        for node in graph.sources(area_id, RelationKind.LOCATED_IN)
                    } & measuring
                else:
                    candidates = set()
                if len(candidates) > 1:
                    preferred = {
                        item.node.node_id for item in graph.traverse(
                            (member_id,),
                            (TraversalStep(RelationKind.PREFERRED_MEASUREMENT),),
                        )
                    } & candidates
                    candidates = preferred if len(preferred) == 1 else candidates
                if len(candidates) != 1:
                    if len(candidates) > 1:
                        source.ambiguous = True
                    continue
                sensor_id = next(iter(candidates)).removeprefix("entity:")
                entity = world.entities_by_id.get(sensor_id)
                if entity is None or entity.state in {"unknown", "unavailable"}:
                    continue
                raw = entity.attributes.get({
                    SemanticProperty.TEMPERATURE: "current_temperature",
                    SemanticProperty.HUMIDITY: "humidity",
                    SemanticProperty.POWER: "power",
                    SemanticProperty.ENERGY: "energy",
                    SemanticProperty.BATTERY: "battery_level",
                    SemanticProperty.BRIGHTNESS: "brightness",
                }.get(expression.property, ""), entity.state)
                try:
                    normalized = normalize_measurement(float(raw), entity.unit, expression.property)
                except (TypeError, ValueError):
                    normalized = None
                if normalized is None:
                    source.unsupported = True
                    continue
                values[member_id] = normalized.value
            source.values = values
            source.member_ids = tuple(item for item in source.member_ids if item in values)
            source.steps.append(ReasoningStep(
                "measure", output_ids=source.member_ids,
                detail=expression.property.name.lower(),
            ))
            return source

        if isinstance(expression, ThresholdExpression):
            source = cls._evaluate(expression.source, world)
            predicate = {
                RelationalOperator.LT: lambda value: value < expression.value,
                RelationalOperator.LTE: lambda value: value <= expression.value,
                RelationalOperator.EQ: lambda value: value == expression.value,
                RelationalOperator.GTE: lambda value: value >= expression.value,
                RelationalOperator.GT: lambda value: value > expression.value,
            }[expression.operator]
            groups = tuple(group for group in source.groups if predicate(float(group.value)))
            members = tuple(group.group_id for group in groups)
            source.groups = groups
            source.member_ids = members
            source.kind = expression.source.group_kind
            source.steps.append(ReasoningStep(
                "filter_aggregate", output_ids=members,
                detail=f"{expression.operator.name.lower()} {expression.value:g}",
            ))
            return source

        if isinstance(expression, CompareExpression):
            left = cls._evaluate(expression.left, world)
            right = cls._evaluate(expression.right, world)
            if len(right.values) != 1 or not left.values:
                left.ambiguous = left.ambiguous or len(right.values) > 1
                left.unsupported = left.unsupported or not right.values
                left.steps.extend(right.steps)
                return left
            reference = next(iter(right.values.values()))
            predicate = {
                RelationalOperator.LT: lambda value: value < reference,
                RelationalOperator.LTE: lambda value: value <= reference,
                RelationalOperator.EQ: lambda value: value == reference,
                RelationalOperator.GTE: lambda value: value >= reference,
                RelationalOperator.GT: lambda value: value > reference,
            }[expression.operator]
            members = tuple(item for item in left.member_ids if predicate(left.values[item]))
            left.steps.extend(right.steps)
            left.steps.append(ReasoningStep(
                "compare", left.member_ids, members,
                detail=f"{expression.operator.name.lower()} {reference:g}",
            ))
            left.member_ids = members
            left.values = {key: value for key, value in left.values.items() if key in members}
            left.ambiguous = left.ambiguous or right.ambiguous
            left.unsupported = left.unsupported or right.unsupported
            return left

        if isinstance(expression, OrderExpression):
            source = cls._evaluate(expression.source, world)
            key = cls._evaluate(expression.key, world)
            if key.ambiguous or key.unsupported or not key.values:
                source.ambiguous = source.ambiguous or key.ambiguous
                source.unsupported = source.unsupported or key.unsupported or not key.values
                source.steps.extend(key.steps)
                return source
            reverse = expression.direction is SortDirection.DESCENDING
            members = tuple(sorted(
                (item for item in source.member_ids if item in key.values),
                key=lambda item: (key.values[item], item),
                reverse=reverse,
            ))
            source.steps.extend(key.steps)
            source.steps.append(ReasoningStep(
                "order", source.member_ids, members,
                detail=expression.direction.name.lower(),
            ))
            source.member_ids = members
            source.values = key.values
            return source

        if isinstance(expression, LimitExpression):
            source = cls._evaluate(expression.source, world)
            limited = source.member_ids[:expression.count]
            source.steps.append(ReasoningStep(
                "limit", source.member_ids, limited, detail=str(expression.count)
            ))
            source.member_ids = limited
            return source

        return _Evaluation(QueryTargetKind.ENTITY, unsupported=True)

    @classmethod
    def _query_cost(cls, expression: QueryExpression, candidate_count: int) -> int:
        """Conservative deterministic complexity score; never changes meaning."""
        if isinstance(expression, SourceExpression):
            return max(1, candidate_count)
        if isinstance(expression, StateFilterExpression):
            return cls._query_cost(expression.source, candidate_count) + candidate_count
        if isinstance(expression, TraverseExpression):
            return cls._query_cost(expression.source, candidate_count) + candidate_count * len(expression.traversal.steps)
        if isinstance(expression, RelationFilterExpression):
            return (
                cls._query_cost(expression.source, candidate_count)
                + cls._query_cost(expression.nested, candidate_count)
                + candidate_count * len(expression.traversal.steps)
            )
        if isinstance(expression, SetExpression):
            return cls._query_cost(expression.left, candidate_count) + cls._query_cost(expression.right, candidate_count)
        if isinstance(expression, QuantifiedExpression):
            return cls._query_cost(expression.source, candidate_count) + cls._query_cost(expression.matching, candidate_count)
        if isinstance(expression, (AggregateExpression, MeasurementExpression, LimitExpression)):
            return cls._query_cost(expression.source, candidate_count) + candidate_count
        if isinstance(expression, GroupExpression):
            return cls._query_cost(expression.source, candidate_count) + candidate_count * (len(expression.traversal.steps) + 1)
        if isinstance(expression, ThresholdExpression):
            return cls._query_cost(expression.source, candidate_count) + candidate_count
        if isinstance(expression, CompareExpression):
            return cls._query_cost(expression.left, candidate_count) + cls._query_cost(expression.right, candidate_count)
        if isinstance(expression, OrderExpression):
            return cls._query_cost(expression.source, candidate_count) + cls._query_cost(expression.key, candidate_count) + candidate_count * 2
        return 100_001

    @staticmethod
    def _execute_relationship(
        command: QueryCommand,
        candidates: list[EntitySnapshot],
        world_model: WorldModel | None,
    ) -> QueryResult:
        relationship = command.filter.relationship
        if relationship is None or world_model is None:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        if relationship.kind is not QueryRelationKind.SAME_AREA:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        graph = world_model.house_graph
        anchor_id = f"entity:{relationship.anchor_entity_id}"
        areas = graph.related(anchor_id, RelationKind.LOCATED_IN)
        if len(areas) != 1:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        related_ids = {
            node.node_id.removeprefix("entity:")
            for node in graph.sources(areas[0].node_id, RelationKind.LOCATED_IN)
            if node.node_id.startswith("entity:")
        }
        candidate_ids = {entity.entity_id for entity in candidates}
        matched = tuple(
            entity
            for entity_id in sorted(related_ids & candidate_ids)
            if entity_id != relationship.anchor_entity_id
            and (entity := world_model.entities_by_id.get(entity_id)) is not None
        )
        return QueryResult(
            status=(QueryResultStatus.MATCHED if matched else QueryResultStatus.EMPTY),
            entities=matched,
            considered_entities=tuple(candidates),
            command=command,
        )

    @staticmethod
    def _operand_value(
        operand: PropertyOperand, world_model: WorldModel
    ) -> tuple[float, str | None] | None:
        entity = world_model.entities_by_id.get(operand.entity_id)
        if entity is None or entity.state in {"unknown", "unavailable"}:
            return None
        attribute_by_property = {
            SemanticProperty.TEMPERATURE: "current_temperature",
            SemanticProperty.BRIGHTNESS: "brightness",
            SemanticProperty.POSITION: "current_position",
            SemanticProperty.POWER: "power",
            SemanticProperty.ENERGY: "energy",
            SemanticProperty.HUMIDITY: "humidity",
            SemanticProperty.BATTERY: "battery_level",
        }
        raw = entity.attributes.get(attribute_by_property.get(operand.property, ""))
        if raw is None:
            raw = entity.state
        try:
            return float(raw), entity.unit
        except (TypeError, ValueError):
            return None

    @classmethod
    def _execute_relational(
        cls,
        command: QueryCommand,
        candidates: list[EntitySnapshot],
        world_model: WorldModel | None,
    ) -> QueryResult:
        comparison = command.filter.relational
        if comparison is None or world_model is None:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        left_reading = cls._operand_value(comparison.left, world_model)
        right_reading = cls._operand_value(comparison.right, world_model)
        if left_reading is None or right_reading is None:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        left, left_unit = left_reading
        right, right_unit = right_reading
        if comparison.left.property is not comparison.right.property:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        normalized_left = normalize_measurement(
            left, left_unit, comparison.left.property
        )
        normalized_right = normalize_measurement(
            right, right_unit, comparison.right.property
        )
        if (
            normalized_left is None
            or normalized_right is None
            or normalized_left.unit != normalized_right.unit
        ):
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        left = normalized_left.value
        right = normalized_right.value
        predicates = {
            RelationalOperator.LT: left < right,
            RelationalOperator.LTE: left <= right,
            RelationalOperator.EQ: left == right,
            RelationalOperator.GTE: left >= right,
            RelationalOperator.GT: left > right,
        }
        by_id = {entity.entity_id: entity for entity in candidates}
        considered = tuple(
            entity
            for entity_id in (comparison.left.entity_id, comparison.right.entity_id)
            if (entity := by_id.get(entity_id)) is not None
        )
        left_entity = world_model.entities_by_id.get(comparison.left.entity_id)
        return QueryResult(
            status=(
                QueryResultStatus.MATCHED
                if predicates[comparison.operator]
                else QueryResultStatus.EMPTY
            ),
            entities=(left_entity,) if left_entity is not None else (),
            considered_entities=considered,
            command=command,
        )

    @staticmethod
    def _execute_automation(
        command: QueryCommand,
        candidates: list[EntitySnapshot],
        automations: tuple[AutomationSummary, ...],
    ) -> QueryResult:
        """AUTOMATION-scope queries (HassAutomationQuery/HassAutomationWhyQuery,
        V5.29). No ``target.entity_id`` ("welche Automationen gibt es?")
        lists every automation the caller read; a resolved ``entity_id``
        ("was schaltet X?"/"warum geht X an?") narrows to automations whose
        ``referenced_entity_ids`` mention it - see ``AutomationSummary``'s
        own docstring for why that's a deliberately shallow "mentions X
        somewhere", not a re-derivation of actual trigger/action causation.

        ``candidates`` carries the already-resolved target entity (same
        calling shape ``_execute_single`` uses for its own ``entity_id``
        membership check) purely so the response can name it - membership
        itself is decided by ``entity_id in referenced_entity_ids`` alone.
        Zero matches is EMPTY, not an error - same "0 is a normal answer"
        precedent ``_execute_plural`` already establishes.
        """
        entity_id = command.target.entity_id
        if entity_id is None:
            matched = automations
        else:
            matched = tuple(a for a in automations if entity_id in a.referenced_entity_ids)
        status = QueryResultStatus.MATCHED if matched else QueryResultStatus.EMPTY
        entity = candidates[0] if entity_id is not None and candidates else None
        return QueryResult(
            status=status,
            entities=(entity,) if entity is not None else (),
            automations=tuple(matched),
            command=command,
        )

    @staticmethod
    def _execute_device(command: QueryCommand, world_model: WorldModel | None) -> QueryResult:
        """DEVICE-scope queries (HassDeviceQuery, "welche Geräte sind im
        Büro?") answer from the WorldModel's device list, not an entity/state
        filter - no world_model or no resolved area means no answer, never a
        crash or an invented "all devices" fallback (Regel: niemals raten).
        """
        if world_model is None or command.target.area is None:
            return QueryResult(status=QueryResultStatus.EMPTY, command=command)
        devices = world_model.devices_in_area(command.target.area.area_id)
        if command.filter.state is not None:
            state = command.filter.state
            devices = tuple(
                d
                for d in devices
                if any(
                    matches_semantic_state(e, state)
                    for e in world_model.entities_for_device(d.device_id)
                )
            )
        status = QueryResultStatus.MATCHED if devices else QueryResultStatus.EMPTY
        return QueryResult(status=status, devices=tuple(devices), command=command)

    @staticmethod
    def _execute_single(command: QueryCommand, candidates: list[EntitySnapshot]) -> QueryResult:
        """SINGLE queries (HassCheckState) always resolve to exactly one
        entity - whether or not its *current* state satisfies the requested
        filter is the answer itself (``Nein, ... ist nicht offen.`` is a
        MATCHED result, not EMPTY), so no state filtering happens here.

        Two calling shapes are supported: the target already carries a
        resolved ``entity_id`` (today's ``StateQueryParser`` - it already
        did the ambiguity check itself via ``resolve_entity_scored``, Regel
        4), or it doesn't, in which case this method does that cardinality
        check itself directly against ``candidates`` - lets a future caller
        skip duplicating that logic and gives ``AMBIGUOUS``/``TARGET_NOT_FOUND``
        real, independently testable code paths.
        """
        if command.target.entity_id is not None:
            match = next(
                (e for e in candidates if e.entity_id == command.target.entity_id), None
            )
            if match is None:
                return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
            return QueryResult(status=QueryResultStatus.MATCHED, entities=(match,), command=command)

        if not candidates:
            return QueryResult(status=QueryResultStatus.TARGET_NOT_FOUND, command=command)
        if len(candidates) > 1:
            return QueryResult(
                status=QueryResultStatus.AMBIGUOUS, entities=tuple(candidates), command=command
            )
        return QueryResult(status=QueryResultStatus.MATCHED, entities=(candidates[0],), command=command)

    @staticmethod
    def _execute_plural(command: QueryCommand, candidates: list[EntitySnapshot]) -> QueryResult:
        """LIST/COUNT/EXISTS all share one filtering rule: keep candidates
        whose live state matches the requested filter (or every candidate,
        for EXISTS's bare-existence form with no {state}/{state_adj} word -
        ``filter.state is None``). COUNT differs from LIST only in how
        ``ResponseGenerator`` (Phase 6) phrases the same matched set, not in
        which entities match - so both take this one branch.

        Zero matches is EMPTY, not an error - HomeIntent v4.2.1 Section 19,
        "Keine Fenster sind offen." is a normal answer.
        """
        state = command.filter.state
        if command.scope is QueryScope.ALL:
            all_match = bool(candidates) and state is not None and all(
                matches_semantic_state(entity, state) for entity in candidates
            )
            return QueryResult(
                status=(
                    QueryResultStatus.MATCHED
                    if all_match
                    else QueryResultStatus.EMPTY
                ),
                entities=tuple(candidates),
                considered_entities=tuple(candidates),
                command=command,
            )
        if command.scope is QueryScope.NONE:
            none_match = bool(candidates) and state is not None and not any(
                matches_semantic_state(entity, state) for entity in candidates
            )
            return QueryResult(
                status=QueryResultStatus.MATCHED if none_match else QueryResultStatus.EMPTY,
                entities=tuple(candidates),
                considered_entities=tuple(candidates),
                command=command,
            )
        matched = (
            candidates
            if state is None
            else [e for e in candidates if matches_semantic_state(e, state)]
        )
        status = QueryResultStatus.MATCHED if matched else QueryResultStatus.EMPTY
        return QueryResult(
            status=status,
            entities=tuple(matched),
            considered_entities=tuple(candidates),
            command=command,
        )
