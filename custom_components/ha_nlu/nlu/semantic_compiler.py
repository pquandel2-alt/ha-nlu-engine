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
from ..world_model import WorldModel
from .constraint_resolver import Constraints, resolve_candidates
from .entity_resolution import ResolveStatus, resolve_entity
from .frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from .parser import ClarificationRequest, ParseResult
from .primitives import SemanticAction, SemanticProperty, SemanticQuantity
from .query_command import QueryCommand, QueryFilter, QueryScope, QueryTarget
from .query_executor import QueryExecutor
from .semantic_lexicon import SemanticAnalysis, SemanticKind, analyse_semantics
from .domain_operations import DOMAIN_WORDS, INTENT_BY_DOMAIN_ACTION
from .semantic_location import (
    has_explicit_location_cue,
    resolve_coordinated_locations,
    resolve_semantic_location,
)
from .semantic_state import QUERYABLE_STATE_DOMAINS, supports_state_predicate


@dataclass(frozen=True)
class SemanticFacts:
    """Observable facts extracted without committing to an execution."""

    intents: frozenset[str]
    domains: frozenset[str]
    percent: int | None
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
    r"\b(?:lichter|lampen|leuchten|steckdosen|rollläden|rolläden|rollos|"
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
_EXCLUSION_RE = re.compile(
    r"\b(?:außer|ausser|mit\s+ausnahme\s+von)\s+(?P<targets>.+?)\s*[?.!]*$",
    re.I,
)
_EXCLUSION_SPLIT_RE = re.compile(r"\s*(?:,|\bund\b)\s*", re.I)
_EXCLUSION_ARTICLE_RE = re.compile(
    r"^(?:(?:dem|der|den|die|das|alle[nrms]?|im|in\s+der|in\s+dem)\s+)+",
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
_SEMANTIC_WORDS = {
    "mache", "machen", "mach", "schalte", "schalten", "stelle", "stellen",
    "setze", "setzen", "fahre", "fahren", "fahr", "gefahren", "öffne", "öffnen", "schließe",
    "schließen", "drehe", "drehen", "lass", "lassen", "hoch", "runter", "herunter",
    "halb", "halbe", "halber", "halben", "hälfte", "höhe", "prozent", "komplett", "ganz", "vollständig", "einschalten",
    "ausschalten", "anmachen", "ausmachen", "aktivieren", "aktiviere", "starten",
    "starte", "ausführen", "führe", "umschalten", "toggle",
    "spiele", "spielen", "spiel", "weiter", "weiterspielen", "pausiere",
    "pausieren", "pausiert", "halte", "halten", "stoppe", "stoppen", "gestoppt",
}
# Concrete surface forms are used for entity-name scoring. Regex lexemes
# remain the authoritative recognition source; this table merely marks
# generic nouns as non-distinctive.
_DOMAIN_CANONICAL = {
    word: domain for domain, words in DOMAIN_WORDS.items() for word in words
}

_QUERY_MARKER_RE = re.compile(
    r"\b(?:ist|sind|welch\w*|wie\s+viele|wo|gibt\s+es|haben\s+wir|irgendein\w*|keine?\w*)\b",
    re.I,
)
_SINGULAR_NAMED_QUERY_RE = re.compile(r"^\s*ist\s+(?:das|der|die)\b", re.I)
_DURATION_QUESTION_RE = re.compile(r"^\s*wie\s+lange\b", re.I)

_QUERY_EXECUTOR = QueryExecutor()


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
    return text[:match.start()].rstrip(" ,;:"), raw_targets


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
        percent is not None and _DIRECTIVE_RE.search(text) is not None
    )
    if not has_command_marker and not elliptical_request:
        return frozenset()
    found: set[str] = set()
    if percent is not None:
        found.add("HassSetPercentage")
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
) -> list[EntitySnapshot]:
    utterance = _tokens(text) - _SEMANTIC_WORDS
    scored: list[tuple[int, EntitySnapshot]] = []
    scoped_entities = resolve_candidates(
        entities,
        Constraints(area_id=area_id, floor_id=floor_id),
    )
    for entity in scoped_entities:
        if domains and entity.domain not in domains:
            continue
        best = 0
        names = (
            ((entity.friendly_name, "friendly_name"),)
            + tuple((alias, "configured") for alias in entity.aliases)
            + tuple((alias.text, alias.source) for alias in generate_aliases(entity))
        )
        for name, source in names:
            name_tokens = _tokens(name)
            distinctive = {token for token in name_tokens if _DOMAIN_CANONICAL.get(token) is None}
            # Generic one-word names ("Rollladen") remain valid, but only
            # when they are unique; ambiguity is handled below.
            # Humanized entity IDs ("Buero Steckdose") must not match from
            # the location word alone. Friendly/configured names may omit a
            # generic domain noun and therefore keep distinctive matching.
            required = (
                name_tokens
                if source in {"entity_name", "entity_id"}
                else distinctive or name_tokens
            )
            if required and required <= utterance:
                best = max(best, len(required) * 10 + len(name_tokens))
        if best:
            scored.append((best, entity))
    if not scored:
        return []
    top = max(score for score, _ in scored)
    return [entity for score, entity in scored if score == top]


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

        domains = frozenset(
            value for value in analysis.values(SemanticKind.DOMAIN)
            if isinstance(value, str)
        )
        coordinated_locations = resolve_coordinated_locations(positive_text, entities)
        location = None if coordinated_locations else resolve_semantic_location(positive_text, entities)
        locations = coordinated_locations or ((location,) if location else ())
        # A spoken scope is a hard constraint.  If HA does not know it (or
        # two floors make "oben" ambiguous), never silently widen the
        # request to every device in the house.
        if not locations and has_explicit_location_cue(positive_text, entities):
            return None
        quantity = _quantity(positive_text)
        percent = _percent(positive_text)

        # If the user named an entity but omitted a generic device noun, infer
        # only the domain(s) of registry names that are actually present.
        preliminary = _entity_candidates(
            positive_text,
            entities,
            domains,
            area_id=location[1] if location else None,
            floor_id=location[2] if location else None,
        )
        if not domains and preliminary:
            domains = frozenset(entity.domain for entity in preliminary)

        intents = _intents(
            positive_text,
            domains,
            percent,
            analysis,
            location_text=location[0] if location else None,
        )
        facts = SemanticFacts(
            intents=intents,
            domains=domains,
            percent=percent,
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
            candidates = _entity_candidates(
                text,
                entities,
                facts.domains,
                area_id=facts.area_id,
                floor_id=facts.floor_id,
            )
            if len(candidates) > 1:
                return ClarificationRequest(intent, domain, tuple(candidates), {"percent": percent} if percent is not None else {})
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
        }[intent]
        property_ = None
        if intent == "HassSetPercentage":
            property_ = SemanticProperty.POSITION if domain == "cover" else SemanticProperty.BRIGHTNESS
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
        if (
            not (_QUERY_MARKER_RE.search(text) or text.rstrip().endswith("?"))
            or analysis.values(SemanticKind.COMMAND_MARKER)
            or analysis.values(SemanticKind.PROPERTY)
            or analysis.values(SemanticKind.COMPARATOR)
            or _DURATION_QUESTION_RE.search(text)
        ):
            return None

        targets = list(analysis.values(SemanticKind.DEVICE_CLASS))
        targets.extend(
            (domain, None)
            for domain in analysis.values(SemanticKind.DOMAIN)
            if isinstance(domain, str)
        )
        targets = list(dict.fromkeys(targets))
        states = list(analysis.values(SemanticKind.STATE))
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

        coordinated_locations = resolve_coordinated_locations(text, entities)
        location = None if coordinated_locations else resolve_semantic_location(text, entities)
        locations = coordinated_locations or ((location,) if location else ())
        has_location_cue = _LOCATION_CUE_RE.search(text) is not None
        if has_location_cue and not locations:
            return None
        # Unknown modifiers may materially change a question (for example
        # "normalerweise", "gestern" or "nicht").  Do not pretend they were
        # understood. Dynamic registry location names are deliberately
        # removed from this check because they cannot live in the lexicon.
        if _has_unexplained_meaning(
            analysis, tuple(item[0] for item in locations)
        ):
            return None
        area_id = location[1] if location else None
        floor_id = location[2] if location else None
        location_name = location[0] if location else None

        if len(locations) > 1:
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
        singular_state_question = _SINGULAR_NAMED_QUERY_RE.search(text) is not None
        if singular_state_question:
            if requested_state is None or len(candidates) != 1:
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
