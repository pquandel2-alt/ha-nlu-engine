"""Unified semantic candidate interpreter for HomeIntent V7.

The interpreter consumes one loss-aware ``LanguageDocument`` and produces
ranked meaning candidates before any domain executor runs.  Existing safe
semantic compilers are reused as the authoritative bridge while commands,
queries and automations migrate to the common candidate model.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

from ..entities import EntitySnapshot
from ..world_model import WorldModel
from .language_frontend import LanguageDocument, TextVariant
from .parser import ClarificationRequest, ParseResult
from .semantic_compiler import SemanticCommandCompiler, SemanticQueryCompiler
from .semantic_lexicon import SemanticKind
from .semantic_lexicon import analyse_semantics
from .semantic_location import resolve_coordinated_locations, resolve_semantic_location
from .semantic_utterance import SpeechAct
from .understanding import EvidenceKind, MeaningCandidate, UnderstandingEvidence
from .entity_resolution import all_mentioned_entities


@dataclass(frozen=True)
class InterpreterResult:
    candidates: tuple[MeaningCandidate, ...]
    parse_result: ParseResult | ClarificationRequest | None = None
    selected_variant: TextVariant | None = None


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


def _missing_slots(document: LanguageDocument) -> tuple[str, ...]:
    analysis = document.semantics
    missing: list[str] = []
    if document.utterance.speech_act is SpeechAct.COMMAND:
        if not analysis.values(SemanticKind.ACTION):
            missing.append("action")
        if not (
            analysis.values(SemanticKind.DOMAIN)
            or analysis.values(SemanticKind.DEVICE_CLASS)
        ):
            missing.append("target")
    elif document.utterance.speech_act is SpeechAct.QUERY:
        if not (
            analysis.values(SemanticKind.DOMAIN)
            or analysis.values(SemanticKind.DEVICE_CLASS)
            or analysis.values(SemanticKind.PROPERTY)
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
        seen_keys: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
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
                resolve_coordinated_locations(variant.text, entities)
                if resolve_registry
                else None
            )
            if locations:
                slots["locations"] = tuple(item[0] for item in locations)
            else:
                location = (
                    resolve_semantic_location(variant.text, entities)
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
            # Bounded phonetic/edit candidates are explanatory only and must
            # pass the existing confirm-before-action correction flow.
            may_compile = (
                compile_result
                and not variant.source.startswith("phonetic:")
                and variant.source != "orthographic"
            )
            if may_compile and document.utterance.speech_act is SpeechAct.QUERY:
                parse_result = SemanticQueryCompiler.compile(
                    variant.text, entities, world_model, analysis
                )
            elif may_compile and document.utterance.safe_to_execute_directly:
                parse_result = SemanticCommandCompiler.compile(
                    variant.text, entities, world_model, analysis
                )

            conflicts = _conflicts(candidate_document)
            missing = _missing_slots(candidate_document)
            complete = isinstance(parse_result, ParseResult) and not conflicts
            coverage = len(analysis.spans) * 5.0
            penalty = (
                len(analysis.unexplained_tokens) * 3.0
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
            if identity not in seen_keys:
                seen_keys.add(identity)
                candidates.append(MeaningCandidate(
                    key=key,
                    score=score,
                    complete=complete,
                    slots=slots,
                    missing_slots=missing,
                    conflicts=conflicts,
                    evidence=evidence,
                ))
            if best_parse is None and parse_result is not None and not conflicts:
                best_parse = parse_result
                selected_variant = variant

        candidates.sort(key=lambda item: (-item.score, item.key))
        return InterpreterResult(tuple(candidates), best_parse, selected_variant)
