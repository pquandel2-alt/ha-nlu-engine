"""Unified semantic candidate interpreter for HomeIntent V7.

The interpreter consumes one loss-aware ``LanguageDocument`` and produces
ranked meaning candidates before any domain executor runs.  Existing safe
semantic compilers are reused as the authoritative bridge while commands,
queries and automations migrate to the common candidate model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..entities import EntitySnapshot, normalize_for_compare
from ..world_model import WorldModel
from .language_frontend import LanguageDocument, TextVariant
from .parser import ClarificationRequest, ParseResult
from .semantic_compiler import SemanticCommandCompiler, SemanticQueryCompiler
from .semantic_catalog import INTENT_BY_DOMAIN_ACTION
from .semantic_lexicon import SemanticKind
from .semantic_lexicon import analyse_semantics
from .semantic_location import resolve_coordinated_locations, resolve_semantic_location
from .semantic_utterance import SpeechAct
from .understanding import EvidenceKind, MeaningCandidate, UnderstandingEvidence
from .entity_resolution import all_mentioned_entities
from .frame import SemanticFrame, TargetReference
from .primitives import SemanticAction
from .verb_state_query import match_verb_state_query
from .composition import CompositionalPlan, build_compositional_plan, project_target
from .meaning import analyse_turn


@dataclass(frozen=True)
class InterpreterResult:
    candidates: tuple[MeaningCandidate, ...]
    parse_result: ParseResult | ClarificationRequest | None = None
    selected_variant: TextVariant | None = None
    compositional_plan: CompositionalPlan | None = None


def _slot_values(document: LanguageDocument) -> dict[str, object]:
    analysis = document.semantics
    slots: dict[str, object] = {
        "speech_act": document.utterance.speech_act.name.lower(),
        "modality": document.utterance.modality.name.lower(),
        "polarity": document.utterance.polarity.name.lower(),
        "clauses": tuple(
            {
                "role": clause.role.name.lower(),
                "text": clause.text,
                "connector": clause.connector,
            }
            for clause in document.utterance.clauses
        ),
    }
    for label, kind in (
        ("actions", SemanticKind.ACTION),
        ("domains", SemanticKind.DOMAIN),
        ("device_classes", SemanticKind.DEVICE_CLASS),
        ("states", SemanticKind.STATE),
        ("quantifiers", SemanticKind.QUANTIFIER),
        ("query_scopes", SemanticKind.QUERY_SCOPE),
        ("properties", SemanticKind.PROPERTY),
        ("comparators", SemanticKind.COMPARATOR),
    ):
        values = analysis.values(kind)
        if values:
            slots[label] = tuple(sorted((str(value) for value in values)))
    return slots


def _conflicts(document: LanguageDocument) -> tuple[str, ...]:
    conflicts: list[str] = []
    for kind in (
        SemanticKind.ACTION,
        SemanticKind.DOMAIN,
        SemanticKind.STATE,
        SemanticKind.PROPERTY,
        SemanticKind.COMPARATOR,
    ):
        if document.semantics.conflicts(kind):
            conflicts.append(kind.name.lower())
    return tuple(conflicts)


def _resolved_conflicts(
    document: LanguageDocument,
    parse_result: ParseResult | ClarificationRequest | None,
) -> tuple[str, ...]:
    """Return only conflicts that remain after domain-aware compilation.

    German particles and participles are deliberately polysemous: ``zu`` in
    ``zu starten`` is not a close action, and ``Wiedergabe gestartet`` may
    expose both ``play`` and ``start`` although both compile to the same media
    service.  Once the compiler has produced one validated intent for one
    domain, discard an action conflict only when every domain-valid action
    collapses to that exact intent.  Truly competing meanings such as
    ``Licht an und aus`` remain conflicts.
    """
    conflicts = list(_conflicts(document))
    if "action" not in conflicts or not isinstance(parse_result, ParseResult):
        return tuple(conflicts)
    domains = {
        entity.domain for entity in parse_result.resolved_entities
    }
    if not domains and parse_result.frame.target is not None:
        if parse_result.frame.target.domain is not None:
            domains.add(parse_result.frame.target.domain)
    intents = {
        intent
        for domain in domains
        for action in document.semantics.values(SemanticKind.ACTION)
        if (intent := INTENT_BY_DOMAIN_ACTION.get((domain, str(action)))) is not None
    }
    if intents == {parse_result.frame.intent}:
        conflicts.remove("action")
    return tuple(conflicts)


def _missing_slots(
    document: LanguageDocument,
    slots: dict[str, object],
    parse_result: ParseResult | ClarificationRequest | None = None,
) -> tuple[str, ...]:
    analysis = document.semantics
    missing: list[str] = []
    if document.utterance.speech_act is SpeechAct.COMMAND:
        compiled_action = (
            parse_result.frame.action
            if isinstance(parse_result, ParseResult)
            else None
        )
        if not analysis.values(SemanticKind.ACTION) and compiled_action is None:
            missing.append("action")
        if not (
            analysis.values(SemanticKind.DOMAIN)
            or analysis.values(SemanticKind.DEVICE_CLASS)
            or slots.get("entities")
        ):
            missing.append("target")
    elif document.utterance.speech_act is SpeechAct.QUERY:
        if not (
            analysis.values(SemanticKind.DOMAIN)
            or analysis.values(SemanticKind.DEVICE_CLASS)
            or analysis.values(SemanticKind.PROPERTY)
            or slots.get("entities")
        ):
            missing.append("target_or_property")
    return tuple(missing)


class SemanticInterpreter:
    """Compose one language document into candidates and a safe parse."""

    @staticmethod
    def interpret(
        document: LanguageDocument,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        *,
        compile_result: bool = True,
        resolve_registry: bool = True,
    ) -> InterpreterResult:
        candidates: list[MeaningCandidate] = []
        best_parse: ParseResult | ClarificationRequest | None = None
        selected_variant: TextVariant | None = None
        best_compositional_plan: CompositionalPlan | None = None
        candidate_indexes: dict[
            tuple[str, tuple[tuple[str, str], ...]], int
        ] = {}
        for variant in document.variants:
            analysis = (
                document.semantics
                if variant.source == "original"
                else analyse_semantics(variant.text)
            )
            candidate_document = replace(document, semantics=analysis)
            slots = _slot_values(candidate_document)
            mentions = (
                all_mentioned_entities(variant.text, entities)
                if resolve_registry
                else ()
            )
            if mentions:
                slots["entities"] = tuple(entity.entity_id for entity in mentions)
                if "domains" not in slots:
                    slots["domains"] = tuple(sorted({entity.domain for entity in mentions}))
            locations = (
                resolve_coordinated_locations(variant.text, entities, world_model)
                if resolve_registry
                else None
            )
            if locations:
                slots["locations"] = tuple(item[0] for item in locations)
            else:
                location = (
                    resolve_semantic_location(variant.text, entities, world_model)
                    if resolve_registry
                    else None
                )
                if location is not None:
                    slots["locations"] = (location[0],)

            evidence = tuple(
                UnderstandingEvidence(
                    EvidenceKind.LEXICON,
                    f"{span.kind.name.lower()}={span.value}",
                    span.start,
                    span.end,
                    1.0,
                    span.text,
                )
                for span in analysis.spans
            ) + tuple(
                UnderstandingEvidence(
                    EvidenceKind.REGISTRY,
                    entity.entity_id,
                    score=1.0,
                    detail=entity.friendly_name,
                )
                for entity in mentions
            )
            if variant.source != "original":
                evidence += (
                    UnderstandingEvidence(
                        EvidenceKind.PHONETIC
                        if variant.source.startswith("phonetic:")
                        else EvidenceKind.NORMALIZED,
                        variant.text,
                        score=-variant.cost,
                        detail=variant.source,
                    ),
                )

            parse_result: ParseResult | ClarificationRequest | None = None
            compositional_plan: CompositionalPlan | None = None
            # Bounded phonetic/edit candidates are explanatory only and must
            # pass the existing confirm-before-action correction flow.
            may_compile = (
                compile_result
                and not variant.source.startswith("phonetic:")
                and variant.source != "orthographic"
            )
            if may_compile and document.utterance.speech_act is SpeechAct.QUERY:
                verb_answer = match_verb_state_query(variant.text, entities)
                if verb_answer is not None:
                    domains = {entity.domain for entity in verb_answer.entities}
                    parse_result = ParseResult(
                        frame=SemanticFrame(
                            intent="HassEntityStateQuery",
                            target=TargetReference(
                                text=variant.text,
                                domain=(next(iter(domains)) if len(domains) == 1 else None),
                            ),
                            area=None,
                            parameters={"predicate": verb_answer.predicate},
                            source_text=variant.text,
                            action=SemanticAction.QUERY,
                        ),
                        resolved_entities=list(verb_answer.entities),
                        response_text=verb_answer.response_text,
                        context_predicate=verb_answer.predicate,
                        explanation_text=verb_answer.explanation_text,
                    )
                else:
                    parse_result = SemanticQueryCompiler.compile(
                        variant.text, entities, world_model, analysis
                    )
            elif may_compile and document.utterance.safe_to_execute_directly:
                compositional_plan = build_compositional_plan(
                    analyse_turn(variant.text), entities
                )
                compile_text = (
                    project_target(
                        compositional_plan, compositional_plan.targets[0]
                    )
                    if compositional_plan is not None
                    else variant.text
                )
                parse_result = SemanticCommandCompiler.compile(
                    compile_text,
                    entities,
                    world_model,
                    analyse_semantics(compile_text),
                )

            resolved_mentions = mentions
            if isinstance(parse_result, ParseResult):
                resolved_mentions = tuple(parse_result.resolved_entities)
            elif isinstance(parse_result, ClarificationRequest):
                resolved_mentions = parse_result.candidates
            if resolved_mentions and "entities" not in slots:
                slots["entities"] = tuple(
                    entity.entity_id for entity in resolved_mentions
                )
                slots.setdefault(
                    "domains",
                    tuple(sorted({entity.domain for entity in resolved_mentions})),
                )

            conflicts = _resolved_conflicts(candidate_document, parse_result)
            missing = _missing_slots(candidate_document, slots, parse_result)
            complete = (
                isinstance(parse_result, ParseResult)
                and not conflicts
                and not missing
            )
            coverage = len(analysis.spans) * 5.0
            registry_tokens = {
                normalize_for_compare(token)
                for entity in resolved_mentions
                for name in (entity.friendly_name, *entity.aliases)
                for token in name.split()
            }
            unexplained = tuple(
                token
                for token in analysis.unexplained_tokens
                if normalize_for_compare(token) not in registry_tokens
            )
            penalty = (
                len(unexplained) * 3.0
                + len(conflicts) * 20.0
                + variant.cost * 10.0
            )
            score = max(0.0, min(100.0, 50.0 + coverage - penalty))
            key_parts = [document.utterance.speech_act.name.lower()]
            for name in ("actions", "domains", "device_classes", "properties"):
                if name in slots:
                    key_parts.append(f"{name}={slots[name]}")
            key = "|".join(key_parts)
            identity = (key, tuple(sorted((name, repr(value)) for name, value in slots.items())))
            candidate = MeaningCandidate(
                key=key,
                score=score,
                complete=complete,
                slots=slots,
                missing_slots=missing,
                conflicts=conflicts,
                evidence=evidence,
            )
            previous_index = candidate_indexes.get(identity)
            if previous_index is None:
                candidate_indexes[identity] = len(candidates)
                candidates.append(candidate)
            else:
                previous = candidates[previous_index]
                merged_evidence = previous.evidence + tuple(
                    item for item in candidate.evidence
                    if item not in previous.evidence
                )
                if complete and not previous.complete:
                    # A normalized surface can preserve exactly the same
                    # slots while making them compilable. Keep that stronger
                    # proof, but retain evidence from every equivalent
                    # surface (including non-executable phonetic variants).
                    candidates[previous_index] = replace(
                        candidate, evidence=merged_evidence
                    )
                else:
                    candidates[previous_index] = replace(
                        previous, evidence=merged_evidence
                    )
            if best_parse is None and parse_result is not None and not conflicts:
                best_parse = parse_result
                selected_variant = variant
                best_compositional_plan = compositional_plan

        candidates.sort(key=lambda item: (-item.score, item.key))
        return InterpreterResult(
            tuple(candidates),
            best_parse,
            selected_variant,
            best_compositional_plan,
        )
