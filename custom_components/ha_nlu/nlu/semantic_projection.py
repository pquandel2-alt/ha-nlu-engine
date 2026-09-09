"""Controlled projection from turn meaning to compatibility domain models.

This module never creates German text and never invokes a language parser.
It accepts the already analysed :class:`LanguageDocument`, delegates identity
and location grounding to the existing authoritative resolvers, and emits the
same ``ParseResult``/``SemanticFrame`` consumed by the established validator,
reasoning and service-mapping pipeline.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum, auto
from typing import Iterable

from ..areas import AreaSnapshot
from ..entities import EntitySnapshot, normalize_for_compare
from ..world_model import WorldModel
from .composition import CompositionalPlan
from .constraint_resolver import Constraints, resolve_candidates
from .domain_operations import INTENT_BY_DOMAIN_ACTION
from .entity_resolution import ResolutionStatus, resolve_entity_scored
from .entity_resolution import all_mentioned_entities
from .frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from .german_structure import ClauseKind, StructuralRelationKind
from .language_frontend import LanguageDocument
from .parser import ParseResult
from .primitives import SemanticAction, SemanticProperty, SemanticQuantity
from .query_command import (
    PropertyOperand,
    QueryCommand,
    QueryFilter,
    QueryRelationKind,
    QueryResultStatus,
    QueryScope,
    QueryTarget,
    RelationalComparison,
    RelationalOperator,
    RelationConstraint,
)
from .query_executor import QueryExecutor
from .semantic_graph import SemanticEdgeKind, SemanticGraph, SemanticNodeKind
from .semantic_lexicon import SemanticKind, SemanticSpan
from .semantic_location import resolve_coordinated_locations, resolve_semantic_location
from .semantic_state import SemanticState, matches_semantic_state


class ProjectionStatus(Enum):
    """Whether a graph was safely representable by today's domain model."""

    PROJECTED = auto()
    AMBIGUOUS = auto()
    UNSUPPORTED = auto()


_ACTION_ENUM = {
    "turn_on": SemanticAction.TURN_ON,
    "turn_off": SemanticAction.TURN_OFF,
    "toggle": SemanticAction.TOGGLE,
    "open": SemanticAction.OPEN,
    "close": SemanticAction.CLOSE,
    "lock": SemanticAction.LOCK,
    "unlock": SemanticAction.UNLOCK,
    "mute": SemanticAction.MUTE,
    "locate": SemanticAction.LOCATE,
    "press": SemanticAction.PRESS,
    "start": SemanticAction.START,
    "play": SemanticAction.START,
    "pause": SemanticAction.PAUSE,
    "stop": SemanticAction.STOP,
}

_PROPERTY_ENUM = {
    "temperature": SemanticProperty.TEMPERATURE,
    "humidity": SemanticProperty.HUMIDITY,
    "brightness": SemanticProperty.BRIGHTNESS,
    "position": SemanticProperty.POSITION,
    "power": SemanticProperty.POWER,
    "energy": SemanticProperty.ENERGY,
    "battery": SemanticProperty.BATTERY,
    "volume": SemanticProperty.VOLUME,
}

_RELATIONAL_OPERATOR = {
    "lt": RelationalOperator.LT,
    "lte": RelationalOperator.LTE,
    "eq": RelationalOperator.EQ,
    "gte": RelationalOperator.GTE,
    "gt": RelationalOperator.GT,
}

_QUERY_EXECUTOR = QueryExecutor()


def attach_graph(result: ParseResult, graph: SemanticGraph) -> ParseResult:
    """Attach canonical meaning provenance to a compatibility frame."""
    return replace(result, frame=replace(result.frame, semantic_graph=graph))


