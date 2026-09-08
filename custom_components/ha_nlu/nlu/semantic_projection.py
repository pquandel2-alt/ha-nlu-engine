"""The single controlled bridge from turn semantics to existing domain models.

Projection is deliberately non-executing.  It may call the authoritative
command/query compilers and resolvers, but it never maps or invokes a Home
Assistant service.  Unsupported graph shapes remain unprojected.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum, auto

from ..entities import EntitySnapshot
from ..world_model import WorldModel
from .german_structure import ClauseKind, StructuralRelationKind
from .language_frontend import LanguageDocument
from .parser import ClarificationRequest, ParseResult
from .semantic_compiler import SemanticCommandCompiler
from .semantic_graph import SemanticGraph
from .semantic_lexicon import SemanticKind, analyse_semantics
from .semantic_state import SemanticState, matches_semantic_state


class ProjectionStatus(Enum):
    """Whether a graph was safely representable by today's domain model."""

    PROJECTED = auto()
    AMBIGUOUS = auto()
    UNSUPPORTED = auto()


def attach_graph(
    result: ParseResult,
    graph: SemanticGraph,
) -> ParseResult:
    """Attach canonical meaning provenance to a validated legacy frame."""
    return replace(result, frame=replace(result.frame, semantic_graph=graph))


def _without_clause(document: LanguageDocument, clause_id: str) -> str:
    clause = next(item for item in document.structure.clauses if item.clause_id == clause_id)
    relation = next(
        item
        for item in document.structure.relations
        if item.target_clause == clause_id
        and item.kind is StructuralRelationKind.MODIFIES
    )
    start = relation.connector_start
    while start > 0 and document.source_text[start - 1].isspace():
        start -= 1
    if start > 0 and document.source_text[start - 1] == ",":
        start -= 1
    projected = document.source_text[:start] + document.source_text[clause.char_end:]
    return " ".join(projected.split())


def project_relative_state_command(
    document: LanguageDocument,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None = None,
) -> ParseResult | ClarificationRequest | None:
    """Project one explicitly scoped relative state filter.

    Entity selection and capability validation continue to be performed by
    the existing compiler.  Broader or ambiguous shapes are intentionally
    returned as parsed-but-unprojectable.
    """
    relatives = tuple(
        clause for clause in document.structure.clauses
        if clause.kind is ClauseKind.RELATIVE
    )
    if len(relatives) != 1:
        return None
    relative = relatives[0]
    relative_states = tuple(
        span.value
        for span in document.semantics.matching(SemanticKind.STATE)
        if relative.char_start <= span.start < relative.char_end
        and isinstance(span.value, SemanticState)
    )
    if len(set(relative_states)) != 1:
        return None
    requested_state = relative_states[0]
    assert isinstance(requested_state, SemanticState)
    if not any(
        relation.kind is StructuralRelationKind.MODIFIES
        and relation.target_clause == relative.clause_id
        for relation in document.structure.relations
    ):
        return None

    projected_text = _without_clause(document, relative.clause_id)
    compiled = SemanticCommandCompiler.compile(
        projected_text,
        entities,
        world_model,
        analyse_semantics(projected_text),
    )
    if not isinstance(compiled, ParseResult):
        return compiled
    filtered = [
        entity for entity in compiled.resolved_entities
        if matches_semantic_state(entity, requested_state)
    ]
    if not filtered:
        return None
    return replace(
        compiled,
        frame=replace(
            compiled.frame,
            source_text=document.source_text,
            parameters={
                **compiled.frame.parameters,
                "state_filter": requested_state.name.lower(),
            },
        ),
        resolved_entities=filtered,
    )


def project_scoped_negation_exclusion(
    document: LanguageDocument,
    entities: list[EntitySnapshot],
    world_model: WorldModel | None = None,
) -> ParseResult | ClarificationRequest | None:
    """Project comma-scoped ``nur TARGET nicht`` through existing exclusion logic."""
    exclusions = tuple(
        clause for clause in document.structure.clauses
        if clause.kind is ClauseKind.EXCLUSION and clause.connector == "nur"
    )
    if len(exclusions) != 1:
        return None
    exclusion = exclusions[0]
    scopes = tuple(
        scope for scope in document.structure.negations
        if scope.clause_id == exclusion.clause_id
    )
    if len(scopes) != 1:
        return None
    target_words = tuple(
        token.text
        for token in document.tokens[exclusion.token_start:exclusion.token_end]
        if token.is_word
        and token.canonical not in {
            "der", "die", "das", "den", "dem", "nur", "nicht",
        }
    )
    if not target_words:
        return None
    connector_start = next(
        relation.connector_start
        for relation in document.structure.relations
        if relation.kind is StructuralRelationKind.EXCEPT
        and relation.target_clause == exclusion.clause_id
    )
    positive = document.source_text[:connector_start].rstrip(" ,")
    projected = f"{positive} außer {' '.join(target_words)}"
    compiled = SemanticCommandCompiler.compile(
        projected, entities, world_model, analyse_semantics(projected)
    )
    if not isinstance(compiled, ParseResult):
        return compiled
    return replace(
        compiled,
        frame=replace(compiled.frame, source_text=document.source_text),
    )
