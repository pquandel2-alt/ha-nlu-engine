"""Loss-aware German language frontend.

Unlike the historical ``normalize()`` contract this frontend never replaces
the user's utterance.  It retains source spans and records canonical variants
beside the original, allowing later stages to see negation, modality and
clause boundaries even when an orthographic form is normalized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from ..entities import EntitySnapshot, normalize_for_compare
from ..name_similarity import edit_distance
from ..phonetic_correction import phonetic_suggestions
from .normalize import normalize
from .semantic_lexicon import SemanticAnalysis, SemanticKind, analyse_semantics
from .semantic_catalog import CANONICAL_SPELLING_FORMS
from .semantic_utterance import Polarity, SemanticUtterance, SpeechAct, analyse_utterance


_TOKEN_RE = re.compile(r"\d+(?:[,.]\d+)?|[\wäöüß]+|[%°]|[^\w\s]", re.I)
_SPACE_RE = re.compile(r"\s+")
_ELLIPTICAL_DIRECTIVE_RE = re.compile(
    r"\b(?:bitte|soll(?:st|en|t)?|möchte|moechte|will|gern|gerne)\b", re.I
)
_COPULA_RE = re.compile(r"\b(?:ist|sind|war|waren|bleibt|bleiben)\b", re.I)
_LOCATION_CUE_RE = re.compile(r"\b(?:im|in\s+der|in\s+dem|am|beim)\b", re.I)
_SPELLING_FORMS = {
    normalize_for_compare(item): item
    for item in sorted(CANONICAL_SPELLING_FORMS, key=lambda value: ("ae" in value or "oe" in value or "ue" in value, value))
}
_SPELLING_PROTECTED = frozenset(
    normalize_for_compare(word)
    for word in (
        "nicht kein keine keinen ohne wenn sobald falls sofern vielleicht "
        "bitte kannst könnte koennte soll sollen möchte moechte würde wuerde "
        "heute morgen gestern immer normalerweise welche welcher welches"
    ).split()
)
_NEGATION_FORMS = frozenset({"nicht", "kein", "keine", "keinen", "niemals"})
_NEGATION_TYPO_PROTECTED = frozenset({
    "sein", "fein", "klein", "einen", "meine", "deine", "keinerlei",
    # Frequent command/temporal vocabulary one edit away from "nicht".
    # These are real words, while a transposition such as "nciht" remains
    # safety-critical below.
    "licht", "dicht", "nacht",
})


@dataclass(frozen=True)
class LanguageToken:
    text: str
    canonical: str
    start: int
    end: int
    is_word: bool
    is_number: bool


@dataclass(frozen=True)
class TextVariant:
    text: str
    source: str
    cost: float = 0.0


@dataclass(frozen=True)
class LanguageDocument:
    source_text: str
    tokens: tuple[LanguageToken, ...]
    variants: tuple[TextVariant, ...]
    utterance: SemanticUtterance
    semantics: SemanticAnalysis

    @property
    def normalized_text(self) -> str:
        return self.variants[1].text if len(self.variants) > 1 else self.source_text


def _tokens(text: str) -> tuple[LanguageToken, ...]:
    return tuple(
        LanguageToken(
            text=match.group(0),
            canonical=normalize_for_compare(match.group(0)),
            start=match.start(),
            end=match.end(),
            is_word=bool(re.fullmatch(r"[\wäöüß]+", match.group(0), re.I)),
            is_number=bool(re.fullmatch(r"\d+(?:[,.]\d+)?", match.group(0))),
        )
        for match in _TOKEN_RE.finditer(text)
    )


def _orthographic_variant(text: str) -> str:
    """Return a comparison-only ASCII/umlaut canonical form."""
    return _SPACE_RE.sub(" ", normalize_for_compare(text)).strip()


def _registry_compound_variants(
    text: str, entities: tuple[EntitySnapshot, ...]
) -> tuple[str, ...]:
    """Expand joined/split registry spellings without fuzzy guessing."""
    normalized_text = normalize_for_compare(text)
    collapsed_text = normalized_text.replace(" ", "")
    variants: set[str] = set()
    registry_terms = {
        term
        for entity in entities
        for term in (
            entity.area_name or "",
            *entity.area_aliases,
            entity.floor_name or "",
        )
        if term and " " in term.strip()
    }
    for term in registry_terms:
        canonical = normalize_for_compare(term)
        collapsed = canonical.replace(" ", "")
        if collapsed not in collapsed_text or canonical in normalized_text:
            continue
        # Only replace a single joined word with a registry spelling whose
        # letters are exactly equal after whitespace removal.
        pattern = re.compile(rf"(?<!\w){re.escape(collapsed)}(?!\w)", re.I)
        candidate = pattern.sub(canonical, normalized_text)
        if candidate != normalized_text:
            variants.add(candidate)
    return tuple(sorted(variants))


def _has_registry_mention(text: str, entities: tuple[EntitySnapshot, ...]) -> bool:
    normalized = normalize_for_compare(text)
    padded = f" {normalized} "
    return any(
        key
        and f" {key} " in padded
        for entity in entities
        for name in (entity.friendly_name, *entity.aliases)
        if (key := normalize_for_compare(name))
    )


def _lexical_spelling_variants(
    text: str, entities: tuple[EntitySnapshot, ...]
) -> tuple[str, ...]:
    """Correct one uniquely close semantic word; never registry-name words."""
    variants: set[str] = set()
    for match in re.finditer(r"[A-Za-zÄÖÜäöüß]{5,}", text):
        spoken = normalize_for_compare(match.group(0))
        if analyse_semantics(match.group(0)).spans:
            continue
        if (
            spoken in _SPELLING_FORMS
            or spoken in _SPELLING_PROTECTED
        ):
            continue
        scored = sorted(
            (edit_distance(spoken, candidate), candidate)
            for candidate in _SPELLING_FORMS
            if abs(len(spoken) - len(candidate)) <= 1
        )
        if not scored:
            continue
        best_distance = scored[0][0]
        limit = 1
        best = [candidate for distance, candidate in scored if distance == best_distance]
        if best_distance > limit or len(best) != 1:
            continue
        if any(
            spoken in normalize_for_compare(name).split()
            for entity in entities
            for name in (entity.friendly_name, *entity.aliases)
        ):
            continue
        variants.add(
            text[:match.start()] + _SPELLING_FORMS[best[0]] + text[match.end():]
        )
    return tuple(sorted(variants))[:8]


def _has_near_negation(
    text: str, entities: tuple[EntitySnapshot, ...] = ()
) -> bool:
    """Treat a one-edit negation typo as negative, never as ignorable noise."""
    for raw in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", text):
        word = normalize_for_compare(raw)
        if word in _NEGATION_TYPO_PROTECTED:
            continue
        if word in _NEGATION_FORMS:
            return True
        near_negation = any(
            abs(len(word) - len(negation)) <= 1
            and (
                edit_distance(word, negation) == 1
                or (
                    len(word) == len(negation)
                    and sum(left != right for left, right in zip(word, negation)) == 2
                    and any(
                        word[index] == negation[index + 1]
                        and word[index + 1] == negation[index]
                        and word[:index] == negation[:index]
                        and word[index + 2:] == negation[index + 2:]
                        for index in range(len(word) - 1)
                    )
                )
            )
            for negation in _NEGATION_FORMS
        )
        if not near_negation:
            continue
        # Registry names are user data, not grammar.  Only pay the O(n)
        # registry scan after a token has passed the bounded edit-distance
        # gate; ordinary turns therefore remain independent of registry
        # size.  A name such as "Gute Nacht" still cannot become negation.
        if any(
            word in normalize_for_compare(name).split()
            for entity in entities
            for name in (entity.friendly_name, *entity.aliases)
        ):
            continue
        return True
    return False


def analyse_language(
    text: str,
    entities: Iterable[EntitySnapshot] = (),
    *,
    include_phonetic: bool = False,
) -> LanguageDocument:
    """Build one immutable language document without discarding input."""
    normalized = normalize(text)
    variants: list[TextVariant] = [TextVariant(text, "original")]
    if normalized != text:
        variants.append(TextVariant(normalized, "surface_normalization", 0.1))
    canonical = _orthographic_variant(text)
    if canonical not in {variant.text for variant in variants}:
        variants.append(TextVariant(canonical, "orthographic", 0.2))
    entity_tuple = tuple(entities)
    if _LOCATION_CUE_RE.search(text):
        for candidate in _registry_compound_variants(text, entity_tuple):
            if candidate not in {variant.text for variant in variants}:
                variants.append(TextVariant(candidate, "registry_compound", 0.15))
    for candidate in _lexical_spelling_variants(text, entity_tuple):
        if candidate not in {variant.text for variant in variants}:
            variants.append(TextVariant(candidate, "lexical_spelling", 0.35))
    if include_phonetic:
        for suggestion in phonetic_suggestions(text, list(entity_tuple)):
            if suggestion.corrected_text not in {variant.text for variant in variants}:
                variants.append(TextVariant(
                    suggestion.corrected_text,
                    f"phonetic:{suggestion.corrected_term}",
                    0.75,
                ))
    # Semantics consumes the normalized surface for compatibility while the
    # document keeps the original and every applied alternative.
    utterance = analyse_utterance(text)
    semantics = analyse_semantics(utterance.normalized_text)
    # A unique one-edit operation correction may reveal an otherwise hidden
    # imperative. It changes only the discourse classification; compilation
    # still has to succeed on that recorded variant below the frontend.
    if utterance.speech_act is SpeechAct.STATEMENT:
        corrected_command = next(
            (
                analyse_utterance(variant.text)
                for variant in variants
                if variant.source == "lexical_spelling"
                and analyse_utterance(variant.text).speech_act is SpeechAct.COMMAND
            ),
            None,
        )
        if corrected_command is not None:
            utterance = replace(
                utterance,
                speech_act=SpeechAct.COMMAND,
                modality=corrected_command.modality,
            )
    # Dynamic registry names can contain the device noun as a compound
    # ("Gartenschalter", "Turmventilator"). Static discourse regexes cannot
    # safely enumerate those names.  Promote only a positive statement with
    # one explicit registry mention, one operation and directive/elliptical
    # evidence; plain state descriptions ("... ist an") remain statements.
    if (
        utterance.speech_act is SpeechAct.STATEMENT
        and len(semantics.values(SemanticKind.ACTION)) == 1
        and not utterance.normalized_text.rstrip().endswith("?")
        and (
            _ELLIPTICAL_DIRECTIVE_RE.search(utterance.normalized_text)
            or _COPULA_RE.search(utterance.normalized_text) is None
        )
        and _has_registry_mention(utterance.normalized_text, entity_tuple)
    ):
        utterance = replace(utterance, speech_act=SpeechAct.COMMAND)
    if _has_near_negation(text, entity_tuple):
        utterance = replace(utterance, polarity=Polarity.NEGATIVE)
    return LanguageDocument(
        source_text=text,
        tokens=_tokens(text),
        variants=tuple(variants),
        utterance=utterance,
        semantics=semantics,
    )