def project_relational_comparison_query(
    document: LanguageDocument,
    graph: SemanticGraph,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None,
) -> ParseResult | None:
    """Project a two-operand live comparison directly from the graph.

    Both operands must be explicit, uniquely grounded registry entities. The
    shared ``QueryExecutor`` reads their live values; missing readings and
    incompatible units remain non-projectable instead of being converted or
    guessed. Entity order is recovered only from the unchanged source spans.
    """
    if world_model is None:
        return None
    comparators = graph.nodes_of_kind(SemanticNodeKind.COMPARISON)
    if len(comparators) != 1:
        return None
    operator = _RELATIONAL_OPERATOR.get(comparators[0].value)
    if operator is None:
        return None
    mentioned = all_mentioned_entities(
        document.source_text,
        entities,
        index=world_model.entity_index,
    )
    normalized_source = normalize_for_compare(document.source_text)

    def mention_position(entity: EntitySnapshot) -> int:
        positions = tuple(
            position
            for name in (entity.friendly_name, *entity.aliases)
            if (normalized_name := normalize_for_compare(name))
            and (position := normalized_source.find(normalized_name)) >= 0
        )
        return min(positions, default=len(normalized_source))

    if len(mentioned) == 2:
        operands = tuple(
            sorted(
                mentioned,
                key=lambda entity: (mention_position(entity), entity.entity_id),
            )
        )
        if mention_position(operands[1]) == len(normalized_source):
            return None
        grounded_locations: tuple[tuple[str, str | None, str | None], ...] = ()
    else:
        area_mentions = sorted(
            (
                position,
                area,
                surface,
            )
            for area in world_model.areas
            for surface in (area.name, *area.aliases)
            if (normalized_area := normalize_for_compare(surface))
            and (position := normalized_source.find(normalized_area)) >= 0
        )
        unique_areas: list[tuple[int, AreaSnapshot, str]] = []
        seen_area_ids: set[str] = set()
        for position, area, surface in area_mentions:
            if area.area_id not in seen_area_ids:
                unique_areas.append((position, area, surface))
                seen_area_ids.add(area.area_id)
        if len(unique_areas) != 2:
            return None
        readings = tuple(
            world_model.select_entities(
                domain="sensor",
                device_class="temperature",
                area_id=area.area_id,
            )
            for _, area, _ in unique_areas
        )
        if any(len(items) != 1 for items in readings):
            return None
        operands = (readings[0][0], readings[1][0])
        grounded_locations = tuple(
            (surface, area.area_id, None)
            for _, area, surface in unique_areas
        )

    properties = {node.value for node in graph.nodes_of_kind(SemanticNodeKind.PROPERTY)}
    if len(properties) == 1:
        property_ = _PROPERTY_ENUM.get(next(iter(properties)))
    else:
        device_classes = {entity.device_class for entity in operands}
        only_device_class = next(iter(device_classes)) if len(device_classes) == 1 else None
        property_ = (
            _PROPERTY_ENUM.get(only_device_class)
            if only_device_class is not None
            else None
        )
    if property_ is None:
        return None

    comparison = RelationalComparison(
        PropertyOperand(operands[0].entity_id, property_),
        operator,
        PropertyOperand(operands[1].entity_id, property_),
    )
    command = QueryCommand(
        intent="HassRelationalComparison",
        scope=QueryScope.SINGLE,
        target=QueryTarget(
            domain=operands[0].domain,
            device_class=operands[0].device_class,
            entity_id=operands[0].entity_id,
        ),
        filter=QueryFilter(relational=comparison),
    )
    query_result = _QUERY_EXECUTOR.execute(command, list(operands), world_model)
    if query_result.status is QueryResultStatus.TARGET_NOT_FOUND:
        return None
    grounded_graph = graph.with_grounded_entities(
        entity.entity_id for entity in operands
    )
    if grounded_locations:
        grounded_graph = grounded_graph.with_grounded_locations(grounded_locations)
    return ParseResult(
        frame=SemanticFrame(
            intent=command.intent,
            target=TargetReference(
                operands[0].friendly_name,
                operands[0].entity_id,
                operands[0].domain,
                operands[0].device_class,
            ),
            area=None,
            parameters={"query_command": command, "query_result": query_result},
            source_text=document.source_text,
            action=SemanticAction.QUERY,
            property=property_,
            semantic_graph=grounded_graph,
        ),
        # SemanticCommand's target cardinality remains singular. The second
        # operand lives in the typed comparison/QueryResult, not in the
        # command target list (where it would look like an ambiguous action
        # target to the central validator).
        resolved_entities=[operands[0]],
    )


