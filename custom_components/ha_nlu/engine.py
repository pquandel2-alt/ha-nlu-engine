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
``IntentParser`` per grammar - see its module docstring for why three
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
from .nlu.frame import SemanticFrame
from .nlu.normalize import normalize
from .nlu.parser import ParseContext, ParseResult
from .parsers import PercentageParser, QuantifierParser, SingleTargetParser
from .service_call import INTENTS, PERCENT_INTENTS, QUERY_INTENTS, ServiceCallPlan

INTENTS_DIR = Path(__file__).parent / "intents" / "de"
QUANTIFIERS_DIR = INTENTS_DIR / "quantifiers"
PERCENTAGE_DIR = INTENTS_DIR / "percentage"

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


@dataclass(frozen=True)
class MatchResult:
    plan: ServiceCallPlan | None
    response_text: str
    # SemanticFrame representation of the same match, built by the parser
    # in parsers.py and used here to look up the ServiceCall spec (see
    # _build_match_result) - see Phase 1/2 of the v2 plan.
    frame: SemanticFrame | None = None


class NluEngine:
    """Loads all intent YAML files once at construction; ``match()`` is
    stateless per call (entities are passed in fresh each time since HA
    entity state changes between conversation turns)."""

    def __init__(
        self,
        intents_dir: Path = INTENTS_DIR,
        quantifiers_dir: Path = QUANTIFIERS_DIR,
        percentage_dir: Path = PERCENTAGE_DIR,
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

        self._single_parser = SingleTargetParser(intents)
        self._quantifier_parser = QuantifierParser(quantifier_intents)
        self._percentage_parser = PercentageParser(percentage_intents)

    def match(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        text = normalize(text)
        if _PERCENT_RE.search(text):
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

        percent = frame.parameters.get("percent")
        if percent is not None:
            spec = PERCENT_INTENTS.get(matched[0].domain)
            if spec is None:
                return None
            return MatchResult(
                plan=spec.build(matched, percent),
                response_text=spec.response(matched, percent),
                frame=frame,
            )

        query_spec = QUERY_INTENTS.get(frame.intent)
        if query_spec is not None:
            return MatchResult(plan=None, response_text=query_spec.response(matched), frame=frame)

        spec = INTENTS.get(frame.intent)
        if spec is None:
            return None
        return MatchResult(plan=spec.build(matched), response_text=spec.response(matched), frame=frame)
