"""Deterministic, order-independent compiler for German device commands.

Unlike a sentence-template parser, this module scans an utterance for
independent semantic facts (operation, target/domain, location, quantity and
value) and accepts the command only if those facts form exactly one valid
meaning against the current Home Assistant entity snapshot.  It is small,
local and dependency-free; no probabilistic model or network service is
involved.

The established Hassil grammars remain the compatibility fast path.  This
compiler is the safe fallback for natural paraphrases and free word order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..areas import AreaSnapshot
from ..entities import (
    EntitySnapshot,
    generate_aliases,
    normalize_for_compare,
)
from ..name_similarity import bounded_name_similarity
from ..world_model import WorldModel
from .constraint_resolver import Constraints, resolve_candidates
from .entity_resolution import (
    ResolutionStatus,
    ResolveStatus,
    mentioned_entities,
    rank_semantic_targets,
    resolve_entity,
    resolve_entity_scored,
)
from .frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from .parser import ClarificationRequest, ParseResult
from .primitives import SemanticAction, SemanticProperty, SemanticQuantity
from .query_command import QueryCommand, QueryFilter, QueryScope, QueryTarget
from .query_executor import QueryExecutor
from .semantic_lexicon import SemanticAnalysis, SemanticKind, analyse_semantics
from .semantic_catalog import (
    INTENT_BY_DOMAIN_ACTION,
    MEASUREMENT_PROPERTY_SPECS,
    SEMANTIC_RESOLUTION_WORDS,
    V7_ENTITY_AMBIGUITY_MARGIN,
    VALUE_INTENT_BY_DOMAIN_PROPERTY,
)
from .semantic_location import (
    has_explicit_location_cue,
    resolve_coordinated_locations,
    resolve_semantic_location,
)
from .semantic_state import (
    QUERYABLE_STATE_DOMAINS,
    SemanticState,
    supports_state_predicate,
)


def _device_class_targets(
    analysis: SemanticAnalysis,
) -> list[tuple[str, str | None]]:
    """Narrow lexicon object values to typed domain/device-class pairs."""
    targets: list[tuple[str, str | None]] = []
    for value in analysis.values(SemanticKind.DEVICE_CLASS):
        if not isinstance(value, tuple) or len(value) != 2:
            continue
        domain, device_class = value
        if isinstance(domain, str) and (
            device_class is None or isinstance(device_class, str)
        ):
            targets.append((domain, device_class))
    return targets


@dataclass(frozen=True)
class SemanticFacts:
    """Observable facts extracted without committing to an execution."""

    intents: frozenset[str]
    domains: frozenset[str]
    percent: int | None
    temperature: int | None
    quantity: Quantifier | None
    location_text: str | None
    area_id: str | None
    floor_id: str | None


_QUESTION_RE = re.compile(
    r"^\s*(?:wer|was|wie|welch\w*|wo|wann|warum|wieso|ist|sind|hat|haben|gibt)\b",
    re.IGNORECASE,
)
_LOCATION_CUE_RE = re.compile(r"\b(?:im|in\s+der|in\s+dem|am|beim)\s+", re.I)
_LEVEL_CUE_RE = re.compile(r"(?<!nach\s)\b(?:oben|unten)\b", re.I)
_PLURAL_RE = re.compile(
    r"\b(?:lichter|lampen|leuchten|steckdosen|rollläden|rolläden|"
    r"die\s+rol{1,3}aden|rollos|"
    r"jalousien|ventilatoren|heizungen|thermostate|skripte|lautsprecher|"
    r"staubsauger|ventile)\b",
    re.I,
)
_ALL_RE = re.compile(r"\b(?:alle|sämtliche|sämtlichen|jede|jeden|jedes|die\s+ganzen)\b", re.I)
_BOTH_RE = re.compile(r"\bbeide(?:n|r)?\b", re.I)
_COUNT_WORDS = {
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
}
_COUNT_RE = re.compile(r"\b(" + "|".join(_COUNT_WORDS) + r"|[2-9]|10)\b", re.I)
_ORDERED_SUBSET_RE = re.compile(r"\b(?:erste\w*|letzte\w*)\b", re.I)
_EXCLUSION_CUE_RE = re.compile(
    r"\b(?:außer|ausser|mit\s+ausnahme\s+von)\b", re.I
)
# German separable particles can follow the exclusion: ``alle Lichter außer
# Küchenlicht aus``.  The first alternative deliberately claims a recognised
# command tail before the general end-of-sentence alternative can absorb it
# into the registry name.
_EXCLUSION_RE = re.compile(
    r"\b(?:außer|ausser|mit\s+ausnahme\s+von)\s+(?P<targets>.+?)"
    r"(?:\s+(?P<tail>an|ein|aus|auf|zu|hoch|runter|herunter|hinauf|hinunter|"
    r"anmachen|ausmachen|einschalten|ausschalten|anschalten|abschalten|"
    r"öffnen|schließen)\s*[?.!]*$|\s*[?.!]*$)",
    re.I,
)
_EXCLUSION_SPLIT_RE = re.compile(r"\s*(?:,|\bund\b)\s*", re.I)
_EXCLUSION_ARTICLE_RE = re.compile(
    r"^(?:(?:dem|der|den|die|das|des|vom|alle[nrms]?|im|in\s+der|in\s+dem)\s+)+",
    re.I,
)

_HALF_RE = re.compile(r"\b(?:halb|halbe(?:r|n)?|hälfte|zur\s+hälfte)\b", re.I)
_ZERO_RE = re.compile(r"\b(?:komplett|ganz|vollständig)\s+(?:runter|herunter|zu)\b", re.I)
_HUNDRED_RE = re.compile(r"\b(?:komplett|ganz|vollständig)\s+(?:hoch|auf)\b", re.I)
_PERCENT_RE = re.compile(
    r"(?:\bauf\s+(?P<after>100|[1-9]?\d)\b|"
    r"\b(?P<unit>100|[1-9]?\d)\s*(?:prozent|%)\b)", re.I
)
_ANY_PERCENT_RE = re.compile(r"\b(?P<value>\d+)\s*(?:prozent|%)\b", re.I)
_FIFTY_PERCENT_RE = re.compile(r"\bfünfzig\s+prozent\b", re.I)
_TEMPERATURE_RE = re.compile(
    r"\bauf\s+(?P<value>-?\d{1,2})\s*(?:grad|°\s*c|°c)\b",
    re.I,
)
_DIRECTIVE_RE = re.compile(
    r"\b(?:bitte|soll(?:st|en|t)?|möchte|will|kannste|könntest|koenntest|"
    r"würdest|wuerdest|würde\s+gern|würd\s+gern|wuerd\s+gern)\b", re.I
)
_COPULA_STATEMENT_RE = re.compile(
    r"\b(?:ist|sind|war|waren|bleibt|bleiben)\b", re.I
)

_TOKEN_RE = re.compile(r"[\wäöüß]+", re.I)
_STOP_WORDS = {
    "der", "die", "das", "den", "dem", "ein", "eine", "einen", "einem",
    "bitte", "kannst", "du", "mir", "mal", "doch", "jetzt", "vorhandenen",
    "im", "in", "am", "auf", "aus", "an", "zu", "und", "sind", "ist",
    "alle", "sämtliche", "sämtlichen", "jede", "jeden", "jedes", "beide",
}
_QUERY_MARKER_RE = re.compile(
    r"\b(?:ist|sind|welch\w*|wie\s+viele|wo|gibt\s+es|haben\s+wir|irgendein\w*|keine?\w*)\b",
    re.I,
)
_SINGULAR_NAMED_QUERY_RE = re.compile(r"^\s*ist\s+(?:das|der|die)\b", re.I)
_BARE_NAMED_STATE_QUERY_RE = re.compile(
    r"^\s*(?:wie\s+ist|welchen\s+zustand\s+hat|(?:wie\s+lautet\s+)?der\s+status\s+von)\b",
    re.I,
)
_DURATION_QUESTION_RE = re.compile(r"^\s*wie\s+lange\b", re.I)

_QUERY_EXECUTOR = QueryExecutor()


def _compile_measurement_query(
    text: str,
    entities: list[EntitySnapshot],
    analysis: SemanticAnalysis,
    world_model: WorldModel | None = None,
) -> ParseResult | None:
    """Compile one property/location question from independent facts."""
    if analysis.values(SemanticKind.COMMAND_MARKER):
        return None
    properties = analysis.values(SemanticKind.PROPERTY)
    comparators = analysis.values(SemanticKind.COMPARATOR)
    if len(properties) != 1 or len(comparators) > 1:
        return None
    canonical = next(iter(properties))
    if not isinstance(canonical, str):
        return None
    spec = MEASUREMENT_PROPERTY_SPECS.get(canonical)
    if spec is None:
        return None
    location = resolve_semantic_location(text, entities, world_model)
    if location is None:
        return None
    if _has_unexplained_meaning(analysis, (location[0],)):
        return None

    comparator = next(iter(comparators), None)
    threshold_match = re.search(r"\b\d+(?:[,.]\d+)?\b", text)
    if comparator is not None and threshold_match is None:
        return None
    domain, device_class, label, property_name = spec
    area_id, floor_id = location[1], location[2]
    matched = [
        entity
        for entity in entities
        if entity.domain == domain
        and (device_class is None or entity.device_class == device_class)
        and (area_id is None or entity.area_id == area_id)
        and (floor_id is None or entity.floor_id == floor_id)
    ]
    if comparator is not None and threshold_match is not None:
        threshold = float(threshold_match.group(0).replace(",", "."))
        predicates = {
            "lt": lambda value: value < threshold,
            "gt": lambda value: value > threshold,
            "lte": lambda value: value <= threshold,
            "gte": lambda value: value >= threshold,
        }
        predicate = predicates.get(str(comparator))
        if predicate is None:
            return None
        filtered: list[EntitySnapshot] = []
        for entity in matched:
            try:
                if predicate(float(entity.state)):
                    filtered.append(entity)
            except (TypeError, ValueError):
                continue
        matched = filtered
    if not matched:
        return None
    matched.sort(key=lambda entity: (entity.area_name or "", entity.friendly_name))
    average = "average" in analysis.values(SemanticKind.QUERY_SCOPE)
    intent = (
        "HassLocationPropertyQuery"
        if len(matched) > 1 or average
        else "HassGetState"
    )
    return ParseResult(
        frame=SemanticFrame(
            intent=intent,
            target=TargetReference(
                text=location[0], domain=domain, device_class=device_class
            ),
            area=(
                AreaReference(
                    text=location[0], area_id=area_id, area_name=matched[0].area_name
                )
                if area_id is not None
                else None
            ),
            quantifier=Quantifier(kind="all") if len(matched) > 1 else None,
            parameters={
                "property": property_name,
                "property_label": label,
                "average": average,
                "location_kind": "area" if area_id is not None else "floor",
                "location_id": area_id if area_id is not None else floor_id,
            },
            source_text=text,
            action=SemanticAction.QUERY,
        ),
        resolved_entities=matched,
    )


def _tokens(text: str) -> set[str]:
    return {
        normalize_for_compare(token)
        for token in _TOKEN_RE.findall(text)
        if normalize_for_compare(token) not in _STOP_WORDS
    }


def _has_unexplained_meaning(analysis, dynamic_texts=()) -> bool:
    """Whether lexical coverage leaves non-registry meaning unexplained."""
    dynamic_tokens = {
        token
        for dynamic_text in dynamic_texts
        if dynamic_text
        for token in _tokens(dynamic_text)
    }
    return bool({
        normalize_for_compare(token)
        for token in analysis.unexplained_tokens
    } - dynamic_tokens)


def _has_registry_typo(
    analysis: SemanticAnalysis, candidates: list[EntitySnapshot]
) -> bool:
    """Detect a bounded name typo hidden by an exact partial alias.

    The canonical resolver intentionally accepts distinctive fragments such
    as ``links``.  That fragment must not silently hide the misspelled first
    half of ``Deckenlicth links`` and authorize an action.
    """
    unexplained = {
        normalize_for_compare(token)
        for token in analysis.unexplained_tokens
        if len(normalize_for_compare(token)) >= 4
    }
    registry_tokens = {
        token
        for entity in candidates
        for name in (entity.friendly_name, *entity.aliases)
        for token in _tokens(name)
        if len(token) >= 4
    }
    return any(
        spoken != registered
        and bounded_name_similarity(spoken, registered).accepted
        for spoken in unexplained
        for registered in registry_tokens
    )


def _quantity(text: str) -> Quantifier | None:
    if _ORDERED_SUBSET_RE.search(text):
        return None
    if _BOTH_RE.search(text):
        return Quantifier("both")
    count = _COUNT_RE.search(text)
    if count:
        raw = count.group(1).casefold()
        return Quantifier("count", _COUNT_WORDS.get(raw, int(raw) if raw.isdigit() else None))
    if _ALL_RE.search(text) or _PLURAL_RE.search(text):
        return Quantifier("all")
    return None


def _percent(text: str) -> int | None:
    if _HALF_RE.search(text):
        return 50
    if _ZERO_RE.search(text):
        return 0
    if _HUNDRED_RE.search(text):
        return 100
    if _FIFTY_PERCENT_RE.search(text):
        return 50
    match = _PERCENT_RE.search(text)
    return int(match.group("after") or match.group("unit")) if match else None


def _temperature(text: str) -> int | None:
    match = _TEMPERATURE_RE.search(text)
    if match is None:
        return None
    value = int(match.group("value"))
    return value if 5 <= value <= 30 else None


def _split_exclusion(text: str) -> tuple[str, tuple[str, ...]]:
    """Return the positive command and independently named exclusions."""
    match = _EXCLUSION_RE.search(text)
    if match is None:
        return text, ()
    raw_targets = tuple(
        cleaned
        for part in _EXCLUSION_SPLIT_RE.split(match.group("targets"))
        if (cleaned := _EXCLUSION_ARTICLE_RE.sub("", part).strip(" ,.;:!?"))
    )
    positive = text[:match.start()].rstrip(" ,;:")
    if tail := match.group("tail"):
        positive = f"{positive} {tail}"
    return positive, raw_targets


def has_exclusion_clause(text: str) -> bool:
    """Return whether *text* explicitly introduces one or more exceptions."""
    return _EXCLUSION_CUE_RE.search(text) is not None


def canonicalize_exclusion_clause(text: str) -> str:
    """Move an exclusion behind a separable particle for legacy grammars.

    The semantic compiler itself consumes the split representation directly.
    Automation action Hassil grammars still use the established canonical
    ``... aus außer Name`` shape, so this small adapter lets both word orders
    share the same safe entity-resolution path.
    """
    positive, targets = _split_exclusion(text)
    if not targets:
        return text
    return f"{positive} außer {' und '.join(targets)}"


def _resolve_exclusions(
    names: tuple[str, ...],
    entities: list[EntitySnapshot],
    candidates: list[EntitySnapshot],
) -> tuple[list[EntitySnapshot], tuple[str, ...]] | None:
    """Resolve every exclusion exactly and ensure it belongs to the scope."""
    if not names:
        return candidates, ()
    excluded: list[EntitySnapshot] = []
    for name in names:
        result = resolve_entity(name, entities)
        if result.status is not ResolveStatus.OK or result.entity is None:
            return None
        if result.entity not in candidates or result.entity in excluded:
            return None
        excluded.append(result.entity)
    excluded_ids = {entity.entity_id for entity in excluded}
    remaining = [entity for entity in candidates if entity.entity_id not in excluded_ids]
    if not remaining:
        return None
    return remaining, tuple(entity.friendly_name for entity in excluded)


def _scoped_candidates(
    entities: list[EntitySnapshot],
    domain: str,
    locations: tuple[tuple[str, str | None, str | None], ...],
    world_model: WorldModel | None,
) -> list[EntitySnapshot]:
    """Return one stable union for one or more explicit location scopes."""
    scopes = locations or (("", None, None),)
    selected: list[EntitySnapshot] = []
    seen: set[str] = set()
    for _, area_id, floor_id in scopes:
        matches = list(world_model.select_entities(
            domain=domain, area_id=area_id, floor_id=floor_id,
        )) if world_model is not None else resolve_candidates(
            entities,
            Constraints(domain=domain, area_id=area_id, floor_id=floor_id),
        )
        for entity in matches:
            if entity.entity_id not in seen:
                seen.add(entity.entity_id)
                selected.append(entity)
    return selected


def _intents(
    text: str,
    domains: frozenset[str],
    percent: int | None,
    temperature: int | None,
    analysis=None,
    *,
    location_text: str | None = None,
) -> frozenset[str]:
    analysis = analysis or analyse_semantics(text)
    has_command_marker = bool(analysis.values(SemanticKind.COMMAND_MARKER))
    # Natural voice commands are often elliptical ("Küchenlicht bitte an",
    # "Rollladen nach oben") or expressed as a wish/passive construction.
    # Action + resolvable target is sufficient unless the utterance is an
    # indicative state statement; candidate resolution below remains the
    # safety boundary and never guesses an entity.
    actions = frozenset(
        span.value
        for span in analysis.matching(SemanticKind.ACTION)
        if not (
            location_text is not None
            and location_text.casefold() in {"oben", "unten"}
            and span.text.casefold() == location_text.casefold()
        )
    )
    elliptical_request = (
        bool(actions)
        and (
            _DIRECTIVE_RE.search(text) is not None
            or _COPULA_STATEMENT_RE.search(text) is None
        )
    ) or (
        (percent is not None or temperature is not None)
        and _DIRECTIVE_RE.search(text) is not None
    )
    if not has_command_marker and not elliptical_request:
        return frozenset()
    found: set[str] = set()
    if percent is not None:
        found.update(
            intent
            for domain in domains
            for property_name in ("position", "brightness")
            if (
                intent := VALUE_INTENT_BY_DOMAIN_PROPERTY.get(
                    (domain, property_name)
                )
            ) is not None
        )
    if temperature is not None:
        found.update(
            intent
            for domain in domains
            if (
                intent := VALUE_INTENT_BY_DOMAIN_PROPERTY.get(
                    (domain, "temperature")
                )
            ) is not None
        )
    for domain in domains:
        for action in actions:
            intent = INTENT_BY_DOMAIN_ACTION.get((domain, str(action)))
            if intent is not None:
                found.add(intent)
    return frozenset(found)


def _entity_candidates(
    text: str,
    entities: list[EntitySnapshot],
    domains: frozenset[str],
    *,
    area_id: str | None = None,
    floor_id: str | None = None,
    world_model: WorldModel | None = None,
) -> list[EntitySnapshot]:
    ignored = frozenset(SEMANTIC_RESOLUTION_WORDS | _STOP_WORDS)
    ranked = rank_semantic_targets(
        text,
        entities,
        domains=domains,
        area_id=area_id,
        floor_id=floor_id,
        ignored_tokens=ignored,
        index=world_model.entity_index if world_model is not None else None,
    )
    if not ranked:
        return []
    top = ranked[0].score
    return [
        item.entity
        for item in ranked
        if top - item.score <= V7_ENTITY_AMBIGUITY_MARGIN
    ]


class SemanticCommandCompiler:
    """Compile a direct command from semantic facts and live HA constraints."""

    @staticmethod
    def compile(
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        analysis: SemanticAnalysis | None = None,
    ) -> ParseResult | ClarificationRequest | None:
        if _QUESTION_RE.search(text):
            return None
        if _ORDERED_SUBSET_RE.search(text):
            return None
        positive_text, exclusion_names = _split_exclusion(text)
        # Analyse only the positive clause: entity names after ``außer`` are
        # registry data, not command semantics, and must not introduce a
        # second domain/action into the requested operation.
        analysis = analyse_semantics(positive_text) if exclusion_names else (
            analysis or analyse_semantics(text)
        )
        spoken_percent = _ANY_PERCENT_RE.search(positive_text)
        if spoken_percent is not None and int(spoken_percent.group("value")) > 100:
            return None
        spoken_temperature = _TEMPERATURE_RE.search(positive_text)
        if spoken_temperature is not None and not (
            5 <= int(spoken_temperature.group("value")) <= 30
        ):
            return None

        domains = frozenset(
            value for value in analysis.values(SemanticKind.DOMAIN)
            if isinstance(value, str)
        )
        coordinated_locations = resolve_coordinated_locations(
            positive_text, entities, world_model
        )
        location = (
            None
            if coordinated_locations
            else resolve_semantic_location(positive_text, entities, world_model)
        )
        locations = coordinated_locations or ((location,) if location else ())
        # A spoken scope is a hard constraint.  If HA does not know it (or
        # two floors make "oben" ambiguous), never silently widen the
        # request to every device in the house.
        if not locations and has_explicit_location_cue(positive_text, entities):
            return None
        quantity = _quantity(positive_text)
        temperature = _temperature(positive_text)
        # ``auf 22 Grad`` and ``auf 22 Prozent`` share the same numeric
        # preposition.  The explicit temperature unit owns the value and
        # prevents the bare-percentage shorthand from creating a second
        # intent.
        percent = None if temperature is not None else _percent(positive_text)

        # If the user named an entity but omitted a generic device noun, infer
        # only the domain(s) of registry names that are actually present.
        if not domains:
            preliminary = _entity_candidates(
                positive_text,
                entities,
                domains,
                area_id=location[1] if location else None,
                floor_id=location[2] if location else None,
                world_model=world_model,
            )
            if preliminary:
                domains = frozenset(entity.domain for entity in preliminary)

        intents = _intents(
            positive_text,
            domains,
            percent,
            temperature,
            analysis,
            location_text=location[0] if location else None,
        )
        facts = SemanticFacts(
            intents=intents,
            domains=domains,
            percent=percent,
            temperature=temperature,
            quantity=quantity,
            location_text=" und ".join(item[0] for item in locations) if locations else None,
            area_id=location[1] if location else None,
            floor_id=location[2] if location else None,
        )
        if len(facts.intents) != 1 or len(facts.domains) != 1:
            return None
        intent = next(iter(facts.intents))
        domain = next(iter(facts.domains))
        if intent == "HassSetPercentage" and domain not in {"cover", "light"}:
            return None

        if quantity is not None:
            if exclusion_names and quantity.kind in {"both", "count"}:
                # "genau drei außer X" has two plausible counts (before or
                # after exclusion). Refuse instead of choosing one silently.
                return None
            matches = _scoped_candidates(entities, domain, locations, world_model)
            if percent is not None:
                capability = "POSITION" if domain == "cover" else "BRIGHTNESS"
                matches = [entity for entity in matches if capability in entity.capabilities]
            if not matches:
                return None
            if quantity.kind == "both" and len(matches) != 2:
                return None
            if quantity.kind == "count" and len(matches) != quantity.value:
                return None
            exclusion_result = _resolve_exclusions(exclusion_names, entities, matches)
            if exclusion_result is None:
                return None
            matches, excluded_names = exclusion_result
            target = TargetReference(text=domain, domain=domain)
            area = (
                AreaReference(text=facts.location_text or "", area_id=facts.area_id)
                if facts.area_id is not None and len(locations) == 1 else None
            )
        else:
            if exclusion_names or len(locations) > 1:
                return None
            ranked_candidates = rank_semantic_targets(
                text,
                entities,
                domains=facts.domains,
                area_id=facts.area_id,
                floor_id=facts.floor_id,
                ignored_tokens=frozenset(SEMANTIC_RESOLUTION_WORDS | _STOP_WORDS),
                index=world_model.entity_index if world_model is not None else None,
            )
            top_score = ranked_candidates[0].score if ranked_candidates else 0
            selected_ranked = [
                item
                for item in ranked_candidates
                if top_score - item.score <= V7_ENTITY_AMBIGUITY_MARGIN
            ]
            candidates = [item.entity for item in selected_ranked]
            if len(candidates) > 1:
                return ClarificationRequest(
                    intent,
                    domain,
                    tuple(candidates),
                    {
                        **({"percent": percent} if percent is not None else {}),
                        **({"temperature": temperature} if temperature is not None else {}),
                    },
                )
            if selected_ranked and selected_ranked[0].source == "fuzzy":
                return ClarificationRequest(
                    intent,
                    domain,
                    tuple(candidates),
                    {
                        **({"percent": percent} if percent is not None else {}),
                        **({"temperature": temperature} if temperature is not None else {}),
                    },
                )
            if len(candidates) != 1:
                return None
            matches = candidates
            entity = matches[0]
            target = TargetReference(entity.friendly_name, entity.entity_id, entity.domain)
            area = None

        registry_texts = [facts.location_text or ""]
        for entity in matches:
            registry_texts.extend((
                entity.friendly_name,
                entity.area_name or "",
                entity.floor_name or "",
                *(alias.text for alias in generate_aliases(entity)),
            ))
        if _has_unexplained_meaning(analysis, registry_texts):
            fuzzy = resolve_entity_scored(
                " ".join(analysis.unexplained_tokens),
                [entity for entity in entities if entity.domain == domain],
                area_id=facts.area_id,
                domain=domain,
            )
            if fuzzy.status in {
                ResolutionStatus.AMBIGUOUS,
                ResolutionStatus.CONFIRMATION_REQUIRED,
            } and fuzzy.candidates:
                return ClarificationRequest(
                    intent,
                    domain,
                    fuzzy.candidates,
                    {
                        **({"percent": percent} if percent is not None else {}),
                        **({"temperature": temperature} if temperature is not None else {}),
                    },
                    (
                        fuzzy.candidate_set.ranked
                        if fuzzy.candidate_set is not None
                        else ()
                    ),
                )
            if _has_registry_typo(analysis, matches):
                return ClarificationRequest(
                    intent,
                    domain,
                    tuple(matches),
                    {
                        **({"percent": percent} if percent is not None else {}),
                        **(
                            {"temperature": temperature}
                            if temperature is not None
                            else {}
                        ),
                    },
                )
            return None

        action = {
            "HassTurnOn": SemanticAction.TURN_ON,
            "HassTurnOff": SemanticAction.TURN_OFF,
            "HassToggle": SemanticAction.TOGGLE,
            "HassOpenCover": SemanticAction.OPEN,
            "HassCloseCover": SemanticAction.CLOSE,
            "HassRunScript": SemanticAction.TURN_ON,
            "HassActivateScene": SemanticAction.TURN_ON,
            "HassMediaPlay": SemanticAction.START,
            "HassMediaPause": SemanticAction.PAUSE,
            "HassMediaStop": SemanticAction.STOP,
            "HassVacuumStart": SemanticAction.START,
            "HassVacuumStop": SemanticAction.STOP,
            "HassOpenValve": SemanticAction.OPEN,
            "HassCloseValve": SemanticAction.CLOSE,
            "HassSetPercentage": SemanticAction.SET,
            "HassClimateSetTemperature": SemanticAction.SET,
        }[intent]
        property_ = None
        if intent == "HassSetPercentage":
            property_ = SemanticProperty.POSITION if domain == "cover" else SemanticProperty.BRIGHTNESS
        elif intent == "HassClimateSetTemperature":
            property_ = SemanticProperty.TEMPERATURE
        semantic_quantity = None
        if quantity is not None:
            semantic_quantity = (
                SemanticQuantity.exactly(2) if quantity.kind == "both"
                else SemanticQuantity.exactly(quantity.value) if quantity.kind == "count" and quantity.value is not None
                else SemanticQuantity.all()
            )
            if exclusion_names:
                semantic_quantity = SemanticQuantity.exclude(*excluded_names)
        return ParseResult(
            frame=SemanticFrame(
                intent=intent,
                target=target,
                area=area,
                quantifier=quantity,
                parameters={
                    **({"percent": percent} if percent is not None else {}),
                    **({"temperature": temperature} if temperature is not None else {}),
                    **({"excluded": excluded_names} if exclusion_names else {}),
                    **({
                        "locations": tuple(
                            {"text": spoken, "area_id": area_id, "floor_id": floor_id}
                            for spoken, area_id, floor_id in locations
                        )
                    } if len(locations) > 1 else {}),
                },
                source_text=text,
                action=action,
                property=property_,
                quantity=semantic_quantity,
            ),
            resolved_entities=matches,
        )


class SemanticQueryCompiler:
    """Compile read-only plural queries from freely ordered semantic facts."""

    @staticmethod
    def compile(
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        analysis: SemanticAnalysis | None = None,
    ) -> ParseResult | None:
        # A question mark alone also supports terse chat-style questions such
        # as "Offene Fenster im Erdgeschoss?".  An imperative verb always
        # wins the command interpretation and is never converted to a query.
        analysis = analysis or analyse_semantics(text)
        if analysis.values(SemanticKind.PROPERTY):
            return _compile_measurement_query(
                text, entities, analysis, world_model
            )
        if (
            not (_QUERY_MARKER_RE.search(text) or text.rstrip().endswith("?"))
            or analysis.values(SemanticKind.COMMAND_MARKER)
            or analysis.values(SemanticKind.COMPARATOR)
            or _DURATION_QUESTION_RE.search(text)
        ):
            return None

        targets = _device_class_targets(analysis)
        targets.extend(
            (domain, None)
            for domain in analysis.values(SemanticKind.DOMAIN)
            if isinstance(domain, str)
        )
        targets = list(dict.fromkeys(targets))
        named_mentions: tuple[EntitySnapshot, ...] = ()
        needs_named_resolution = (
            not targets
            or bool(analysis.unexplained_tokens)
            or _SINGULAR_NAMED_QUERY_RE.search(text) is not None
            or _BARE_NAMED_STATE_QUERY_RE.search(text) is not None
        )
        if needs_named_resolution:
            named_mentions = mentioned_entities(text, entities)
        if not targets:
            if named_mentions:
                named_domains = {entity.domain for entity in named_mentions}
                named_device_classes = {
                    entity.device_class for entity in named_mentions
                }
                if len(named_domains) == 1 and len(named_device_classes) == 1:
                    targets.append(
                        (
                            next(iter(named_domains)),
                            next(iter(named_device_classes)),
                        )
                    )
        states = [
            value
            for value in analysis.values(SemanticKind.STATE)
            if isinstance(value, SemanticState)
        ]
        if len(targets) != 1 or len(states) > 1:
            return None
        domain, device_class = targets[0]
        if domain not in QUERYABLE_STATE_DOMAINS:
            return None
        requested_state = states[0] if states else None
        if requested_state is not None and not supports_state_predicate(
            domain, requested_state, device_class
        ):
            return None

        coordinated_locations = resolve_coordinated_locations(
            text, entities, world_model
        )
        location = (
            None
            if coordinated_locations
            else resolve_semantic_location(text, entities, world_model)
        )
        locations = coordinated_locations or ((location,) if location else ())
        has_location_cue = _LOCATION_CUE_RE.search(text) is not None
        if has_location_cue and not locations:
            return None
        # Unknown modifiers may materially change a question (for example
        # "normalerweise", "gestern" or "nicht").  Do not pretend they were
        # understood. Dynamic registry location and entity names are removed
        # from this check because they cannot live in the lexicon.
        registry_texts = [item[0] for item in locations]
        for entity in named_mentions:
            registry_texts.extend((entity.friendly_name, *entity.aliases))
        if _has_unexplained_meaning(
            analysis, tuple(registry_texts)
        ):
            return None
        area_id = location[1] if location else None
        floor_id = location[2] if location else None
        location_name = location[0] if location else None

        named_candidates = [
            entity
            for entity in named_mentions
            if entity.domain == domain
            and (device_class is None or entity.device_class == device_class)
        ]
        if named_candidates:
            candidates = named_candidates
        elif len(locations) > 1:
            candidates = _scoped_candidates(entities, domain, locations, world_model)
            if device_class is not None:
                candidates = [
                    entity for entity in candidates
                    if entity.device_class == device_class
                ]
        else:
            candidates = list(world_model.select_entities(
                domain=domain,
                device_class=device_class,
                area_id=area_id,
                floor_id=floor_id,
            )) if world_model is not None else resolve_candidates(
                entities, Constraints(
                    domain=domain,
                    device_class=device_class,
                    area_id=area_id,
                    floor_id=floor_id,
                ),
            )
        # The target category itself must exist. An empty *state match* is a
        # valid answer, but inventing an answer for a home with no such
        # selected entities would hide configuration errors.
        if not candidates:
            return None

        scopes = analysis.values(SemanticKind.QUERY_SCOPE)
        quantities = analysis.values(SemanticKind.QUANTIFIER)
        singular_state_question = (
            _SINGULAR_NAMED_QUERY_RE.search(text) is not None
            or (
                _BARE_NAMED_STATE_QUERY_RE.search(text) is not None
                and len(named_candidates) == 1
            )
        )
        if singular_state_question:
            if len(candidates) != 1 or (
                requested_state is None
                and _BARE_NAMED_STATE_QUERY_RE.search(text) is None
            ):
                return None
            scope = QueryScope.SINGLE
        elif "none" in scopes:
            if requested_state is None:
                return None
            scope = QueryScope.NONE
        elif "all" in quantities or "both" in quantities:
            if requested_state is None:
                return None
            if "both" in quantities and len(candidates) != 2:
                return None
            scope = QueryScope.ALL
        elif "count" in scopes:
            scope = QueryScope.COUNT
        elif "locations" in scopes:
            scope = QueryScope.LOCATIONS
        elif "exists" in scopes:
            scope = QueryScope.EXISTS
        else:
            scope = QueryScope.LIST

        intent = (
            "HassCheckState"
            if scope is QueryScope.SINGLE
            else "HassExistsQuery" if scope is QueryScope.EXISTS else "HassStateQuery"
        )
        area_snapshot = (
            AreaSnapshot(area_id=area_id, name=location_name)
            if area_id is not None and location_name is not None and len(locations) == 1
            else None
        )
        query_command = QueryCommand(
            intent=intent,
            scope=scope,
            target=QueryTarget(
                domain=domain,
                device_class=device_class,
                area=area_snapshot,
                floor_id=floor_id,
                entity_id=(candidates[0].entity_id if scope is QueryScope.SINGLE else None),
            ),
            filter=QueryFilter(state=requested_state),
        )
        query_result = _QUERY_EXECUTOR.execute(query_command, candidates)

        semantic_quantity = (
            SemanticQuantity.exactly(2)
            if "both" in quantities
            else SemanticQuantity.all()
        )
        return ParseResult(
            frame=SemanticFrame(
                intent=intent,
                target=TargetReference(
                    text=device_class or domain,
                    domain=domain,
                    device_class=device_class,
                ),
                area=(
                    AreaReference(
                        text=location_name,
                        area_id=area_id,
                        area_name=location_name,
                    )
                    if area_id is not None and location_name is not None
                    else None
                ),
                quantifier=Quantifier("all"),
                parameters={
                    "semantic_state": requested_state,
                    "count_only": scope is QueryScope.COUNT,
                    "all_requested": scope is QueryScope.ALL,
                    "none_requested": scope is QueryScope.NONE,
                    "locations_requested": scope is QueryScope.LOCATIONS,
                    "device_class": device_class,
                    "domain": domain,
                    "floor_id": floor_id,
                    "floor_name": location_name if floor_id is not None else None,
                    "locations": tuple(
                        {"text": spoken, "area_id": item_area_id, "floor_id": item_floor_id}
                        for spoken, item_area_id, item_floor_id in locations
                    ) if len(locations) > 1 else (),
                    "query_command": query_command,
                    "query_result": query_result,
                },
                source_text=text,
                action=SemanticAction.QUERY,
                quantity=semantic_quantity,
            ),
            resolved_entities=list(query_result.entities),
        )
