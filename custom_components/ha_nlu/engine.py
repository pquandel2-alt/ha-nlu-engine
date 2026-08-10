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

from .entities import EntitySnapshot
from .nlu.command import SemanticCommand, build_semantic_command
from .nlu.frame import SemanticFrame
from .nlu.normalize import normalize
from .nlu.parser import ParseContext, ParseResult
from .nlu.response import NluError, NluResponse
from .nlu.service_mapper import map_to_service_call
from .nlu.validator import validate_command
from .parsers import (
    ClimateExtendedParser,
    FanExtendedParser,
    LightExtendedParser,
    PercentageParser,
    QuantifierParser,
    SingleTargetParser,
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

# Sentences containing "Prozent" are routed to PercentageParser's separately-
# compiled grammar for the same reason as the quantifier routing below: the
# existing {name}-wildcard close-cover sentence ("fahre {name} runter")
# would otherwise structurally swallow "Rolllade im Büro auf 30 Prozent" as
# {name}. Checked after normalize() so a "%" symbol (normalized to the word
# "Prozent" - see nlu/normalize.py) is routed correctly too.
_PERCENT_RE = re.compile(r"\bprozent\b", re.IGNORECASE)

# Sentences containing "alle"/"beide[n/r]" are routed to QuantifierParser's
# separately-compiled grammar rather than mixed into the {name}-wildcard
# grammar above - hassil's recognize() would otherwise structurally match
# both grammars for the same sentence and silently pick whichever comes
# first in file/sentence order.
_QUANTIFIER_RE = re.compile(r"\b(alle|beide[nr]?)\b", re.IGNORECASE)

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

        self._single_parser = SingleTargetParser(intents)
        self._quantifier_parser = QuantifierParser(quantifier_intents)
        self._percentage_parser = PercentageParser(percentage_intents)
        self._light_extended_parser = LightExtendedParser(light_extended_intents)
        self._fan_extended_parser = FanExtendedParser(fan_extended_intents)
        self._climate_extended_parser = ClimateExtendedParser(climate_extended_intents)

    def _select_parser(self, text: str):
        if _LIGHT_EXTENDED_RE.search(text):
            return self._light_extended_parser
        if _FAN_EXTENDED_RE.search(text):
            return self._fan_extended_parser
        if _CLIMATE_EXTENDED_RE.search(text):
            return self._climate_extended_parser
        if _PERCENT_RE.search(text):
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
        return self._build_match_result(result)

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