def project_relationship_query(
    document: LanguageDocument,
    graph: SemanticGraph,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None,
) -> ParseResult | None:
    """Project the safe, registry-proven ``same area`` query shape."""
    if world_model is None:
        return None
    relations = graph.nodes_of_kind(SemanticNodeKind.RELATION)
    if len(relations) != 1 or relations[0].value != "same_area":
        return None
    relation_start = relations[0].start
    if relation_start is None:
        return None
    anchors = all_mentioned_entities(
        document.source_text,
        entities,
        index=world_model.entity_index,
    )
    if len(anchors) != 1:
        return None
    anchor = anchors[0]
    domains = {
        str(span.value)
        for span in document.semantics.matching(SemanticKind.DOMAIN)
        if span.end <= relation_start
    }
    device_classes = {
        str(span.value)
        for span in document.semantics.matching(SemanticKind.DEVICE_CLASS)
        if span.end <= relation_start
    }
    if len(domains) != 1 or len(device_classes) > 1:
        return None
    domain = next(iter(domains))
    device_class = next(iter(device_classes), None)
    candidates = list(
        world_model.select_entities(domain=domain, device_class=device_class)
    )
    command = QueryCommand(
        intent="HassRelationshipQuery",
        scope=QueryScope.LIST,
        target=QueryTarget(domain=domain, device_class=device_class),
        filter=QueryFilter(
            relationship=RelationConstraint(
                QueryRelationKind.SAME_AREA, anchor.entity_id
            )
        ),
    )
    query_result = _QUERY_EXECUTOR.execute(command, candidates, world_model)
    if query_result.status is QueryResultStatus.TARGET_NOT_FOUND:
        return None
    matched = list(query_result.entities)
    # The graph describes the requested relation and its grounded anchor.
    # Potentially thousands of result members stay in the typed QueryResult
    # (and Discourse query-result group), avoiding an O(result-size) copy of
    # the complete registry into every MeaningCandidate graph.
    grounded_graph = graph.with_grounded_entities((anchor.entity_id,))
    return ParseResult(
        frame=SemanticFrame(
            intent=command.intent,
            target=TargetReference(
                document.source_text,
                domain=domain,
                device_class=device_class,
            ),
            area=None,
            parameters={"query_command": command, "query_result": query_result},
            source_text=document.source_text,
            action=SemanticAction.QUERY,
            semantic_graph=grounded_graph,
        ),
        resolved_entities=matched,
    )
def project_independent_predicates(
    document: LanguageDocument,
    graph: SemanticGraph,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None,
) -> tuple[ParseResult, ...]:
    """Project a safe structural AND of complete direct predicates.

    Clause and action scope come exclusively from GermanStructuralAnalysis
    and its graph-backed semantic spans. Each clause must explicitly and
    uniquely name one live entity. Rich modifiers stay with their dedicated
    graph projectors so they cannot be flattened accidentally here.
    """
    if (
        not document.utterance.safe_to_execute_directly
        or document.temporal
        or any(
            relation.kind in {
                StructuralRelationKind.OR,
                StructuralRelationKind.EXCEPT,
                StructuralRelationKind.REPLACES,
            }
            for relation in document.structure.relations
        )
        or any(
            clause.kind in {
                ClauseKind.CONDITION,
                ClauseKind.EXCLUSION,
                ClauseKind.RELATIVE,
                ClauseKind.REPAIR,
            }
            for clause in document.structure.clauses
        )
    ):
        return ()
    relations = tuple(
        relation
        for relation in document.structure.relations
        if relation.kind is StructuralRelationKind.AND
    )
    if not relations:
        return ()
    clauses = {clause.clause_id: clause for clause in document.structure.clauses}
    ordered_ids: list[str] = []
    for relation in relations:
        for clause_id in (relation.source_clause, relation.target_clause):
            if clause_id not in ordered_ids:
                ordered_ids.append(clause_id)
    selected = tuple(clauses[item] for item in ordered_ids if item in clauses)
    if len(selected) != len(ordered_ids) or len(selected) < 2:
        return ()

    results: list[ParseResult] = []
    index = world_model.entity_index if world_model is not None else None
    for clause in selected:
        action_values = {
            span.value
            for span in document.semantics.matching(SemanticKind.ACTION)
            if clause.char_start <= span.start < clause.char_end
            and isinstance(span.value, str)
        }
        if len(action_values) != 1:
            return ()
        action = next(iter(action_values))
        semantic_action = _ACTION_ENUM.get(action)
        if semantic_action is None:
            return ()
        clause_text = document.source_text[clause.char_start:clause.char_end]
        mentioned = all_mentioned_entities(clause_text, entities, index=index)
        if len(mentioned) != 1:
            return ()
        entity = mentioned[0]
        intent = INTENT_BY_DOMAIN_ACTION.get((entity.domain, action))
        if intent is None:
            return ()
        results.append(
            ParseResult(
                frame=SemanticFrame(
                    intent=intent,
                    target=TargetReference(
                        entity.friendly_name,
                        entity.entity_id,
                        entity.domain,
                        entity.device_class,
                    ),
                    area=None,
                    source_text=clause_text,
                    action=semantic_action,
                    semantic_graph=graph.with_grounded_entities((entity.entity_id,)),
                ),
                resolved_entities=[entity],
            )
        )
    return tuple(results)


