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
``IntentParser`` per grammar - see its module docstring for why four
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
from .nlu.service_mapper import map_to_service_call
from .nlu.validator import validate_command
from .parsers import LightExtendedParser, PercentageParser, QuantifierParser, SingleTargetParser
from .service_call import INTENTS, LIGHT_EXTENDED_INTENTS, PERCENT_INTENTS, QUERY_INTENTS, ServiceCallPlan

INTENTS_DIR = Path(__file__).parent / "intents" / "de"
QUANTIFIERS_DIR = INTENTS_DIR / "quantifiers"
PERCENTAGE_DIR = INTENTS_DIR / "percentage"
LIGHT_EXTENDED_DIR = INTENTS_DIR / "light_extended"

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

        self._single_parser = SingleTargetParser(intents)
        self._quantifier_parser = QuantifierParser(quantifier_intents)
        self._percentage_parser = PercentageParser(percentage_intents)
        self._light_extended_parser = LightExtendedParser(light_extended_intents)

    def match(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        text = normalize(text)
        if _LIGHT_EXTENDED_RE.search(text):
            parser = self._light_extended_parser
        elif _PERCENT_RE.search(text):
            parser = self._percentage_parser
        elif _QUANTIFIER_RE.search(text):
            parser = self._quantifier_parser
        else:
            parser = self._single_parser

        result = parser.parse(text, ParseContext(entities=entities))
        if result is None:
            return None
        return self._build_match_result(result)

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

        query_spec = QUERY_INTENTS.get(frame.intent)
        if query_spec is not None:
            return MatchResult(plan=None, response_text=query_spec.response(matched), frame=frame, command=command)

        spec = INTENTS.get(frame.intent)
        if spec is None:
            return None
        return MatchResult(
            plan=map_to_service_call(command), response_text=spec.response(matched), frame=frame, command=command
        )
