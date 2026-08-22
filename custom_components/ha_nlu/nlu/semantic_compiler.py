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
from ..entities import EntitySnapshot, generate_aliases, normalize_for_compare
from ..floors import FloorResolveStatus, resolve_floor_by_level_keyword
from .constraint_resolver import Constraints, resolve_candidates
from .frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from .group_semantics import resolve_group_location
from .parser import ClarificationRequest, ParseResult
from .primitives import SemanticAction, SemanticProperty, SemanticQuantity
from .query_command import QueryCommand, QueryFilter, QueryScope, QueryTarget
from .query_executor import QueryExecutor
from .semantic_state import SemanticState


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
_DOMAIN_PATTERNS = {
    "light": re.compile(r"\b(?:licht(?:er)?|lamp(?:e|en)|leucht(?:e|en)|beleuchtung)\b", re.I),
    "switch": re.compile(r"\b(?:schalter|steckdos(?:e|en))\b", re.I),
    "cover": re.compile(r"\b(?:rol{2,3}[aä]d(?:e|en)|rollos?|jalousie(?:n)?)\b", re.I),
    "fan": re.compile(r"\b(?:ventilator(?:en)?|lüfter)\b", re.I),
    "climate": re.compile(r"\b(?:heizung(?:en)?|thermostat(?:e)?)\b", re.I),
    "script": re.compile(r"\b(?:skript(?:e)?)\b", re.I),
}
_PLURAL_RE = re.compile(
    r"\b(?:lichter|lampen|leuchten|steckdosen|rollläden|rolläden|rollos|"
    r"jalousien|ventilatoren|heizungen|thermostate|skripte)\b",
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

_COMMAND_VERB_RE = re.compile(
    r"\b(?:(?:an|aus)mach(?:e|en)?|(?:ein|aus)schalt(?:e|en)?|"
    r"mach(?:e|en)?|schalt(?:e|en)?|stell(?:e|en)?|setz(?:e|en)?|"
    r"fahr(?:e|en)?|gefahren|öffn(?:e|en)?|schließ(?:e|en)?|dreh(?:e|en)?|"
    r"lass(?:e|en)?|aktivier(?:e|en)?|start(?:e|en)?|führ(?:e|en)?)\b",
    re.I,
)
_OPEN_RE = re.compile(r"\b(?:hoch|oben|hochgefahren|öffn(?:e|en)?|auf)\b", re.I)
_CLOSE_RE = re.compile(r"\b(?:runter|herunter|geschlossen|schließ(?:e|en)?|zu)\b", re.I)
_ON_RE = re.compile(r"\b(?:an|ein|anmachen|einschalten|eingeschaltet|aktivier(?:e|en)?)\b", re.I)
_OFF_RE = re.compile(r"\b(?:aus|ausmachen|ausschalten|ausgeschaltet|deaktivier(?:e|en)?)\b", re.I)
_TOGGLE_RE = re.compile(r"\b(?:umschalten|toggle)\b", re.I)
_RUN_RE = re.compile(r"\b(?:start(?:e|en)?|aktivier(?:e|en)?|ausführen|führe)\b", re.I)
_HALF_RE = re.compile(r"\b(?:halb|halbe(?:r|n)?|hälfte|zur\s+hälfte)\b", re.I)
_ZERO_RE = re.compile(r"\b(?:komplett|ganz|vollständig)\s+(?:runter|herunter|zu)\b", re.I)
_HUNDRED_RE = re.compile(r"\b(?:komplett|ganz|vollständig)\s+(?:hoch|auf)\b", re.I)
_PERCENT_RE = re.compile(
    r"(?:\bauf\s+(?P<after>100|[1-9]?\d)\b|"
    r"\b(?P<unit>100|[1-9]?\d)\s*(?:prozent|%)\b)", re.I
)
_ANY_PERCENT_RE = re.compile(r"\b(?P<value>\d+)\s*(?:prozent|%)\b", re.I)

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
}
_DOMAIN_CANONICAL = {
    "licht": "light", "lichter": "light", "lampe": "light", "lampen": "light",
    "leuchte": "light", "leuchten": "light", "beleuchtung": "light",
    "schalter": "switch", "steckdose": "switch", "steckdosen": "switch",
    "rollladen": "cover", "rollläden": "cover", "rolladen": "cover", "rolläden": "cover",
    "rollo": "cover", "rollos": "cover", "jalousie": "cover", "jalousien": "cover",
    "ventilator": "fan", "ventilatoren": "fan", "lüfter": "fan",
    "heizung": "climate", "heizungen": "climate", "thermostat": "climate", "thermostate": "climate",
    "skript": "script", "skripte": "script",
}