def project_structured_repair(
    document: LanguageDocument,
    graph: SemanticGraph,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None = None,
) -> ParseResult | None:
    """Project an unambiguous target self-correction without text reparsing.

    The replacement clause must name exactly one live entity and the graph
    must contain exactly one executable action. The original referent is
    never included in ``resolved_entities``. Numeric, temporal and predicate
    repairs remain explicitly unsupported until their domain projections can
    preserve units/scope just as strictly.
    """
    replacements = tuple(
        relation
        for relation in document.structure.relations
        if relation.kind is StructuralRelationKind.REPLACES
    )
    if len(replacements) != 1:
        return None
    clauses = {clause.clause_id: clause for clause in document.structure.clauses}
    replacement = clauses.get(replacements[0].target_clause)
    if replacement is None or replacement.kind is not ClauseKind.REPAIR:
        return None
    actions = {node.value for node in graph.nodes_of_kind(SemanticNodeKind.ACTION)}
    if len(actions) != 1:
        return None
    action = next(iter(actions))
    replacement_text = document.source_text[
        replacement.char_start:replacement.char_end
    ]
    mentioned = all_mentioned_entities(
        replacement_text,
        entities,
        index=(world_model.entity_index if world_model is not None else None),
    )
    if len(mentioned) != 1:
        return None
    entity = mentioned[0]
    intent = INTENT_BY_DOMAIN_ACTION.get((entity.domain, action))
    semantic_action = _ACTION_ENUM.get(action)
    if intent is None or semantic_action is None:
        return None
    # A value/property/temporal expression in the replacement changes more
    # than entity identity. Refuse it rather than silently retaining a value
    # from the original clause.
    if any(
        node.start is not None
        and replacement.char_start <= node.start < replacement.char_end
        for kind in {
            SemanticNodeKind.VALUE,
            SemanticNodeKind.PROPERTY,
            SemanticNodeKind.TEMPORAL,
            SemanticNodeKind.COMPARISON,
        }
        for node in graph.nodes_of_kind(kind)
    ):
        return None
    return ParseResult(
        frame=SemanticFrame(
            intent=intent,
            target=TargetReference(
                entity.friendly_name,
                entity.entity_id,
                entity.domain,
                entity.device_class,
            ),
            area=None,
            source_text=document.source_text,
            action=semantic_action,
            semantic_graph=graph.with_grounded_entities((entity.entity_id,)),
        ),
        resolved_entities=[entity],
    )


def _active_spans(
    document: LanguageDocument, kind: SemanticKind
) -> tuple[SemanticSpan, ...]:
    return tuple(
        span
        for span in document.semantics.matching(kind)
        if (
            (clause := document.structure.clause_for_char(span.start)) is None
            or clause.kind in {ClauseKind.MAIN, ClauseKind.COORDINATE}
        )
    )


