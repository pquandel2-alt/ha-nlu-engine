"""Deterministic NLU matching: hassil for sentence structure, ``entities``
for name resolution. No fuzzy scoring anywhere in the pipeline.

A hit requires all three to hold:
  1. hassil ``recognize()`` matches a sentence template for a known intent.
  2. The captured ``{name}`` resolves unambiguously to exactly one entity
     (``entities.resolve_entity`` - exact match, or unambiguous contains-match).
  3. The resolved entity's domain is allowed for the matched intent.

Anything else (no template match, ambiguous/unknown name, wrong domain)
returns ``None`` - the caller (``conversation.py``) turns that into a fixed
"not understood" response. There is no LLM fallback and no confidence score;
this is intentional (see plan: predictability over coverage).

Sentence-matching and entity/area resolution live in ``parsers.py`` (one
``IntentParser`` per grammar - see its module docstring for why six
grammars stay separately compiled). This module only routes text to the
right parser and turns its ``ParseResult`` into a ``ServiceCallPlan`` -
see the v2 plan, Phase 2 ("Intent-System vereinheitlichen"):
``docs/architecture-v2-phase2.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hassil import Intents

from .areas import AreaResolveStatus, resolve_area_name
from .entities import EntitySnapshot, ResolveStatus, resolve_entity
from .nlu.command import SemanticCommand, build_semantic_command
from .nlu.context import ConversationContext
from .nlu.debug import DebugTrace, format_command
from .nlu.frame import SemanticFrame, TargetReference
from .nlu.normalize import normalize
from .nlu.parser import AmbiguousReference, ClarificationRequest, ParseContext, ParseResult
from .nlu.response import NluError, NluResponse
from .nlu.service_mapper import map_to_service_call
from .nlu.validator import validate_command
from .parsers import (
    ClimateExtendedParser,
    ContextFollowupParser,
    FanExtendedParser,
    LightExtendedParser,
    PercentageParser,
    QuantifierParser,
    ReferenceParser,
    SingleTargetParser,
    _DEFAULT_DIMMING_STEP_PERCENT,
)
from .service_call import (
    CLIMATE_EXTENDED_INTENTS,
    FAN_EXTENDED_INTENTS,
    INTENTS,
    LIGHT_EXTENDED_INTENTS,
    PERCENT_INTENTS,
    QUERY_INTENTS,
    ServiceCallPlan,
)

INTENTS_DIR = Path(__file__).parent / "intents" / "de"
QUANTIFIERS_DIR = INTENTS_DIR / "quantifiers"
PERCENTAGE_DIR = INTENTS_DIR / "percentage"
LIGHT_EXTENDED_DIR = INTENTS_DIR / "light_extended"
FAN_EXTENDED_DIR = INTENTS_DIR / "fan_extended"
CLIMATE_EXTENDED_DIR = INTENTS_DIR / "climate_extended"
CONTEXT_FOLLOWUP_DIR = INTENTS_DIR / "context_followup"
REFERENCE_DIR = INTENTS_DIR / "reference"

# Sentences containing "Prozent" are routed to PercentageParser's separately-
# compiled grammar for the same reason as the quantifier routing below: the
# existing {name}-wildcard close-cover sentence ("fahre {name} runter")
# would otherwise structurally swallow "Rolllade im Büro auf 30 Prozent" as
# {name}. Checked after normalize() so a "%" symbol (normalized to the word
# "Prozent" - see nlu/normalize.py) is routed correctly too.
_PERCENT_RE = re.compile(r"\bprozent\b", re.IGNORECASE)

# Bare "auf 50" with no unit word at all (HomeIntent plan V4.2, "Number
# Normalization" - "50" must mean the same as "50 Prozent") also needs
# routing here, since without a "Prozent"/"%" anywhere in the sentence
# _PERCENT_RE above never fires. Checked *after* the climate/fan regexes
# below (never before this point in _select_parser) so "auf 21 Grad"/"auf
# Stufe 3" keep going to their own grammars first - this only catches a
# digit sitting directly after "auf" with nothing else in between, which
# "auf Stufe 3" and "auf 21 Grad" don't (there's always a word between "auf"
# and the digit, or a unit word after it, in those two).
_BARE_PERCENT_RE = re.compile(r"\bauf\s+\d{1,3}\b")

# Sentences containing "alle"/"beide[n/r]"/"nur"/a count word are routed to
# QuantifierParser's separately-compiled grammar rather than mixed into the
# {name}-wildcard grammar above - hassil's recognize() would otherwise
# structurally match both grammars for the same sentence and silently pick
# whichever comes first in file/sentence order. The count-word list (v2 plan
# Phase 29, "Natural Quantifiers") mirrors parsers.py's _COUNT_SLOT_LIST -
# "nur"/count-only sentences like "nur die Wohnzimmerlampen an" or "mach die
# drei Lichter an" contain neither "alle" nor "beide[n/r]", so without this
# they'd never even reach QuantifierParser. Same reasoning applies to
# "oben"/"unten" (HomeIntent plan V4.3, "Implicit Targets" - "Mach oben die
# Lichter aus." has no {quantifier} word at all, only {level}) - added here
# for the same "or this sentence never reaches QuantifierParser" reason.
_QUANTIFIER_RE = re.compile(
    r"\b(alle|beide[nr]?|nur|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|oben|unten)\b", re.IGNORECASE
)

# Sentences containing a brightness-adjust or colour/colour-temperature
# keyword are routed to LightExtendedParser's separately-compiled grammar
# (v2 plan Phase 14). Checked *before* _PERCENT_RE below: "mach das Licht 20
# Prozent heller" contains both "Prozent" and "heller" and must not fall
# into PercentageParser's absolute {name}/{percent} grammar.
_LIGHT_EXTENDED_RE = re.compile(
    r"\b(heller|dunkler|rot|grün|blau|gelb|orange|lila|violett|weiß|pink|rosa|türkis|cyan|warmweiß|kaltweiß)\b",
    re.IGNORECASE,
)

# Sentences containing a fan-speed keyword are routed to FanExtendedParser's
# separately-compiled grammar (v2 plan Phase 16) - same reasoning as the
# other dedicated grammars above: "auf Stufe 3" would otherwise collide with
# nothing existing (no overlap with prozent/quantifier/color keywords), but
# keeping it as its own grammar/parser follows the same one-parser-per-
# vocabulary precedent LightExtendedParser already established.
_FAN_EXTENDED_RE = re.compile(r"\b(stufe|schneller|langsamer)\b", re.IGNORECASE)

# Sentences containing a climate-temperature keyword are routed to
# ClimateExtendedParser's separately-compiled grammar (v2 plan Phase 17) -
# same reasoning as the other dedicated grammars above. "temperatur" is safe
# as a standalone \b-bounded word here: it never matches inside compound
# words like "Außentemperatur" (query.yaml), since there's no boundary
# between "Außen" and "temperatur".
_CLIMATE_EXTENDED_RE = re.compile(r"\b(grad|wärmer|kälter|temperatur)\b", re.IGNORECASE)

# Per-domain question word for the clarification round-trip (v2 plan Phase
# 25). Same kind of small, explicit German-grammar lookup as
# service_call.py's ``_DOMAIN_PLURAL_DE`` - only covers the domains
# SingleTargetParser's basic INTENTS can actually produce ambiguity for.
# Unknown/mixed-domain candidate sets fall back to a grammatically safe,
# gender-neutral phrasing rather than guessing an article.
_DOMAIN_QUESTION_WORD_DE = {
    "light": "Welches Licht",
    "switch": "Welchen Schalter",
    "cover": "Welche Rollläden",
    "fan": "Welchen Ventilator",
    "climate": "Welche Heizung",
}


def _clarification_question(clarification: ClarificationRequest) -> str:
    domains = {candidate.domain for candidate in clarification.candidates}
    if len(domains) == 1:
        question_word = _DOMAIN_QUESTION_WORD_DE.get(next(iter(domains)))
        if question_word is not None:
            return f"{question_word} meinst du?"
    return "Das war nicht eindeutig. Welches meinst du?"


@dataclass(frozen=True)
class MatchResult:
    plan: ServiceCallPlan | None
    response_text: str
    # SemanticFrame representation of the same match, built by the parser
    # in parsers.py and used here to look up the ServiceCall spec (see
    # _build_match_result) - see Phase 1/2 of the v2 plan.
    frame: SemanticFrame | None = None
    # Fully-resolved counterpart to ``frame`` (real EntitySnapshot/AreaSnapshot
    # objects instead of text references) - see Phase 10 of the v2 plan.
    # Purely additive like ``frame`` was in Phase 1/2: plan/response_text
    # keep driving behaviour, no consumer reads this yet (Phase 11 Validator).
    command: SemanticCommand | None = None
    # Set instead of ``plan``/``command`` when the name resolved to more than
    # one tied candidate (v2 plan Phase 25, "Clarification") - ``plan`` is
    # ``None`` here too, but unlike a successful query (also ``plan=None``)
    # this means "ask the user, don't execute anything yet". Callers must
    # check ``clarification`` before falling back to the ``plan is None``
    # query-vs-action distinction ``conversation.py`` already made in Phase
    # 19/Query-Engine (see its module docstring).
    clarification: ClarificationRequest | None = None


class NluEngine:
    """Loads all intent YAML files once at construction; ``match()`` is
    stateless per call (entities are passed in fresh each time since HA
    entity state changes between conversation turns)."""

    def __init__(
        self,
        intents_dir: Path = INTENTS_DIR,
        quantifiers_dir: Path = QUANTIFIERS_DIR,
        percentage_dir: Path = PERCENTAGE_DIR,
        light_extended_dir: Path = LIGHT_EXTENDED_DIR,
        fan_extended_dir: Path = FAN_EXTENDED_DIR,
        climate_extended_dir: Path = CLIMATE_EXTENDED_DIR,
        context_followup_dir: Path = CONTEXT_FOLLOWUP_DIR,
        reference_dir: Path = REFERENCE_DIR,
    ) -> None:
        yaml_files = sorted(intents_dir.glob("*.yaml"))
        if not yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {intents_dir}")
        intents: Intents = Intents.from_files(yaml_files)

        quantifier_yaml_files = sorted(quantifiers_dir.glob("*.yaml"))
        if not quantifier_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {quantifiers_dir}")
        quantifier_intents: Intents = Intents.from_files(quantifier_yaml_files)

        percentage_yaml_files = sorted(percentage_dir.glob("*.yaml"))
        if not percentage_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {percentage_dir}")
        percentage_intents: Intents = Intents.from_files(percentage_yaml_files)

        light_extended_yaml_files = sorted(light_extended_dir.glob("*.yaml"))
        if not light_extended_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {light_extended_dir}")
        light_extended_intents: Intents = Intents.from_files(light_extended_yaml_files)

        fan_extended_yaml_files = sorted(fan_extended_dir.glob("*.yaml"))
        if not fan_extended_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {fan_extended_dir}")
        fan_extended_intents: Intents = Intents.from_files(fan_extended_yaml_files)

        climate_extended_yaml_files = sorted(climate_extended_dir.glob("*.yaml"))
        if not climate_extended_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {climate_extended_dir}")
        climate_extended_intents: Intents = Intents.from_files(climate_extended_yaml_files)

        context_followup_yaml_files = sorted(context_followup_dir.glob("*.yaml"))
        if not context_followup_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {context_followup_dir}")
        context_followup_intents: Intents = Intents.from_files(context_followup_yaml_files)

        reference_yaml_files = sorted(reference_dir.glob("*.yaml"))
        if not reference_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {reference_dir}")
        reference_intents: Intents = Intents.from_files(reference_yaml_files)

        self._single_parser = SingleTargetParser(intents)
        self._quantifier_parser = QuantifierParser(quantifier_intents)
        self._percentage_parser = PercentageParser(percentage_intents)
        self._light_extended_parser = LightExtendedParser(light_extended_intents)
        self._fan_extended_parser = FanExtendedParser(fan_extended_intents)
        self._climate_extended_parser = ClimateExtendedParser(climate_extended_intents)
        self._context_followup_parser = ContextFollowupParser(context_followup_intents)
        self._reference_parser = ReferenceParser(reference_intents)

    def _select_parser(self, text: str):
        if _LIGHT_EXTENDED_RE.search(text):
            return self._light_extended_parser
        if _FAN_EXTENDED_RE.search(text):
            return self._fan_extended_parser
        if _CLIMATE_EXTENDED_RE.search(text):
            return self._climate_extended_parser
        if _PERCENT_RE.search(text) or _BARE_PERCENT_RE.search(text):
            return self._percentage_parser
        if _QUANTIFIER_RE.search(text):
            return self._quantifier_parser
        return self._single_parser

    def match(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        text = normalize(text)
        parser = self._select_parser(text)
        result = parser.parse(text, ParseContext(entities=entities))
        if result is None:
            return None
        if isinstance(result, ClarificationRequest):
            return MatchResult(
                plan=None, response_text=_clarification_question(result), clarification=result,
            )
        return self._build_match_result(result)

    def match_followup(self, text: str, context: ConversationContext | None) -> MatchResult | None:
        """Complete an elliptical follow-up sentence that omits its own
        target (v2 plan Phase 26, "Context") - e.g. "Etwas heller." right
        after "Mach das Wohnzimmerlicht an.". Tried by ``conversation.py``
        *before* a fresh ``match()``, since these sentences have no {name}
        of their own for any other parser to resolve.

        Scope deliberately narrowed to exactly one light in
        ``context.last_entities``: ``LIGHT_EXTENDED_INTENTS``'
        ``HassLightBrighten``/``HassLightDim`` responses only ever read
        ``entities[0].friendly_name`` (see service_call.py), so passing
        through 2+ entities would silently name only one of several lights
        actually changed. 0 or 2+ matching lights therefore both return
        ``None`` here - same "never guess" rule as the rest of the engine,
        not a bug: the plan's own example is single-light anyway. Falls
        through to the normal "not understood" response, same as any other
        non-match.
        """
        if context is None:
            return None

        matched = [entity for entity in context.last_entities if entity.domain == "light"]
        if len(matched) != 1:
            return None

        normalized = normalize(text)
        intent = self._context_followup_parser.parse(normalized)
        if intent is None:
            return None

        entity = matched[0]
        frame = SemanticFrame(
            intent=intent,
            target=TargetReference(text=text, entity_id=entity.entity_id, domain=entity.domain),
            area=None,
            parameters={"step_percent": _DEFAULT_DIMMING_STEP_PERCENT},
            source_text=text,
        )
        return self._build_match_result(ParseResult(frame=frame, resolved_entities=[entity]))

    def match_reference(self, text: str, entities: list[EntitySnapshot], context: ConversationContext | None) -> MatchResult | None:
        """Resolve a pronoun or relative reference ("Mach es aus.", "Mach die
        auch an.", "Die Rollläden dort runter.", "Die andere.") against the
        stored ``ConversationContext`` (v2 plan Phase 27, "Pronomen und
        Referenzen"). Tried by ``conversation.py`` alongside
        ``match_followup()`` - see ``ReferenceParser``'s docstring for why
        the two grammars can't collide with each other or with any other
        grammar (disjoint, fixed sentence sets, verified empirically against
        hassil==3.11.0).

        Both a structural non-match and a recognized-but-unresolvable
        relative reference (``AmbiguousReference`` - "Die andere.", the
        plan's own ``AMBIGUOUS_REFERENCE`` case, "nie raten") collapse to
        ``None`` here, same as the rest of this engine's
        ``match_followup()``/``match()``/``resolve_clarification()``:
        ``conversation.py`` shows the same fixed "not understood" text
        regardless of the specific miss cause.
        """
        if context is None:
            return None

        normalized = normalize(text)
        result = self._reference_parser.parse(normalized, entities, context.last_entities, context.last_area)
        if result is None or isinstance(result, AmbiguousReference):
            return None
        return self._build_match_result(result)

    def resolve_clarification(
        self, reply_text: str, clarification: ClarificationRequest, entities: list[EntitySnapshot]
    ) -> MatchResult | None:
        """Complete a pending clarification (v2 plan Phase 25) with the
        user's follow-up reply - e.g. "Das im Wohnzimmer." after "Welches
        Licht meinst du?". Deterministic, same "never guess" rule as the
        rest of the engine: resolves only if the reply narrows
        ``clarification.candidates`` down to exactly one entity, either by
        name (tried first, against just the candidates - not the full
        ``entities`` list, so a reply like "Küche" can't accidentally match
        some unrelated entity outside the original candidate set) or by area
        (tried second, against the full ``entities`` list since area
        resolution needs to see every entity to judge unambiguity - then
        filtered down to the candidates). Anything else - reply resolves to
        zero or more than one candidate - returns ``None``, same as any
        other non-match; the caller decides how to respond (today: the
        fixed "not understood" text, same as everywhere else in this
        engine).

        Only supports the intents ``SingleTargetParser`` can actually
        produce a ``ClarificationRequest`` for (``INTENTS``: basic
        turn_on/off/toggle/open/close-cover) - the extended parsers
        (percentage, light/fan/climate-extended) don't build
        ``ClarificationRequest`` yet (see parsers.py's ``SingleTargetParser.
        parse()``), so ``clarification.pending_intent`` is always one of
        those five.
        """
        normalized = normalize(reply_text)

        name_resolved = resolve_entity(normalized, list(clarification.candidates))
        entity = name_resolved.entity if name_resolved.status is ResolveStatus.OK else None

        if entity is None:
            area_resolved = resolve_area_name(normalized, entities)
            if area_resolved.status is AreaResolveStatus.OK:
                area_matches = [c for c in clarification.candidates if c.area_id == area_resolved.area_id]
                if len(area_matches) == 1:
                    entity = area_matches[0]

        if entity is None:
            return None

        spec = INTENTS.get(clarification.pending_intent)
        if spec is None:
            return None
        matched = [entity]
        return MatchResult(plan=spec.build(matched), response_text=spec.response(matched))

    def respond(self, text: str, entities: list[EntitySnapshot]) -> NluResponse:
        """Same matching as ``match()``, but never collapses a miss to a bare
        ``None`` - see nlu/response.py's module docstring for why. Not yet
        wired into ``conversation.py``: today's Assist agent shows the same
        fixed "not understood" text regardless of cause, so there is no
        current consumer for the distinction - kept additive, like
        ``SemanticFrame``/``SemanticCommand`` were ahead of Phases 10/11,
        until a later phase (Debug-Modus, Clarification) actually branches
        on ``NluResponse.error``.
        """
        normalized = normalize(text)
        parser = self._select_parser(normalized)
        result = parser.parse(normalized, ParseContext(entities=entities))
        if result is None:
            return NluResponse(success=False, speech=None, command=None, error=NluError.NO_MATCH)
        if isinstance(result, ClarificationRequest):
            return NluResponse(success=False, speech=None, command=None, error=NluError.AMBIGUOUS_ENTITY)

        command = build_semantic_command(result)
        validation_error = validate_command(command)
        if validation_error is not None:
            return NluResponse(
                success=False, speech=None, command=None, error=NluError[validation_error.name]
            )

        match_result = self._build_match_result(result)
        if match_result is None:
            # Structurally unreachable once validate_command() has passed -
            # every remaining lookup in _build_match_result mirrors a check
            # the validator already performed (see its module docstring).
            # Kept as a safe fallback rather than an assert.
            return NluResponse(success=False, speech=None, command=None, error=NluError.NO_MATCH)
        return NluResponse(
            success=True, speech=match_result.response_text, command=match_result.command, error=None
        )

    def debug(self, text: str, entities: list[EntitySnapshot]) -> DebugTrace:
        """Structured trace of every pipeline stage for one utterance (v2
        plan Phase 22, "Debug-Modus"). Purely a read-only view alongside
        ``respond()`` - duplicates the same small, cheap, pure calls
        (``build_semantic_command``/``validate_command``) rather than
        threading trace-collection through ``_build_match_result``, same
        documented tradeoff as ``respond()`` itself (see its docstring).
        Not wired into ``conversation.py`` or a HA service: the plan calls
        this feature optional and explicitly "kein Debugging von normalen
        Nutzern verlangen" - there is no current consumer, same additive
        pattern as ``SemanticFrame``/``SemanticCommand``/``respond()``
        before their consuming phases existed.

        CANDIDATES/RESOLUTION only ever show the parser's *final* resolved
        entity/entities - see nlu/debug.py's module docstring for why a
        failed resolution can't show ranked alternatives without
        restructuring every ``IntentParser``'s return type. Since Phase 25
        ("Clarification") that restructuring exists for exactly one case -
        ``SingleTargetParser``'s AMBIGUOUS outcome, surfaced below as
        ``validation="AMBIGUOUS_ENTITY"`` with the tied candidates - other
        failure causes (NOT_FOUND, no template match) are still collapsed.
        """
        normalized = normalize(text)
        parser = self._select_parser(normalized)
        parser_name = type(parser).__name__
        result = parser.parse(normalized, ParseContext(entities=entities))
        if result is None:
            return DebugTrace(
                input=text,
                normalized=normalized,
                parser=parser_name,
                intent=None,
                target=None,
                area=None,
                candidates=(),
                resolution=None,
                capabilities=(),
                command=None,
                validation="NO_MATCH",
                service=None,
                data=None,
            )
        if isinstance(result, ClarificationRequest):
            return DebugTrace(
                input=text,
                normalized=normalized,
                parser=parser_name,
                intent=result.pending_intent,
                target=result.pending_target,
                area=None,
                candidates=tuple(entity.entity_id for entity in result.candidates),
                resolution=None,
                capabilities=(),
                command=None,
                validation="AMBIGUOUS_ENTITY",
                service=None,
                data=None,
            )

        frame = result.frame
        matched = result.resolved_entities
        command = build_semantic_command(result)
        validation_error = validate_command(command)
        capabilities = tuple(sorted({capability for entity in matched for capability in entity.capabilities}))
        candidates = tuple(entity.entity_id for entity in matched)

        service = None
        data = None
        validation = "OK"
        if validation_error is not None:
            validation = validation_error.name
        else:
            match_result = self._build_match_result(result)
            if match_result is not None and match_result.plan is not None:
                service = f"{match_result.plan.domain}.{match_result.plan.service}"
                data = match_result.plan.data

        return DebugTrace(
            input=text,
            normalized=normalized,
            parser=parser_name,
            intent=frame.intent,
            target=frame.target.text if frame.target is not None else None,
            area=frame.area.text if frame.area is not None else None,
            candidates=candidates,
            resolution=", ".join(candidates) or None,
            capabilities=capabilities,
            command=format_command(command),
            validation=validation,
            service=service,
            data=data,
        )

    @staticmethod
    def _build_match_result(result: ParseResult) -> MatchResult | None:
        frame = result.frame
        matched = result.resolved_entities
        command = build_semantic_command(result)

        # Gate on the Command Validator (v2 plan Phase 11) before building
        # anything. Today's parsers already self-police everything this
        # checks, so this never actually rejects a real match (see the 5
        # "real matches validate clean" regression tests in
        # tests/test_validator.py) - it is wired in now so a future,
        # non-self-policing parser (LLM Adapter) gets a real gatekeeper
        # instead of a silent no-op.
        if validate_command(command) is not None:
            return None

        percent = frame.parameters.get("percent")
        if percent is not None:
            spec = PERCENT_INTENTS.get(matched[0].domain)
            if spec is None:
                return None
            return MatchResult(
                plan=map_to_service_call(command),
                response_text=spec.response(matched, percent),
                frame=frame,
                command=command,
            )

        light_extended_spec = LIGHT_EXTENDED_INTENTS.get(frame.intent)
        if light_extended_spec is not None:
            return MatchResult(
                plan=map_to_service_call(command),
                response_text=light_extended_spec.response(matched, frame.parameters),
                frame=frame,
                command=command,
            )

        fan_extended_spec = FAN_EXTENDED_INTENTS.get(frame.intent)
        if fan_extended_spec is not None:
            return MatchResult(
                plan=map_to_service_call(command),
                response_text=fan_extended_spec.response(matched, frame.parameters),
                frame=frame,
                command=command,
            )

        climate_extended_spec = CLIMATE_EXTENDED_INTENTS.get(frame.intent)
        if climate_extended_spec is not None:
            return MatchResult(
                plan=map_to_service_call(command),
                response_text=climate_extended_spec.response(matched, frame.parameters),
                frame=frame,
                command=command,
            )

        query_spec = QUERY_INTENTS.get(frame.intent)
        if query_spec is not None:
            return MatchResult(plan=None, response_text=query_spec.response(matched), frame=frame, command=command)

        spec = INTENTS.get(frame.intent)
        if spec is None:
            return None
        return MatchResult(
            plan=map_to_service_call(command), response_text=spec.response(matched), frame=frame, command=command
        )