_QUERY_DEVICE_PATTERNS = {
    ("binary_sensor", "window"): re.compile(r"\bfenster(?:kontakte?)?\b", re.I),
    ("binary_sensor", "door"): re.compile(r"\btür(?:en)?\b", re.I),
    ("binary_sensor", "garage_door"): re.compile(r"\bgaragentor(?:e)?\b", re.I),
    ("binary_sensor", "motion"): re.compile(r"\b(?:bewegungsmelder|bewegungssensor(?:en)?)\b", re.I),
    ("cover", None): _DOMAIN_PATTERNS["cover"],
    ("light", None): _DOMAIN_PATTERNS["light"],
    ("switch", None): _DOMAIN_PATTERNS["switch"],
}
_QUERY_STATE_PATTERNS = {
    SemanticState.OPEN: re.compile(
        r"\b(?:offen\w*|geöffnet\w*|hochgefahren\w*|oben)\b", re.I
    ),
    SemanticState.CLOSED: re.compile(
        r"\b(?:geschlossen\w*|runtergefahren\w*|heruntergefahren\w*|unten|zu)\b", re.I
    ),
    SemanticState.ON: re.compile(r"\b(?:an|ein|eingeschaltet\w*|angeschaltet\w*)\b", re.I),
    SemanticState.OFF: re.compile(r"\b(?:aus|ausgeschaltet\w*)\b", re.I),
}
_QUERY_MARKER_RE = re.compile(
    r"\b(?:ist|sind|welch\w*|wie\s+viele|wo|gibt\s+es|haben\s+wir|irgendein\w*|keine?\w*)\b",
    re.I,
)
_COUNT_QUERY_RE = re.compile(r"\bwie\s+viele\b", re.I)
_LOCATION_QUERY_RE = re.compile(r"\b(?:wo|in\s+welchen\s+räumen|welche\s+räume)\b", re.I)
_EXISTS_QUERY_RE = re.compile(r"\b(?:gibt\s+es|haben\s+wir|irgendein\w*|irgendwelche)\b", re.I)
_ALL_QUERY_RE = re.compile(r"\b(?:alle|sämtliche|sämtlichen|beide)\b", re.I)
_NONE_QUERY_RE = re.compile(r"\b(?:kein|keine|keiner|keines)\b", re.I)
_SINGULAR_NAMED_QUERY_RE = re.compile(r"^\s*ist\s+(?:das|der|die)\b", re.I)
_DURATION_QUESTION_RE = re.compile(r"^\s*wie\s+lange\b", re.I)

_QUERY_EXECUTOR = QueryExecutor()


def _tokens(text: str) -> set[str]:
    return {
        normalize_for_compare(token)
        for token in _TOKEN_RE.findall(text)
        if normalize_for_compare(token) not in _STOP_WORDS
    }


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


def _location(text: str, entities: list[EntitySnapshot]) -> tuple[str, str | None, str | None] | None:
    level = _LEVEL_CUE_RE.search(text)
    if level is not None:
        resolved_level = resolve_floor_by_level_keyword(
            "up" if level.group(0).casefold() == "oben" else "down", entities
        )
        if resolved_level.status is not FloorResolveStatus.OK:
            return None
        return level.group(0), None, resolved_level.floor_id
    names = {
        name
        for entity in entities
        for name in (entity.area_name, *entity.area_aliases, entity.floor_name)
        if name
    }
    mentioned = [
        name for name in sorted(names, key=len, reverse=True)
        if re.search(rf"\b{re.escape(name)}\b", text, re.I)
    ]
    if not mentioned:
        return None
    longest = len(mentioned[0])
    selected = [name for name in mentioned if len(name) == longest]
    resolved = {resolve_group_location(name, entities) for name in selected}
    resolved.discard(None)
    if len(resolved) != 1:
        return None
    area_id, floor_id = resolved.pop()
    return selected[0], area_id, floor_id