def _locations(
    document: LanguageDocument,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None,
) -> tuple[tuple[str, str | None, str | None], ...]:
    # An area named inside an exclusion belongs to that excluded target, not
    # to the main target set. Ground the main source span only; this is an
    # unchanged substring selected by structure, never a generated sentence.
    exclusions = tuple(
        clause
        for clause in document.structure.clauses
        if clause.kind is ClauseKind.EXCLUSION
    )
    location_text = document.source_text
    if exclusions:
        first_exclusion = min(clause.char_start for clause in exclusions)
        preceding = tuple(
            clause
            for clause in document.structure.clauses
            if clause.kind is ClauseKind.MAIN and clause.char_end <= first_exclusion
        )
        if preceding:
            location_text = document.source_text[
                preceding[0].char_start:max(clause.char_end for clause in preceding)
            ]
    coordinated = resolve_coordinated_locations(
        location_text, entities, world_model
    )
    if coordinated:
        return coordinated
    single = resolve_semantic_location(location_text, entities, world_model)
    return (single,) if single is not None else ()


def _scope_candidates(
    entities: list[EntitySnapshot],
    world_model: WorldModel | None,
    *,
    domain: str,
    device_class: str | None,
    locations: tuple[tuple[str, str | None, str | None], ...],
) -> tuple[EntitySnapshot, ...]:
    resolved: dict[str, EntitySnapshot] = {}
    scopes = locations or (("", None, None),)
    for _, area_id, floor_id in scopes:
        candidates = (
            world_model.select_entities(
                domain=domain,
                device_class=device_class,
                area_id=area_id,
                floor_id=floor_id,
            )
            if world_model is not None
            else tuple(
                resolve_candidates(
                    entities,
                    Constraints(
                        domain=domain,
                        device_class=device_class,
                        area_id=area_id,
                        floor_id=floor_id,
                    ),
                )
            )
        )
        resolved.update((entity.entity_id, entity) for entity in candidates)
    return tuple(resolved[key] for key in sorted(resolved))


def _exclusion_phrases(document: LanguageDocument) -> tuple[str, ...]:
    phrases: list[str] = []
    action_spans = document.semantics.matching(SemanticKind.ACTION)
    for clause in document.structure.clauses:
        if clause.kind is not ClauseKind.EXCLUSION:
            continue
        words = tuple(
            token.text
            for token in document.tokens[clause.token_start:clause.token_end]
            if token.is_word
            and not any(
                span.start <= token.start and token.end <= span.end
                for span in action_spans
            )
            and token.canonical
            not in {
                "aber", "ausser", "der", "die", "das", "den", "dem",
                "mit", "ausnahme", "von", "nur", "nicht",
            }
        )
        if words:
            phrases.append(" ".join(words))
    return tuple(phrases)


def _resolve_exclusions(
    phrases: tuple[str, ...],
    candidates: tuple[EntitySnapshot, ...],
    world_model: WorldModel | None,
) -> tuple[tuple[EntitySnapshot, ...], tuple[EntitySnapshot, ...]] | None:
    excluded: dict[str, EntitySnapshot] = {}
    for phrase in phrases:
        resolution = resolve_entity_scored(
            phrase,
            list(candidates),
            index=(world_model.entity_index if world_model is not None else None),
        )
        if (
            resolution.status is not ResolutionStatus.RESOLVED
            or resolution.entity is None
        ):
            return None
        excluded[resolution.entity.entity_id] = resolution.entity
    remaining = tuple(
        entity for entity in candidates if entity.entity_id not in excluded
    )
    if not remaining:
        return None
    return remaining, tuple(excluded[key] for key in sorted(excluded))


def _relative_filter(document: LanguageDocument) -> SemanticState | None:
    relative_clauses = tuple(
        clause
        for clause in document.structure.clauses
        if clause.kind is ClauseKind.RELATIVE
        and any(
            relation.kind is StructuralRelationKind.MODIFIES
            and relation.target_clause == clause.clause_id
            for relation in document.structure.relations
        )
    )
    if len(relative_clauses) != 1:
        return None
    clause = relative_clauses[0]
    states = {
        span.value
        for span in document.semantics.matching(SemanticKind.STATE)
        if clause.char_start <= span.start < clause.char_end
        and isinstance(span.value, SemanticState)
    }
    return next(iter(states)) if len(states) == 1 else None


def _has_definite_plural_target(document: LanguageDocument) -> bool:
    """Recognise a conservative ``die <plural entity class>`` noun phrase."""
    target_spans = (
        *_active_spans(document, SemanticKind.DOMAIN),
        *_active_spans(document, SemanticKind.DEVICE_CLASS),
    )
    for span in target_spans:
        surface = normalize_for_compare(span.text)
        if not surface.endswith(("en", "er")):
            continue
        previous = next(
            (
                token
                for token in reversed(document.tokens)
                if token.end <= span.start and token.is_word
            ),
            None,
        )
        if previous is not None and previous.canonical == "die":
            return True
    return False


def _grounded_vocabulary(
    entities: Iterable[EntitySnapshot],
    locations: tuple[tuple[str, str | None, str | None], ...],
    exclusions: tuple[str, ...],
) -> frozenset[str]:
    texts = [
        name
        for entity in entities
        for name in (
            entity.friendly_name,
            *entity.aliases,
            entity.area_name or "",
            *entity.area_aliases,
            entity.floor_name or "",
        )
    ]
    texts.extend(location[0] for location in locations)
    texts.extend(exclusions)
    return frozenset(
        normalize_for_compare(word)
        for value in texts
        for word in value.split()
        if word
    )


def project_structured_command(
    document: LanguageDocument,
    graph: SemanticGraph,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None = None,
    *,
    composition: CompositionalPlan | None = None,
) -> ParseResult | None:
    """Project one supported command graph shape without reparsing text.

    Supported shapes contain one predicate, explicit named targets or one
    quantified entity class, optional proven locations, one relative state
    filter and explicit exclusions. Any unsupported or ambiguous operand
    rejects the complete projection.
    """
    actions = {node.value for node in graph.nodes_of_kind(SemanticNodeKind.ACTION)}
    if len(actions) != 1:
        return None
    action = next(iter(actions))

    targets = composition.targets if composition is not None else ()
    graph_nodes = {node.node_id: node for node in graph.nodes}
    domain_values = {
        target.value
        for edge in graph.edges
        if edge.kind is SemanticEdgeKind.TARGET
        if (target := graph_nodes.get(edge.target)) is not None
        if target.kind is SemanticNodeKind.ENTITY_CLASS
        if (target.value, action) in INTENT_BY_DOMAIN_ACTION
    }
    if not domain_values:
        domain_values = {
            span.value
            for span in _active_spans(document, SemanticKind.DOMAIN)
            if isinstance(span.value, str)
        }
    device_values = {
        (span.value[0], span.value[1])
        for span in _active_spans(document, SemanticKind.DEVICE_CLASS)
        if isinstance(span.value, tuple)
        and len(span.value) == 2
        and isinstance(span.value[0], str)
        and (span.value[1] is None or isinstance(span.value[1], str))
    }
    if targets:
        domains = {entity.domain for entity in targets}
        if domain_values and not domains <= domain_values:
            return None
        device_class = None
    elif len(device_values) == 1:
        domain, device_class = next(iter(device_values))
        domains = {domain}
    elif len(domain_values) == 1:
        domains = set(domain_values)
        device_class = None
    else:
        return None

    mappings = {
        domain: INTENT_BY_DOMAIN_ACTION.get((domain, action)) for domain in domains
    }
    if any(intent is None for intent in mappings.values()):
        return None
    intents = {intent for intent in mappings.values() if intent is not None}
    if len(intents) != 1:
        return None
    intent = next(iter(intents))

    quantifier_values = {
        span.value
        for span in _active_spans(document, SemanticKind.QUANTIFIER)
        if isinstance(span.value, str)
    }
    if len(quantifier_values) > 1:
        return None
    raw_quantifier = next(iter(quantifier_values), None)
    quantifier = (
        Quantifier("both")
        if raw_quantifier == "both"
        else Quantifier("all")
        if raw_quantifier == "all"
        else None
    )
    if quantifier is None and _has_definite_plural_target(document):
        quantifier = Quantifier("all")
    locations = _locations(document, entities, world_model)
    if not targets:
        if quantifier is None or len(domains) != 1:
            return None
        targets = _scope_candidates(
            entities,
            world_model,
            domain=next(iter(domains)),
            device_class=device_class,
            locations=locations,
        )
        if not targets or (quantifier.kind == "both" and len(targets) != 2):
            return None
    elif locations and any(
        not any(
            (area_id is None or entity.area_id == area_id)
            and (floor_id is None or entity.floor_id == floor_id)
            for _, area_id, floor_id in locations
        )
        for entity in targets
    ):
        return None

    relative_clauses = tuple(
        clause
        for clause in document.structure.clauses
        if clause.kind is ClauseKind.RELATIVE
    )
    state_filter = _relative_filter(document)
    if relative_clauses and state_filter is None:
        return None
    if state_filter is not None:
        targets = tuple(
            entity
            for entity in targets
            if matches_semantic_state(entity, state_filter)
        )
        if not targets:
            return None

    exclusion_phrases = _exclusion_phrases(document)
    excluded: tuple[EntitySnapshot, ...] = ()
    if exclusion_phrases:
        resolved = _resolve_exclusions(exclusion_phrases, targets, world_model)
        if resolved is None:
            return None
        targets, excluded = resolved

    vocabulary = _grounded_vocabulary(
        (*targets, *excluded), locations, exclusion_phrases
    )
    structural_vocabulary = {
        normalize_for_compare(token.text)
        for clause in document.structure.clauses
        if clause.kind in {ClauseKind.RELATIVE, ClauseKind.EXCLUSION}
        for token in document.tokens[clause.token_start:clause.token_end]
        if token.is_word
        and token.canonical in {"aber", "ausser", "nur"}
    }
    structural_vocabulary.update(
        normalize_for_compare(clause.connector)
        for clause in document.structure.clauses
        if clause.kind in {ClauseKind.RELATIVE, ClauseKind.EXCLUSION}
        and clause.connector is not None
    )
    if composition is not None:
        structural_vocabulary.update(
            token.canonical
            for token in document.tokens
            if token.canonical in {"und", "sowie", "ausserdem"}
        )
    if any(
        normalize_for_compare(token) not in vocabulary | structural_vocabulary
        for token in document.semantics.unexplained_tokens
    ):
        return None

    frame_targets = targets[:1] if composition is not None else targets
    first = frame_targets[0]
    area = (
        AreaReference(locations[0][0], locations[0][1])
        if len(locations) == 1 and locations[0][1] is not None
        else None
    )
    semantic_quantity = (
        SemanticQuantity.exclude(*(entity.friendly_name for entity in excluded))
        if excluded
        else SemanticQuantity.exactly(2)
        if quantifier is not None and quantifier.kind == "both"
        else SemanticQuantity.all()
        if quantifier is not None
        else None
    )
    return ParseResult(
        frame=SemanticFrame(
            intent=intent,
            target=(
                TargetReference(
                    first.friendly_name, first.entity_id, first.domain
                )
                if composition is not None
                else TargetReference(
                    next(iter(domains)), domain=next(iter(domains))
                )
            ),
            area=area,
            quantifier=quantifier,
            parameters={
                **(
                    {"state_filter": state_filter.name.lower()}
                    if state_filter is not None
                    else {}
                ),
                **(
                    {
                        "excluded": tuple(
                            item.friendly_name for item in excluded
                        ),
                        "excluded_entity_ids": tuple(
                            item.entity_id for item in excluded
                        ),
                    }
                    if excluded
                    else {}
                ),
                **(
                    {
                        "locations": tuple(
                            {
                                "text": text,
                                "area_id": area_id,
                                "floor_id": floor_id,
                            }
                            for text, area_id, floor_id in locations
                        )
                    }
                    if len(locations) > 1
                    else {}
                ),
            },
            source_text=document.source_text,
            action=_ACTION_ENUM.get(action),
            quantity=semantic_quantity,
        ),
        resolved_entities=list(frame_targets),
    )