def _percent(text: str) -> int | None:
    if _HALF_RE.search(text):
        return 50
    if _ZERO_RE.search(text):
        return 0
    if _HUNDRED_RE.search(text):
        return 100
    match = _PERCENT_RE.search(text)
    return int(match.group("after") or match.group("unit")) if match else None


def _intents(text: str, domains: frozenset[str], percent: int | None) -> frozenset[str]:
    if _COMMAND_VERB_RE.search(text) is None:
        return frozenset()
    found: set[str] = set()
    if percent is not None:
        found.add("HassSetPercentage")
    if "cover" in domains and percent is None:
        if _OPEN_RE.search(text):
            found.add("HassOpenCover")
        if _CLOSE_RE.search(text):
            found.add("HassCloseCover")
    if domains & {"light", "switch", "fan", "climate"}:
        if _TOGGLE_RE.search(text):
            found.add("HassToggle")
        if _ON_RE.search(text):
            found.add("HassTurnOn")
        if _OFF_RE.search(text):
            found.add("HassTurnOff")
    if "script" in domains and _RUN_RE.search(text):
        found.add("HassRunScript")
    return frozenset(found)


def _entity_candidates(text: str, entities: list[EntitySnapshot], domains: frozenset[str]) -> list[EntitySnapshot]:
    utterance = _tokens(text) - _SEMANTIC_WORDS
    scored: list[tuple[int, EntitySnapshot]] = []
    for entity in entities:
        if domains and entity.domain not in domains:
            continue
        best = 0
        names = (entity.friendly_name, *(alias.text for alias in generate_aliases(entity)))
        for name in names:
            name_tokens = _tokens(name)
            distinctive = {token for token in name_tokens if _DOMAIN_CANONICAL.get(token) is None}
            # Generic one-word names ("Rollladen") remain valid, but only
            # when they are unique; ambiguity is handled below.
            required = distinctive or name_tokens
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
        text: str, entities: list[EntitySnapshot]
    ) -> ParseResult | ClarificationRequest | None:
        if _QUESTION_RE.search(text) or re.search(r"\baußer\b", text, re.I):
            return None
        if _ORDERED_SUBSET_RE.search(text):
            return None
        spoken_percent = _ANY_PERCENT_RE.search(text)
        if spoken_percent is not None and int(spoken_percent.group("value")) > 100:
            return None

        domains = frozenset(
            domain for domain, pattern in _DOMAIN_PATTERNS.items() if pattern.search(text)
        )
        location = _location(text, entities)
        # A spoken scope is a hard constraint.  If HA does not know it (or
        # two floors make "oben" ambiguous), never silently widen the
        # request to every device in the house.
        if location is None and (_LOCATION_CUE_RE.search(text) or _LEVEL_CUE_RE.search(text)):
            return None
        quantity = _quantity(text)
        percent = _percent(text)

        # If the user named an entity but omitted a generic device noun, infer
        # only the domain(s) of registry names that are actually present.
        preliminary = _entity_candidates(text, entities, domains)
        if not domains and preliminary:
            domains = frozenset(entity.domain for entity in preliminary)

        intents = _intents(text, domains, percent)
        facts = SemanticFacts(
            intents=intents,
            domains=domains,
            percent=percent,
            quantity=quantity,
            location_text=location[0] if location else None,
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
            matches = resolve_candidates(
                entities,
                Constraints(domain=domain, area_id=facts.area_id, floor_id=facts.floor_id),
            )
            if percent is not None:
                capability = "POSITION" if domain == "cover" else "BRIGHTNESS"
                matches = [entity for entity in matches if capability in entity.capabilities]
            if not matches:
                return None
            if quantity.kind == "both" and len(matches) != 2:
                return None
            if quantity.kind == "count" and len(matches) != quantity.value:
                return None
            target = TargetReference(text=domain, domain=domain)
            area = (
                AreaReference(text=facts.location_text or "", area_id=facts.area_id)
                if facts.area_id is not None else None
            )
        else:
            candidates = _entity_candidates(text, entities, facts.domains)
            if len(candidates) > 1:
                return ClarificationRequest(intent, domain, tuple(candidates), {"percent": percent} if percent is not None else {})
            if len(candidates) != 1:
                return None
            matches = candidates
            entity = matches[0]
            target = TargetReference(entity.friendly_name, entity.entity_id, entity.domain)
            area = None

        action = {
            "HassTurnOn": SemanticAction.TURN_ON,
            "HassTurnOff": SemanticAction.TURN_OFF,
            "HassToggle": SemanticAction.TOGGLE,
            "HassOpenCover": SemanticAction.OPEN,
            "HassCloseCover": SemanticAction.CLOSE,
            "HassRunScript": SemanticAction.TURN_ON,
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
        return ParseResult(
            frame=SemanticFrame(
                intent=intent,
                target=target,
                area=area,
                quantifier=quantity,
                parameters={"percent": percent} if percent is not None else {},
                source_text=text,
                action=action,
                property=property_,
                quantity=semantic_quantity,
            ),
            resolved_entities=matches,
        )


class SemanticQueryCompiler:
    """Compile plural state questions from freely ordered semantic facts."""

    @staticmethod
    def compile(text: str, entities: list[EntitySnapshot]) -> ParseResult | None:
        # A question mark alone also supports terse chat-style questions such
        # as "Offene Fenster im Erdgeschoss?".  An imperative verb always
        # wins the command interpretation and is never converted to a query.
        if (
            not (_QUERY_MARKER_RE.search(text) or text.rstrip().endswith("?"))
            or _COMMAND_VERB_RE.search(text)
            or _SINGULAR_NAMED_QUERY_RE.search(text)
            or _DURATION_QUESTION_RE.search(text)
        ):
            return None

        targets = [
            (domain, device_class)
            for (domain, device_class), pattern in _QUERY_DEVICE_PATTERNS.items()
            if pattern.search(text)
        ]
        states = [state for state, pattern in _QUERY_STATE_PATTERNS.items() if pattern.search(text)]
        if len(targets) != 1 or len(states) != 1:
            return None
        domain, device_class = targets[0]
        requested_state = states[0]

        location = _location(text, entities)
        has_location_cue = _LOCATION_CUE_RE.search(text) is not None
        if has_location_cue and location is None:
            return None
        area_id = location[1] if location else None
        floor_id = location[2] if location else None
        location_name = location[0] if location else None

        candidates = resolve_candidates(
            entities,
            Constraints(
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

        if _NONE_QUERY_RE.search(text):
            scope = QueryScope.NONE
        elif _ALL_QUERY_RE.search(text):
            if re.search(r"\bbeide\b", text, re.I) and len(candidates) != 2:
                return None
            scope = QueryScope.ALL
        elif _COUNT_QUERY_RE.search(text):
            scope = QueryScope.COUNT
        elif _LOCATION_QUERY_RE.search(text):
            scope = QueryScope.LOCATIONS
        elif _EXISTS_QUERY_RE.search(text):
            scope = QueryScope.EXISTS
        else:
            scope = QueryScope.LIST

        intent = "HassExistsQuery" if scope is QueryScope.EXISTS else "HassStateQuery"
        area_snapshot = (
            AreaSnapshot(area_id=area_id, name=location_name)
            if area_id is not None and location_name is not None
            else None
        )
        query_command = QueryCommand(
            intent=intent,
            scope=scope,
            target=QueryTarget(
                domain=domain,
                device_class=device_class,
                area=area_snapshot,
            ),
            filter=QueryFilter(state=requested_state),
        )
        query_result = _QUERY_EXECUTOR.execute(query_command, candidates)

        semantic_quantity = (
            SemanticQuantity.exactly(2)
            if re.search(r"\bbeide\b", text, re.I)
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
                    "query_command": query_command,
                    "query_result": query_result,
                },
                source_text=text,
                action=SemanticAction.QUERY,
                quantity=semantic_quantity,
            ),
            resolved_entities=list(query_result.entities),
        )
