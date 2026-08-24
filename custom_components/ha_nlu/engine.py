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
from dataclasses import dataclass, replace
from pathlib import Path

from hassil import Intents

from .areas import AreaResolveStatus, resolve_area_name
from .automation_summary import AutomationSummary
from .automation_results import (
    AutomationDraftMatchResult,
    AutomationDeletionMatchResult,
    AutomationMatchResult,
    AutomationToggleMatchResult,
)
from .entities import EntitySnapshot, ResolveStatus, resolve_entity
from .nlu.command import SemanticCommand, build_semantic_command
from .nlu.context import ConversationContext
from .nlu.debug import DebugTrace, format_command
from .nlu.frame import AreaReference, SemanticFrame, TargetReference
from .nlu.normalize import normalize
from .nlu.parser import (
    AmbiguousReference,
    ClarificationRequest,
    ParseContext,
    ParseResult,
    create_parse_context,
)
from .nlu.reasoning import ReasoningEngine, ResolvedSemanticIntent
from .nlu.response import NluError, NluResponse
from .nlu.parse_outcome import ParseFailureReason, UnderstandingFeedback
from .nlu.response_generator import ResponseGenerator, _automation_label
from .nlu.service_mapper import map_to_service_call
from .nlu.semantic_compiler import SemanticCommandCompiler, SemanticQueryCompiler
from .nlu.semantic_lexicon import analyse_semantics
from .nlu.validator import validate_command
from .automation_action_parser import AutomationActionParser
from .automation_condition_parser import AutomationConditionParser, split_on_top_level_and
from .automation_trigger_parser import _AUTOMATION_TRIGGER_RE, AutomationTriggerParser
from .location_property_query import LocationPropertyQueryParser, LocationQueryFeedback
from .contextual_property import ContextualPropertyResolver
from .conversation_correction import ConversationCorrectionResolver
from .relative_time_command_parser import RelativeTimeCommandParser
from .scheduled_time_command_parser import ScheduledTimeCommandParser
from .nlu.automation_model import AutomationModel, TriggerModel, TriggerType, render_automation_tree
from .nlu.automation_model import TriggerTarget
from .nlu.action_model import ActionGroup, ActionModel, ActionType
from .nlu.automation_sentence_split import split_trigger_action
from .nlu.automation_validator import validate_automation
from .nlu.condition_model import ConditionNode
from .parsers import (
    AreaQueryParser,
    AutomationDeleteMatch,
    AutomationDeleteParser,
    AutomationQueryParser,
    AutomationToggleMatch,
    AutomationToggleParser,
    ClimateExtendedParser,
    CommandFollowupParser,
    ComparisonQueryParser,
    ContextFollowupParser,
    FanExtendedParser,
    LightExtendedParser,
    PercentageParser,
    QuantifierParser,
    QueryFollowupParser,
    ReferenceParser,
    SingleTargetParser,
    StateQueryParser,
    TemporalParser,
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
from .world_model import WorldModel

_RESPONSE_GENERATOR = ResponseGenerator()

INTENTS_DIR = Path(__file__).parent / "intents" / "de"
QUANTIFIERS_DIR = INTENTS_DIR / "quantifiers"
PERCENTAGE_DIR = INTENTS_DIR / "percentage"
LIGHT_EXTENDED_DIR = INTENTS_DIR / "light_extended"
FAN_EXTENDED_DIR = INTENTS_DIR / "fan_extended"
CLIMATE_EXTENDED_DIR = INTENTS_DIR / "climate_extended"
CONTEXT_FOLLOWUP_DIR = INTENTS_DIR / "context_followup"
REFERENCE_DIR = INTENTS_DIR / "reference"
COMPARISON_QUERY_DIR = INTENTS_DIR / "comparison_query"
TEMPORAL_DIR = INTENTS_DIR / "temporal"
AREA_QUERY_DIR = INTENTS_DIR / "area_query"
QUERY_FOLLOWUP_DIR = INTENTS_DIR / "query_followup"
STATE_QUERY_DIR = INTENTS_DIR / "state_query"
COMMAND_FOLLOWUP_DIR = INTENTS_DIR / "command_followup"
AUTOMATION_TRIGGER_DIR = INTENTS_DIR / "automation_trigger"
AUTOMATION_CONDITION_DIR = INTENTS_DIR / "automation_condition"
AUTOMATION_ACTION_DIR = INTENTS_DIR / "automation_action"
AUTOMATION_QUERY_DIR = INTENTS_DIR / "automation_query"
AUTOMATION_DELETE_DIR = INTENTS_DIR / "automation_delete"
AUTOMATION_TOGGLE_DIR = INTENTS_DIR / "automation_toggle"
RELATIVE_TIME_DIR = INTENTS_DIR / "relative_time"

# Sentences containing a temporal-modifier keyword ("Minute(n)"/"Stunde(n)"/
# "Uhr"/"morgen früh"/"heute Abend"/...) are routed to TemporalParser's
# separately-compiled grammar (HomeIntent plan V4.7, "Temporal Expressions")
# - checked *first*, before _QUANTIFIER_RE below: "mach das Licht in fünf
# Minuten aus"/"... um acht Uhr an" contain "fünf"/"acht", which
# _QUANTIFIER_RE also matches (its spelled-out count-word list), and would
# otherwise misroute these to QuantifierParser's unrelated grammar - same
# "one keyword, one dedicated grammar, checked before anything it could
# collide with" reasoning _COMPARISON_QUERY_RE's own comment documents.
_TEMPORAL_RE = re.compile(
    r"\b(minuten?|stunden?|uhr)\b|\b(morgen früh|heute abend|morgen abend|heute früh)\b", re.IGNORECASE
)

# Sentences containing "welche" *and* an actual comparator word are routed
# to ComparisonQueryParser's separately-compiled grammar (HomeIntent plan
# V4.6, "Comparisons", query-filter half) - checked *first*, before every
# other regex below: a sentence like "welche Heizungen sind unter 20 Grad"
# also contains "Grad" (would otherwise match _CLIMATE_EXTENDED_RE) and
# "welche Lichter sind mindestens 50 Prozent" also contains "Prozent" (would
# otherwise match _PERCENT_RE) - both would be structurally swallowed by the
# wrong grammar if checked after those, same "one keyword, one dedicated
# grammar, checked before anything it could collide with" reasoning
# _LIGHT_EXTENDED_RE's own comment documents for its position ahead of
# _PERCENT_RE.
#
# Requiring a comparator word (not just "welche" alone) is V4.2's fix for a
# real misroute: a bare "welche" sentence with no comparator (e.g. "Welche
# Fenster sind noch geöffnet?") was being swallowed here too and then
# structurally could never match ComparisonQueryParser's comparator+percent/
# temperature-only grammar, so it fell all the way through to "not
# understood" - it belongs to _STATE_QUERY_RE below instead. The comparator
# vocabulary mirrors parsers.py's _COMPARATOR_SLOT_LIST (kept in sync by
# hand - not re-derived here, since that list is built at import time from
# tuples, not a bare word list this regex could read directly). "heller
# als"/"dunkler als"/"mehr als"/"weniger als" (V4.2 spec gap #5) require the
# literal "als" alongside "heller"/"dunkler", so this can't collide with
# _LIGHT_EXTENDED_RE's bare "heller"/"dunkler" keywords below - and this
# regex is checked first regardless, same precedent already documented.
_COMPARISON_QUERY_RE = re.compile(
    r"(?=.*\bwelch\w*\b)(?=.*\b(mindestens|höchstens|nicht höher als|über|unter|"
    r"heller als|dunkler als|mehr als|weniger als)\b)",
    re.IGNORECASE,
)

# Sentences combining a query-trigger word ("welche"/"wie viele"/"ist"/
# "sind") *and* a state word (predicate form: offen/geöffnet/zu/geschlossen/
# an/aus/eingeschaltet/ausgeschaltet - or attributive/adjective form:
# offene/geöffnete/geschlossene/eingeschaltete/angeschaltete/ausgeschaltete,
# since German inflects the same word differently in "die Fenster sind
# offen" vs. "gibt es offene Fenster") are routed to StateQueryParser's
# separately-compiled grammar (HomeIntent V4.2, "Semantic Query & State
# Resolution") - checked immediately after _COMPARISON_QUERY_RE, since a
# "welche"-sentence without a comparator word (e.g. "Welche Fenster sind
# noch geöffnet?") falls through the now-narrowed regex above and needs
# somewhere else to land. Requiring *both* words (not just the state word
# alone) keeps this from swallowing plain on/off commands ("Schalte das
# Licht aus" has "aus" but none of the trigger words). Verified empirically
# (this session) against every existing intent YAML: no sentence combines a
# trigger word with a state word today, so this can't misroute an existing
# match.
#
# "gibt es" is handled as its own unconditional alternative (no state word
# required): HassExistsQuery's grammar explicitly supports a bare existence
# question with no state word at all ("gibt es Fenster im Keller?"), so
# requiring a state word here would make that sentence structurally
# unreachable by any parser. Safe to route "gibt es" unconditionally -
# grepped empirically (this session): no other intent YAML uses the phrase
# "gibt es" anywhere, so this can't misroute an existing match.
_STATE_QUERY_RE = re.compile(
    r"\bgibt es\b"
    r"|\bhaben wir\b.*\b(offen\w*|geöffnet\w*|geschlossen\w*|eingeschaltet\w*|ausgeschaltet\w*)\b"
    r"|\bwelchen\b.*\b(zustand|status)\b"
    r"|\b(wie|zeige)\b.*\b(zustand|status)\b"
    r"|\b(wo|in welchen räumen|welche räume haben|was ist)\b.*"
    r"\b(offen|geöffnet|zu|geschlossen|an|aus|eingeschaltet|ausgeschaltet|"
    r"hochgefahren|runtergefahren|heruntergefahren|oben|unten)\b"
    r"|\bwas ist der\b.*\b(zustand|status)\b"
    r"|\bwelche\b.*\bsind\b"
    r"|\b(welcher|welche|welches|wie viele|ist|sind)\b.*"
    r"\b(offen|geöffnet|offene|geöffnete|zu|geschlossen|geschlossene|"
    r"an|aus|eingeschaltet|angeschaltet|ausgeschaltet|"
    r"hochgefahren|runtergefahren|heruntergefahren|oben|unten|"
    r"eingeschaltete|angeschaltete|ausgeschaltete)\b",
    re.IGNORECASE,
)

# Intents NluEngine.match_query_followup() will continue with a fresh
# area/floor ("Und in der Küche?", "Und oben?") - HassGetState (original,
# v4.9) plus the three StateQueryParser intents (HomeIntent v4.2.1 plan,
# Phase 8). Deliberately excludes HassQueryComparison - see that method's
# docstring.
_QUERY_FOLLOWUP_INTENTS = frozenset(
    {"HassGetState", "HassLocationPropertyQuery", "HassStateQuery", "HassCheckState", "HassEntityStateQuery", "HassExistsQuery", "HassDeviceQuery"}
)

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

# Fixed natural-language cover position: "halb (runter/hoch)" and "zur
# Hälfte" mean an absolute 50 percent position. Routed to PercentageParser
# so single and quantified room/floor targets share the same safe resolver.
_HALF_POSITION_RE = re.compile(r"\b(halb|hälfte)\b", re.IGNORECASE)

# Wave 13 ("Relative-Zeit-Automationen") - the same cheap, collision-free
# pre-check scaffold ``_AUTOMATION_TRIGGER_RE`` establishes for
# ``match_automation()``, gating ``match_relative_time_automation()`` so an
# ordinary command/query sentence never pays for a third hassil pass. Matches
# "in <word> Minuten/Sekunden/Stunden" anywhere in the sentence - <word> is
# deliberately a bare ``\S+`` (not ``\d+``) so spelled-out amounts ("in fünf
# Minuten") aren't missed; the full grammar (relative_time_command.yaml)
# still does the real, exhaustive matching, this only decides whether it's
# worth trying.
_RELATIVE_TIME_RE = re.compile(r"\bin\s+\S+\s+(sekunden?|minuten?|stunden?)\b", re.IGNORECASE)
_CALENDAR_TIME_RE = re.compile(
    r"\b(heute|morgen|übermorgen)\b|\b(?:am\s+)?(?:nächsten?|kommenden?)\s+werktag\b|"
    r"\b(?:am|nächsten?|kommenden?)\s+"
    r"(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag)\b|"
    r"\bam\s+\d{1,2}\.(?=\s)",
    re.IGNORECASE,
)

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
# An area-scoped phrase with a plural article/domain ("die Rollläden im
# Esszimmer", "die Lichter in der Küche") is likewise an unambiguous group
# request even without the redundant word "alle".  The article is part of
# this gate deliberately: "den Rollladen im Büro" remains a singular target.
_QUANTIFIER_RE = re.compile(
    r"\b(alle|beide[nr]?|nur|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|oben|unten)\b"
    r"|\bdie\s+(?:lichter|lampen|steckdosen|rol{2,3}[aä]den|rollos|ventilatoren)\b"
    r"(?=.*\b(?:in der|in dem|im|am|beim)\b)"
    r"|(?=.*\b(?:in der|in dem|im|am|beim)\b.*\bdie\s+"
    r"(?:lichter|lampen|steckdosen|rol{2,3}[aä]den|rollos|ventilatoren)\b)",
    re.IGNORECASE,
)

# "Welche {attribute} zeigt {name} [Sensor]?" / "Was zeigt {name} [Sensor]
# an?" (v4.1.2 live gap, screenshot IMG_3105) is plain HassGetState -
# SingleTargetParser's default grammar (query.yaml) - but "welche Temperatur
# zeigt der Außentemperatur Sensor" also contains the standalone word
# "temperatur", which would otherwise match _CLIMATE_EXTENDED_RE below and
# misroute it to ClimateExtendedParser's unrelated "wärmer/kälter" grammar
# (that parser has no "zeigt" sentence, so it would return None). "zeigt" is
# unique to this HassGetState sentence family - grepped empirically, no
# other intent YAML uses it - so routing on it unconditionally, before
# _CLIMATE_EXTENDED_RE, can't misroute an existing match.
_GET_STATE_ZEIGT_RE = re.compile(r"\bzeigt\b", re.IGNORECASE)

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

# "und"-joined sentences ("Mach das Licht an und fahr die Rollläden hoch.")
# are split into independent sub-commands (HomeIntent plan V4.8, "Multi-Step
# Commands") *before* any other routing below - each segment is re-fed
# through the exact same single-command ``match()`` pipeline (own parser
# selection, own entity resolution, own validation), so a multi-step
# sentence gets zero bespoke grammar of its own. No existing intent YAML
# uses the word "und" (grepped empirically before adding this), so this
# split can never misfire on an existing single-command sentence.
_AND_SPLIT_RE = re.compile(r"\s+und\s+", re.IGNORECASE)

# "ist es" (a state query with no {name} at all, only a room - "wie warm
# ist es im Wohnzimmer") routes to AreaQueryParser's separately-compiled
# grammar (HomeIntent plan V4.9, "Cross-Sentence References", first-turn
# half) instead of falling through to SingleTargetParser's default below -
# query.yaml's own name-based sentence never contains the literal "ist es"
# (it's "ist [die|der|das] {name}"), grepped empirically before adding this,
# same "one keyword, one dedicated grammar" precedent every regex above
# already follows.
_AREA_QUERY_RE = re.compile(
    r"\bist\s+es\b|\bwie\s+hoch\s+ist\s+die\s+temperatur\b|"
    r"\bwelche\s+temperatur\s+hat\b",
    re.IGNORECASE,
)

# "automation(en)"/"was schaltet"/"was steuert"/"warum ist"/"warum geht"
# routes to AutomationQueryParser's separately-compiled grammar (HomeIntent
# plan V5.29, "Automation Query") - checked as its own cheap pre-check
# (mirroring ``_AUTOMATION_TRIGGER_RE``'s own role one wave earlier) since
# this is what gates the real, blocking ``automations.yaml``/metadata-
# sidecar read in ``conversation.py`` before ``match_automation_query()``
# is even called - an ordinary command/query turn must never pay that I/O
# cost. "warum ist"/"warum geht" are deliberately narrow (not a bare
# "warum") - grepped empirically against every existing live grammar, no
# collision found.
_AUTOMATION_QUERY_RE = re.compile(
    r"\bautomation(en)?\b|\bwas schaltet\b|\bwas steuert\b|\bwarum ist\b|\bwarum geht\b", re.IGNORECASE
)

# "lösch(e)"/"entfern(e)" + "automation" routes to AutomationDeleteParser's
# separately-compiled grammar (HomeIntent plan V5.28, "Automation Deletion")
# - same cheap-pre-check role as ``_AUTOMATION_QUERY_RE`` one wave earlier,
# gating the real, blocking ``automations.yaml``/metadata-sidecar read in
# ``conversation.py`` before ``match_automation_delete()`` is even called.
# Grepped empirically against every existing intent YAML (see this module's
# git history) - no other grammar uses "lösch"/"entfern" for anything else.
_AUTOMATION_DELETE_RE = re.compile(r"\blösch\w*\b|\bentfern\w*\b", re.IGNORECASE)

# "deaktivier(e)"/"aktivier(e)" + "automation" route to AutomationToggleParser's
# separately-compiled grammar (HomeIntent plan V5.28 rest, Wave 11
# "Automation Disable/Enable") - same cheap-pre-check role as
# ``_AUTOMATION_DELETE_RE`` above. Two separate regexes (not one with an
# optional "de" prefix) because each gates a different one of
# ``match_automation_disable()``/``match_automation_enable()`` - the German
# word boundary (``\b``) already keeps "deaktiviere" from matching
# ``_AUTOMATION_ENABLE_RE`` (see AutomationToggleParser's own docstring).
# Grepped empirically against every existing intent YAML - no other grammar
# uses "aktivier"/"deaktivier" for anything else.
_AUTOMATION_DISABLE_RE = re.compile(r"\bdeaktivier\w*\b", re.IGNORECASE)
_AUTOMATION_ENABLE_RE = re.compile(r"\baktivier\w*\b", re.IGNORECASE)

# "einmalig(e)"/"nur einmal" marks a fire-once automation (new feature, Wave
# 12 "Einmalige Automation") - matched and *stripped* from the normalized
# text inside ``match_automation()`` itself (not a separate pre-check gate
# like the regexes above, since this qualifier can appear anywhere in an
# otherwise ordinary trigger+action sentence, not just at the very start).
# Verified collision-free: "einmal"/"einmalig" has zero existing usages
# anywhere in intents/lexicon/parsers/engine, and ``normalize()``'s filler-
# word stripping (``\b(ein bisschen|mal|doch|kurz|etwas)\b``) has no word
# boundary at "mal" inside "einmal"/"einmalig", so it never fires on this
# qualifier by accident.
_AUTOMATION_ONCE_RE = re.compile(r"\beinmalig\w*\b|\bnur einmal\b", re.IGNORECASE)
_AUTOMATION_REPEAT_RE = re.compile(
    r"\bnur\s+(?P<separate>zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|[2-9]|10)\s*mal\b"
    r"|\b(?P<joined>zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)mal\b",
    re.IGNORECASE,
)
_REPEAT_COUNTS = {
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
}

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
    "sensor": "Welchen Sensor",
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
    # ReasoningEngine's composed view of the same match (V6.25/V6.26) -
    # additive/observational only, same "no consumer yet" pattern as
    # ``command`` above: computed centrally in ``_build_match_result`` so
    # ``ReasoningEngine`` is actually wired into the live pipeline instead
    # of unreferenced code, but nothing here drives ``plan``/``response_text``.
    # For a current-turn floor reference ("oben"/"unten") this can diverge
    # from ``command`` - ``SemanticFrame`` has no floor field, so
    # ``ReasoningEngine.resolve()`` can only pick up a floor from
    # ``ConversationContext.last_floor`` (a remembered turn), never from the
    # sentence just parsed. Known, documented, not a behaviour regression
    # since nothing reads this field yet.
    resolved_intent: ResolvedSemanticIntent | None = None


@dataclass(frozen=True)
class CommandPlan:
    """An "und"-joined multi-step sentence ("Mach das Licht an und fahr die
    Rollläden hoch."), split and matched as N independent sub-commands
    (HomeIntent plan V4.8, "Multi-Step Commands").

    ``commands`` holds one fully-built ``MatchResult`` per segment, each
    already individually validated through the normal single-command
    pipeline ("Jeder Command einzeln validieren"). ``NluEngine.match()``
    only ever returns a ``CommandPlan`` once *every* segment has
    successfully matched, resolved, and validated - the plan's own
    "Standardmäßig für sicherheitskritische Aktionen: validate entire plan
    first -> execute only if complete plan is valid" default, applied by
    never constructing a partial ``CommandPlan``: one failing/ambiguous/
    non-actionable segment fails the whole sentence (``match()`` returns
    ``None``), same "never guess, no partial execution" precedent the rest
    of this engine already follows.

    Read-only query segments may be mixed with actions. Every segment is
    still resolved and validated before execution starts, and action/query
    segments that refer to the same entity are refused because the query
    would otherwise describe the pre-execution snapshot.
    """

    commands: tuple[MatchResult, ...]


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
        comparison_query_dir: Path = COMPARISON_QUERY_DIR,
        temporal_dir: Path = TEMPORAL_DIR,
        area_query_dir: Path = AREA_QUERY_DIR,
        query_followup_dir: Path = QUERY_FOLLOWUP_DIR,
        state_query_dir: Path = STATE_QUERY_DIR,
        command_followup_dir: Path = COMMAND_FOLLOWUP_DIR,
        automation_trigger_dir: Path = AUTOMATION_TRIGGER_DIR,
        automation_condition_dir: Path = AUTOMATION_CONDITION_DIR,
        automation_action_dir: Path = AUTOMATION_ACTION_DIR,
        automation_query_dir: Path = AUTOMATION_QUERY_DIR,
        automation_delete_dir: Path = AUTOMATION_DELETE_DIR,
        automation_toggle_dir: Path = AUTOMATION_TOGGLE_DIR,
        relative_time_dir: Path = RELATIVE_TIME_DIR,
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

        comparison_query_yaml_files = sorted(comparison_query_dir.glob("*.yaml"))
        if not comparison_query_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {comparison_query_dir}")
        comparison_query_intents: Intents = Intents.from_files(comparison_query_yaml_files)

        temporal_yaml_files = sorted(temporal_dir.glob("*.yaml"))
        if not temporal_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {temporal_dir}")
        temporal_intents: Intents = Intents.from_files(temporal_yaml_files)

        area_query_yaml_files = sorted(area_query_dir.glob("*.yaml"))
        if not area_query_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {area_query_dir}")
        area_query_intents: Intents = Intents.from_files(area_query_yaml_files)

        query_followup_yaml_files = sorted(query_followup_dir.glob("*.yaml"))
        if not query_followup_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {query_followup_dir}")
        query_followup_intents: Intents = Intents.from_files(query_followup_yaml_files)

        state_query_yaml_files = sorted(state_query_dir.glob("*.yaml"))
        if not state_query_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {state_query_dir}")
        state_query_intents: Intents = Intents.from_files(state_query_yaml_files)

        command_followup_yaml_files = sorted(command_followup_dir.glob("*.yaml"))
        if not command_followup_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {command_followup_dir}")
        command_followup_intents: Intents = Intents.from_files(command_followup_yaml_files)

        automation_trigger_yaml_files = sorted(automation_trigger_dir.glob("*.yaml"))
        if not automation_trigger_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {automation_trigger_dir}")
        automation_trigger_intents: Intents = Intents.from_files(automation_trigger_yaml_files)

        automation_condition_yaml_files = sorted(automation_condition_dir.glob("*.yaml"))
        if not automation_condition_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {automation_condition_dir}")
        automation_condition_intents: Intents = Intents.from_files(automation_condition_yaml_files)

        automation_action_yaml_files = sorted(automation_action_dir.glob("*.yaml"))
        if not automation_action_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {automation_action_dir}")
        automation_action_intents: Intents = Intents.from_files(automation_action_yaml_files)

        automation_query_yaml_files = sorted(automation_query_dir.glob("*.yaml"))
        if not automation_query_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {automation_query_dir}")
        automation_query_intents: Intents = Intents.from_files(automation_query_yaml_files)

        automation_delete_yaml_files = sorted(automation_delete_dir.glob("*.yaml"))
        if not automation_delete_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {automation_delete_dir}")
        automation_delete_intents: Intents = Intents.from_files(automation_delete_yaml_files)

        automation_toggle_yaml_files = sorted(automation_toggle_dir.glob("*.yaml"))
        if not automation_toggle_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {automation_toggle_dir}")
        automation_toggle_intents: Intents = Intents.from_files(automation_toggle_yaml_files)

        relative_time_yaml_files = sorted(relative_time_dir.glob("*.yaml"))
        if not relative_time_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {relative_time_dir}")
        relative_time_intents: Intents = Intents.from_files(relative_time_yaml_files)

        self._single_parser = SingleTargetParser(intents)
        self._quantifier_parser = QuantifierParser(quantifier_intents)
        self._percentage_parser = PercentageParser(percentage_intents)
        self._light_extended_parser = LightExtendedParser(light_extended_intents)
        self._fan_extended_parser = FanExtendedParser(fan_extended_intents)
        self._climate_extended_parser = ClimateExtendedParser(climate_extended_intents)
        self._context_followup_parser = ContextFollowupParser(context_followup_intents)
        self._reference_parser = ReferenceParser(reference_intents)
        self._comparison_query_parser = ComparisonQueryParser(comparison_query_intents)
        self._temporal_parser = TemporalParser(temporal_intents)
        self._area_query_parser = AreaQueryParser(area_query_intents)
        self._query_followup_parser = QueryFollowupParser(query_followup_intents)
        self._state_query_parser = StateQueryParser(state_query_intents)
        self._command_followup_parser = CommandFollowupParser(command_followup_intents)

        # Automation-Grammatiken/Parser (Integration Wave Migrationsschritt 1):
        # nur geladen und instanziiert, noch nicht an _select_parser()/match()
        # angeschlossen - reines Laden ohne Routing, Regressionsrisiko ≈ 0.
        self._automation_trigger_parser = AutomationTriggerParser(automation_trigger_intents)
        self._automation_condition_parser = AutomationConditionParser(automation_condition_intents)
        self._automation_action_parser = AutomationActionParser(
            automation_action_intents, self._automation_condition_parser
        )
        self._automation_query_parser = AutomationQueryParser(automation_query_intents)
        self._automation_delete_parser = AutomationDeleteParser(automation_delete_intents)
        self._automation_toggle_parser = AutomationToggleParser(automation_toggle_intents)
        self._relative_time_command_parser = RelativeTimeCommandParser(
            relative_time_intents, self._automation_action_parser
        )
        self._scheduled_time_command_parser = ScheduledTimeCommandParser(
            self._automation_action_parser
        )
        self._location_property_query_parser = LocationPropertyQueryParser()
        self._contextual_property_resolver = ContextualPropertyResolver(
            self._climate_extended_parser,
            self._percentage_parser,
            self._fan_extended_parser,
        )
        self._conversation_correction_resolver = ConversationCorrectionResolver()

    def match_correction_followup(
        self,
        text: str,
        entities: list[EntitySnapshot],
        context: ConversationContext | None,
    ) -> MatchResult | None:
        """Apply an explicit correction to the previous actionable turn."""
        outcome = self._conversation_correction_resolver.resolve(text, entities, context)
        if outcome is None:
            return None
        if isinstance(outcome, UnderstandingFeedback):
            return MatchResult(plan=None, response_text=outcome.speech)
        if isinstance(outcome, ClarificationRequest):
            return MatchResult(
                plan=None,
                response_text=_clarification_question(outcome),
                clarification=outcome,
            )
        return self._build_match_result(outcome, entities, context)

    def _select_parser(self, text: str):
        if _TEMPORAL_RE.search(text):
            return self._temporal_parser
        if _COMPARISON_QUERY_RE.search(text):
            return self._comparison_query_parser
        if _STATE_QUERY_RE.search(text):
            return self._state_query_parser
        if _GET_STATE_ZEIGT_RE.search(text):
            return self._single_parser
        if _LIGHT_EXTENDED_RE.search(text):
            return self._light_extended_parser
        if _FAN_EXTENDED_RE.search(text):
            return self._fan_extended_parser
        # The location-temperature vocabulary is narrower than the general
        # climate keyword gate (which also contains "Temperatur"). Route
        # these questions first so they cannot be mistaken for a setpoint
        # command.
        if _AREA_QUERY_RE.search(text):
            return self._area_query_parser
        if _CLIMATE_EXTENDED_RE.search(text):
            return self._climate_extended_parser
        if _PERCENT_RE.search(text) or _BARE_PERCENT_RE.search(text) or _HALF_POSITION_RE.search(text):
            return self._percentage_parser
        if _QUANTIFIER_RE.search(text):
            return self._quantifier_parser
        return self._single_parser

    def match(
        self, text: str, entities: list[EntitySnapshot], world_model: WorldModel | None = None
    ) -> MatchResult | CommandPlan | None:
        segments = [segment for segment in _AND_SPLIT_RE.split(text) if segment.strip()]
        if len(segments) > 1:
            return self._match_multi(segments, entities, world_model)

        text = normalize(text)
        semantic_analysis = analyse_semantics(text)
        location_query = self._location_property_query_parser.parse(
            text, entities, semantic_analysis
        )
        if isinstance(location_query, LocationQueryFeedback):
            return None
        if location_query is not None:
            return self._build_match_result(location_query, entities)
        parse_context = create_parse_context(entities, world_model=world_model)
        # Location/property phrases are the explicit cross-router fallback
        # above. Once a grammar is selected here, a semantic rejection must
        # not fall through to a broader wildcard parser (for example,
        # "beide" must never degrade into a singular command).
        result = self._select_parser(text).parse(text, parse_context)
        if isinstance(result, ClarificationRequest):
            # Legacy wildcard grammars may include politeness words in the
            # target or detect duplicate names before applying an explicitly
            # spoken area.  Let the constraint-based semantic compiler prove
            # a unique interpretation before asking an unnecessary question.
            semantic_result = SemanticCommandCompiler.compile(
                text, entities, world_model, semantic_analysis
            )
            if isinstance(semantic_result, ParseResult):
                result = semantic_result
        if result is None:
            result = SemanticQueryCompiler.compile(
                text, entities, world_model, semantic_analysis
            )
            if result is None:
                result = SemanticCommandCompiler.compile(
                    text, entities, world_model, semantic_analysis
                )
        if result is None:
            return None
        if isinstance(result, ClarificationRequest):
            return MatchResult(
                plan=None, response_text=_clarification_question(result), clarification=result,
            )
        return self._build_match_result(result, entities)

    def failure_feedback(self, text: str, entities: list[EntitySnapshot] | None = None) -> str | None:
        """Best-effort explanation after every deterministic parser failed."""
        feedback = self.understanding_feedback(text, entities)
        return feedback.speech if feedback is not None else None

    def understanding_feedback(
        self, text: str, entities: list[EntitySnapshot] | None = None
    ) -> UnderstandingFeedback | None:
        """Return the structured counterpart of the spoken failure text."""
        if re.search(
            r"\b(?:heute|morgen|übermorgen|am\s+\S+)\s+"
            r"(?:gegen|irgendwann)\s+(?:früh|morgens|abends?|nachts)\b",
            text,
            re.IGNORECASE,
        ):
            return UnderstandingFeedback(
                ParseFailureReason.INVALID_VALUE,
                "Bitte nenne für diesen Auftrag eine genaue Uhrzeit.",
            )
        if entities is not None:
            location = self._location_property_query_parser.parse(normalize(text), entities)
            if isinstance(location, LocationQueryFeedback):
                return UnderstandingFeedback(location.reason, location.response_text)
            normalized = normalize(text)
            if (
                _PERCENT_RE.search(normalized)
                or _BARE_PERCENT_RE.search(normalized)
                or _HALF_POSITION_RE.search(normalized)
            ):
                percentage_feedback = self._percentage_parser.failure_feedback(
                    normalized,
                    create_parse_context(entities),
                )
                if percentage_feedback is not None:
                    return percentage_feedback
        if _AUTOMATION_TRIGGER_RE.search(text):
            return UnderstandingFeedback(
                ParseFailureReason.INCOMPLETE_REQUEST,
                "Ich konnte Trigger und Aktion der Automation nicht eindeutig erkennen.",
            )
        if re.search(
            r"\b(schalte|mach|fahre|öffne|schließe|stelle|setze|starte|aktiviere|drehe)\b",
            text,
            re.IGNORECASE,
        ):
            return UnderstandingFeedback(
                ParseFailureReason.UNKNOWN_ENTITY,
                "Ich konnte das angesprochene Gerät nicht eindeutig finden oder den Befehl nicht ausführen.",
            )
        return None
        if re.search(r"\b(wie|welche|welcher|welches|was|ist|sind)\b", text, re.IGNORECASE):
            return "Ich habe die Frage erkannt, aber die gewünschte Eigenschaft oder das Ziel nicht gefunden."
        return None

    def _match_multi(
        self, segments: list[str], entities: list[EntitySnapshot], world_model: WorldModel | None = None
    ) -> CommandPlan | None:
        """Match every "und"-joined segment independently, through the exact
        same ``match()`` entry point (recursive - a segment never contains
        "und" itself once split, so this always bottoms out in the
        single-command branch above). See ``CommandPlan``'s docstring for
        the "validate everything first, execute nothing on any failure"
        contract this enforces by only ever returning a fully-populated
        ``CommandPlan`` or ``None``, never something in between.
        """
        results: list[MatchResult] = []
        for segment in segments:
            result = self.match(segment, entities, world_model)
            if (
                not isinstance(result, MatchResult)
                or result.clarification is not None
                or result.command is None
            ):
                return None
            results.append(result)
        action_ids = {
            entity.entity_id
            for result in results if result.plan is not None
            for entity in result.command.entities
        }
        query_ids = {
            entity.entity_id
            for result in results if result.plan is None
            for entity in result.command.entities
        }
        if action_ids & query_ids:
            return None
        return CommandPlan(commands=tuple(results))

    def match_followup(self, text: str, context: ConversationContext | None) -> MatchResult | None:
        """Complete an elliptical follow-up sentence that omits its own
        target (v2 plan Phase 26, "Context"; cross-property extension
        HomeIntent plan V6.23, "Natural Context") - e.g. "Etwas heller."
        right after "Mach das Wohnzimmerlicht an.", or "Wärmer." right after
        a climate command. Tried by ``conversation.py`` *before* a fresh
        ``match()``, since these sentences have no {name} of their own for
        any other parser to resolve.

        The target domain (light vs climate) is derived from which spec
        dict the parsed intent name falls into - ``LIGHT_EXTENDED_INTENTS``'
        ``HassLightBrighten``/``HassLightDim`` for brightness,
        ``CLIMATE_EXTENDED_INTENTS``' ``HassClimateIncreaseTemperature``/
        ``HassClimateDecreaseTemperature`` for "wärmer"/"kälter" (V6.23:
        reuses that already-established vocabulary and those already-wired
        intents rather than inventing a color-temperature equivalent for
        which no grammar/lexicon vocabulary exists yet - "niemals raten").

        Scope deliberately narrowed to exactly one matching entity in
        ``context.last_entities``: both spec dicts' response lambdas only
        ever read ``entities[0].friendly_name`` (see service_call.py), so
        passing through 2+ entities would silently name only one of several
        entities actually changed. 0 or 2+ matches therefore both return
        ``None`` here - same "never guess" rule as the rest of the engine,
        not a bug: the plan's own example is single-entity anyway. Falls
        through to the normal "not understood" response, same as any other
        non-match.
        """
        if context is None:
            return None

        normalized = normalize(text)
        intent = self._context_followup_parser.parse(normalized)
        if intent is None:
            return None

        if intent in LIGHT_EXTENDED_INTENTS:
            domain = "light"
            parameters = {"step_percent": _DEFAULT_DIMMING_STEP_PERCENT}
        elif intent in CLIMATE_EXTENDED_INTENTS:
            domain = "climate"
            parameters = {}
        else:
            return None

        matched = [entity for entity in context.last_entities if entity.domain == domain]
        if len(matched) != 1:
            return None

        entity = matched[0]
        frame = SemanticFrame(
            intent=intent,
            target=TargetReference(text=text, entity_id=entity.entity_id, domain=entity.domain),
            area=None,
            parameters=parameters,
            source_text=text,
        )
        return self._build_match_result(
            ParseResult(frame=frame, resolved_entities=[entity]), list(context.last_entities), context
        )
    def match_contextual_property_followup(
        self,
        text: str,
        entities: list[EntitySnapshot],
        context: ConversationContext | None,
    ) -> MatchResult | None:
        """Infer omitted targets for existing, validated setpoint commands.

        The mapping is intentionally limited to real controllable properties:
        temperature→climate, brightness→light, position→cover and
        speed/level→fan. Battery, humidity, power and energy stay read-only.
        """
        outcome = self._contextual_property_resolver.resolve(text, entities, context)
        if outcome is None:
            return None
        if isinstance(outcome, UnderstandingFeedback):
            return MatchResult(plan=None, response_text=outcome.speech)
        if isinstance(outcome, ClarificationRequest):
            return MatchResult(
                plan=None,
                response_text=_clarification_question(outcome),
                clarification=outcome,
            )
        return self._build_match_result(outcome, entities, context)
    def match_reference(self, text: str, entities: list[EntitySnapshot], context: ConversationContext | None) -> MatchResult | None:
        """Resolve a pronoun or relative reference ("Mach es aus.", "Mach die
        auch an.", "Die Rollläden dort runter.", "Die andere.") against the
        stored ``ConversationContext`` (v2 plan Phase 27, "Pronomen und
        Referenzen"). Tried by ``conversation.py`` alongside
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
        return self._build_match_result(result, entities, context)

    def match_query_followup(
        self,
        text: str,
        entities: list[EntitySnapshot],
        context: ConversationContext | None,
        world_model: WorldModel | None = None,
    ) -> MatchResult | None:
        """Continue a previous state query with a new room/floor ("Und in
        der Küche?", "Und oben?" after "Wie warm ist es im Wohnzimmer?") -
        HomeIntent plan V4.9, "Cross-Sentence References". Tried by
        ``conversation.py`` alongside ``match_followup()``/
        ``match_reference()``, before the normal ``match()``: a leading
        "Und ..." is never touched by ``match()``'s own multi-step
        ``_AND_SPLIT_RE`` (that pattern requires whitespace on *both* sides
        of "und", so it never fires on a sentence that only *starts* with
        the word - see its own comment), and no existing grammar has a
        sentence shape for a bare "und {area}"/"und {level}" anyway, so
        without this method such a follow-up would just fail to match
        anything and fall through to "not understood".

        Continues a plain ``HassGetState`` query, or (HomeIntent v4.2.1
        plan, Phase 8) one of the three ``StateQueryParser`` intents -
        ``HassStateQuery``/``HassCheckState``/``HassExistsQuery`` - gated
        here (not in ``QueryFollowupParser`` itself) for the same reason
        ``match_followup()`` does its own light-only filtering before
        calling into ``ContextFollowupParser``: keeps the parser itself
        free of ``ConversationContext``/``SemanticCommand`` knowledge, it
        only sees the plain ``QueryCommand`` this method extracts from
        ``context.last_command.parameters["query_command"]`` (populated by
        ``StateQueryParser`` since Phase 7). ``HassQueryComparison``
        (``QUERY_INTENTS``' other entry, its own multi-entity "welche..."
        shape) is out of scope - same narrow-scoping precedent
        ``TemporalParser``/``ComparisonQueryParser`` already set for
        themselves. A missing/non-query previous turn, or a structural/
        resolution miss in the parser itself, both collapse to ``None``
        here, same as every other "never guess" miss in this engine.
        """
        if (
            context is None
            or context.last_command is None
            or context.last_command.intent not in _QUERY_FOLLOWUP_INTENTS
        ):
            return None

        normalized = normalize(text)
        correction = re.match(
            r"^(?:nein[, ]+)?(?:ich\s+meinte|gemeint\s+war)\s+(?P<location>.+?)[?.!]*$",
            normalized,
            re.IGNORECASE,
        )
        if correction is not None:
            normalized = f"Und im {correction.group('location').strip()}?"
        else:
            natural = re.match(
                r"^wie\s+sieht\s+es\s+(?P<location>oben|unten|(?:im|in der|in dem)\s+.+?)\s+aus[?.!]*$",
                normalized,
                re.IGNORECASE,
            )
            if natural is not None:
                normalized = f"Und {natural.group('location')}?"
        previous_query_command = context.last_command.parameters.get("query_command")
        if (
            context.last_command.parameters.get("property")
            and context.last_command.parameters.get("location_kind") in {"area", "floor"}
            and (
                context.last_command.intent == "HassLocationPropertyQuery"
                or context.focus is not None
            )
        ):
            location_match = re.match(
                r"^und\s+(?:(?:im|in der|in dem)\s+)?(?P<location>.+?)[?.!]*$",
                normalized,
                re.IGNORECASE,
            )
            property_name = context.last_command.parameters.get("property")
            if location_match is not None and property_name:
                query = self._location_property_query_parser.parse(
                    f"{property_name} im {location_match.group('location').strip()}", entities
                )
                if isinstance(query, LocationQueryFeedback):
                    return None
                if query is not None:
                    return self._build_match_result(query, entities, context)
        result = self._query_followup_parser.parse(
            normalized, entities, context.last_entities, previous_query_command, world_model
        )
        if result is None:
            return None
        return self._build_match_result(result, entities, context)

    def match_command_followup(
        self, text: str, entities: list[EntitySnapshot], context: ConversationContext | None
    ) -> MatchResult | None:
        """Continue a previous *command* (not query) with a generic
        follow-up ("Und jetzt wieder aus." after "Schalte das Studio ein.",
        "Und im Schlafzimmer auch." after "Mach das Licht im Wohnzimmer
        an.") - live conversation-context bug fix 2026-08-18. Tried by
        ``conversation.py`` alongside ``match_followup()``/
        ``match_reference()``/``match_query_followup()``, before the normal
        ``match()`` - same "a leading 'und ...' never matches ``match()``'s
        own grammars anyway" reasoning ``match_query_followup()`` already
        documents for itself.

        Gated on ``context.last_command.intent`` being one of the 5 basic
        command intents (``INTENTS``) - the only ones ``CommandFollowupParser``
        can meaningfully continue (either by inverting via
        ``service_call.ACTION_OPPOSITES``, or by keeping the same intent for
        a new area). Query-only previous turns (``QUERY_INTENTS``) are left
        to ``match_query_followup()`` instead - strict command/query context
        separation, never mixed.
        """
        if context is None or context.last_command is None or context.last_command.intent not in INTENTS:
            return None

        normalized = normalize(text)
        result = self._command_followup_parser.parse(normalized, entities, context.last_command)
        if result is None:
            return None
        return self._build_match_result(result, entities, context)

    def match_automation_query(
        self,
        text: str,
        entities: list[EntitySnapshot],
        context: ConversationContext | None,
        automations: tuple[AutomationSummary, ...],
    ) -> MatchResult | None:
        """Match "Welche Automationen gibt es?"/"Was schaltet/steuert X?"/
        "Warum ist/geht X ...?" (HomeIntent plan V5.29, "Automation Query")
        into a ``QueryResult`` built from ``automations`` - a read-only
        survey of ``automations.yaml`` plus its metadata sidecar
        (``AutomationExecutor.async_list_automations()``), same
        ``AutomationSummary``-tuple shape ``AutomationQueryParser``/
        ``QueryExecutor._execute_automation()`` already consume.

        Gated by ``_AUTOMATION_QUERY_RE`` first, same cheap-pre-check role
        ``_AUTOMATION_TRIGGER_RE`` already plays for ``match_automation()``
        - but here the gate matters even more: it is what lets
        ``conversation.py`` decide whether to await the real, blocking
        ``automations.yaml``/metadata-sidecar read at all *before* calling
        this method, so ``automations`` is only ever non-empty-by-actual-
        content on a turn that plausibly needs it. An ordinary command/query
        turn never pays that I/O cost.

        Called from ``conversation.py`` alongside ``match_automation()`` -
        both are independent entry points ``_select_parser()`` never routes
        to internally, same "new grammar, new top-level method" precedent
        every other separately-compiled grammar in this module already
        follows.
        """
        if not _AUTOMATION_QUERY_RE.search(text):
            return None

        normalized = normalize(text)
        parse_context = create_parse_context(entities)
        result = self._automation_query_parser.parse(normalized, parse_context, automations)
        if result is None:
            return None
        return self._build_match_result(result, entities, context)

    def match_automation_delete(
        self,
        text: str,
        entities: list[EntitySnapshot],
        automations: tuple[AutomationSummary, ...],
    ) -> AutomationDeletionMatchResult | None:
        """Match "Lösche/Entferne die Automation für X" (HomeIntent plan
        V5.28, "Automation Deletion") into an ``AutomationDeletionMatchResult``
        - never a direct deletion on this turn, only ever a spoken
        confirmation prompt or refusal (see that type's own docstring for
        why). ``conversation.py`` stores a successful resolution as a
        ``PendingAutomationDeletion`` and only calls
        ``AutomationExecutor.async_delete_automation()`` once the user
        confirms with "ja" - same two-step gate ``match_automation()``'s own
        creation path already established, and for the identical reason
        (V5.36's "no half-created/half-deleted automations" applies to
        deletion just as much as creation).

        Gated by ``_AUTOMATION_DELETE_RE`` first, the same role
        ``_AUTOMATION_QUERY_RE`` plays for ``match_automation_query()`` -
        letting ``conversation.py`` skip the real, blocking
        ``automations.yaml``/metadata-sidecar read on a turn that plausibly
        can't need it.

        Returns ``None`` only when the sentence doesn't match this grammar
        at all, or when the named entity itself doesn't resolve (unknown or
        ambiguous {name} - never guessed, same as ``AutomationQueryParser``).
        A resolved entity with zero or 2+ referencing automations still
        returns a result (a spoken refusal), not ``None`` - the sentence was
        understood, it just can't be acted on.
        """
        if not _AUTOMATION_DELETE_RE.search(text):
            return None

        normalized = normalize(text)
        parse_context = create_parse_context(entities)
        match: AutomationDeleteMatch | None = self._automation_delete_parser.parse(
            normalized, parse_context, automations
        )
        if match is None:
            return None

        if not match.matched:
            return AutomationDeletionMatchResult(
                automation=None,
                response_text=f"Ich habe keine Automation gefunden, die {match.entity.friendly_name} steuert.",
            )
        if len(match.matched) > 1:
            return AutomationDeletionMatchResult(
                automation=None,
                response_text=(
                    f"Es gibt mehrere Automationen, die {match.entity.friendly_name} steuern. "
                    "Das kann ich nicht eindeutig löschen."
                ),
            )

        automation = match.matched[0]
        return AutomationDeletionMatchResult(
            automation=automation,
            response_text=f'Soll die Automation "{_automation_label(automation)}" gelöscht werden?',
        )

    def match_automation_disable(
        self,
        text: str,
        entities: list[EntitySnapshot],
        automations: tuple[AutomationSummary, ...],
    ) -> AutomationToggleMatchResult | None:
        """Match "Deaktiviere die Automation für X" (HomeIntent plan V5.28
        rest, Wave 11 "Automation Disable/Enable") into an
        ``AutomationToggleMatchResult`` with ``enable=False`` - unlike
        ``match_automation_delete()``, a resolved single match here is acted
        on immediately by ``conversation.py`` on this same turn (see that
        result type's own docstring for why no confirmation gate is needed).

        Gated by ``_AUTOMATION_DISABLE_RE`` first, same role
        ``_AUTOMATION_DELETE_RE`` plays for ``match_automation_delete()``.
        """
        return self._match_automation_toggle(text, entities, automations, gate=_AUTOMATION_DISABLE_RE)

    def match_automation_enable(
        self,
        text: str,
        entities: list[EntitySnapshot],
        automations: tuple[AutomationSummary, ...],
    ) -> AutomationToggleMatchResult | None:
        """The ``match_automation_disable()`` counterpart - ``enable=True``,
        gated by ``_AUTOMATION_ENABLE_RE`` instead."""
        return self._match_automation_toggle(text, entities, automations, gate=_AUTOMATION_ENABLE_RE)

    def _match_automation_toggle(
        self,
        text: str,
        entities: list[EntitySnapshot],
        automations: tuple[AutomationSummary, ...],
        gate: re.Pattern[str],
    ) -> AutomationToggleMatchResult | None:
        if not gate.search(text):
            return None

        normalized = normalize(text)
        parse_context = create_parse_context(entities)
        match: AutomationToggleMatch | None = self._automation_toggle_parser.parse(
            normalized, parse_context, automations
        )
        if match is None:
            return None

        verb = "aktivieren" if match.enable else "deaktivieren"
        if not match.matched:
            return AutomationToggleMatchResult(
                automation=None,
                enable=match.enable,
                response_text=f"Ich habe keine Automation gefunden, die {match.entity.friendly_name} steuert.",
            )
        if len(match.matched) > 1:
            return AutomationToggleMatchResult(
                automation=None,
                enable=match.enable,
                response_text=(
                    f"Es gibt mehrere Automationen, die {match.entity.friendly_name} steuern. "
                    f"Das kann ich nicht eindeutig {verb}."
                ),
            )

        automation = match.matched[0]
        return AutomationToggleMatchResult(
            automation=automation,
            enable=match.enable,
            response_text=(
                f"Automation wurde {'aktiviert' if match.enable else 'deaktiviert'}."
            ),
        )

    def _parse_action_semantically(
        self, text: str, context: ParseContext
    ) -> tuple[ActionModel | ActionGroup, ...] | None:
        """Prefer the shared direct-command semantics for automation actions.

        This keeps percentage, natural-position and flexible-word-order
        understanding identical for immediate, delayed and state-triggered
        commands. Automation-only actions remain available through the
        established dedicated parser as the fallback.
        """
        direct = self.match(text, context.entities, context.world_model)
        action = self._action_from_direct_match(direct, context.entities)
        if action is not None:
            return (action,)
        return self._automation_action_parser.parse(text, context)

    def match_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Match a combined spoken automation sentence ("Wenn das
        Küchenfenster geöffnet wird, schalte das Küchenlicht ein.") into an
        ``AutomationModel`` (Integration Wave Migration Step 3). Called live
        from ``conversation.py`` since Migration Step 4, after
        ``match_command_followup()`` and before the plain ``match()``
        fallback (see ``NluConversationEntity._async_handle_message()``).

        Scope boundary (Integration Plan Section 9, stated plainly): this
        method only ever produces and validates an ``AutomationModel`` - it
        never builds HA Automation YAML and never calls
        ``hass.services.async_call()``. Existing HA write access is
        completely unchanged by this method's existence.

        Gated by ``_AUTOMATION_TRIGGER_RE`` first - the same cheap,
        collision-free (verified empirically against all 14 existing live
        grammars) regex scaffold ``automation_trigger_parser.py`` already
        defined - so an ordinary command/query sentence never pays the cost
        of ``split_trigger_action()``/two extra parser passes below it.
        Deliberately checked on the raw (not yet ``normalize()``-d) text,
        same as every other pre-check regex in this module runs on already-
        normalized text for ``_select_parser()`` - here there is no shared
        normalization step yet to hook into (this is a new, independent
        entry point, not a branch inside ``_select_parser()`` itself; see
        the Integration Plan's Section 4/Variante D).

        Trigger+action is still the primary shape ``split_trigger_action()``
        splits for - a sentence with no comma at all still returns ``None``
        here, same "never guess" rule as the rest of this engine. Since the
        Conditions Wave (2026-08-19), the trigger-clause additionally allows
        an embedded "und"-joined condition ("Wenn X und Y, tu Z."): if the
        whole trigger-clause doesn't parse as a single Trigger on its own,
        ``_split_trigger_condition()`` searches every top-level "und" split
        point for exactly one point where the left half parses as a Trigger
        and the right half as a Condition - grammar-driven (try-parse, not
        keyword-based), and refusing (``None``) on zero or more than one
        such point, same ambiguity discipline every entity resolution in
        this engine already follows. No second ambiguity gate is introduced
        anywhere else - this fallback only ever runs inside this method, for
        this trigger-clause.
        """
        if not _AUTOMATION_TRIGGER_RE.search(text):
            return None

        normalized = normalize(text)
        repeat_match = _AUTOMATION_REPEAT_RE.search(normalized)
        max_runs = None
        if repeat_match is not None:
            raw_count = (repeat_match.group("separate") or repeat_match.group("joined")).casefold()
            max_runs = int(raw_count) if raw_count.isdigit() else _REPEAT_COUNTS[raw_count]
            normalized = _AUTOMATION_REPEAT_RE.sub(" ", normalized)
            normalized = re.sub(r"\s+", " ", normalized).strip()
        once = bool(_AUTOMATION_ONCE_RE.search(normalized))
        if once:
            # Strip the qualifier itself before trigger/action splitting -
            # it is not part of either clause's own grammar (mirrors
            # ``normalize()``'s own filler-word-then-whitespace-squeeze
            # pattern, see nlu/normalize.py).
            normalized = _AUTOMATION_ONCE_RE.sub(" ", normalized)
            normalized = re.sub(r"\s+", " ", normalized).strip()

        last_entities = context.last_entities if context is not None else ()
        last_area = context.last_area if context is not None else None
        parse_context = create_parse_context(
            entities,
            world_model=world_model,
            last_entities=tuple(last_entities),
            last_area=last_area,
        )

        split = split_trigger_action(normalized)
        if split is None:
            candidates: list[tuple[str, str]] = []
            for marker in re.finditer(
                r"\b(schalte|mach|fahre|öffne|schließe|stelle|setze|starte|aktiviere|führe|drehe)\b",
                normalized,
                re.IGNORECASE,
            ):
                trigger_candidate = normalized[: marker.start()].strip(" ,")
                action_candidate = normalized[marker.start() :].strip()
                if (
                    trigger_candidate
                    and self._automation_trigger_parser.parse(trigger_candidate, parse_context) is not None
                    and self._parse_action_semantically(action_candidate, parse_context)
                ):
                    candidates.append((trigger_candidate, action_candidate))
            for marker in re.finditer(r"\s+(wenn|sobald|falls)\s+", normalized, re.IGNORECASE):
                action_candidate = normalized[: marker.start()].strip(" ,")
                trigger_candidate = normalized[marker.start() :].strip(" ,")
                if (
                    action_candidate
                    and self._automation_trigger_parser.parse(trigger_candidate, parse_context) is not None
                    and self._parse_action_semantically(action_candidate, parse_context)
                ):
                    candidates.append((trigger_candidate, action_candidate))
            if len(candidates) != 1:
                return None
            split = candidates[0]
        trigger_text, action_text = split

        condition_node: ConditionNode | None = None
        trigger = self._automation_trigger_parser.parse(trigger_text, parse_context)
        if trigger is None:
            split_result = self._split_trigger_condition(trigger_text, parse_context)
            if split_result is None:
                return None
            trigger, condition_node = split_result

        actions = self._parse_action_semantically(action_text, parse_context)
        if not actions:
            return None

        conditions = (condition_node,) if condition_node is not None else ()
        model = AutomationModel(
            triggers=(trigger,), conditions=conditions, actions=actions, source_text=text,
            once=once, max_runs=max_runs,
        )
        validation_error = validate_automation(model)
        response_text = render_automation_tree(model)
        if validation_error is not None:
            response_text = f"{response_text}\nvalidation_error: {validation_error.name}"
        return AutomationMatchResult(model=model, response_text=response_text, validation_error=validation_error)

    def match_automation_draft_start(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationDraftMatchResult | None:
        """Recognize a complete trigger whose action was left for a reply."""
        if not _AUTOMATION_TRIGGER_RE.search(text):
            return None
        parse_context = create_parse_context(
            entities,
            world_model=world_model,
            last_entities=context.last_entities if context is not None else (),
            last_area=context.last_area if context is not None else None,
        )
        normalized = normalize(text).strip(" ,")
        trigger = self._automation_trigger_parser.parse(normalized, parse_context)
        if trigger is None:
            return None
        return AutomationDraftMatchResult(trigger=trigger, source_text=text)

    def complete_automation_draft(
        self,
        text: str,
        trigger: TriggerModel,
        source_text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Add a spoken action to a stored trigger and validate the model."""
        parse_context = create_parse_context(
            entities,
            world_model=world_model,
            last_entities=context.last_entities if context is not None else (),
            last_area=context.last_area if context is not None else None,
        )
        actions = self._parse_action_semantically(normalize(text), parse_context)
        if not actions:
            return None
        model = AutomationModel(
            triggers=(trigger,),
            actions=actions,
            source_text=f"{source_text}, {text}",
        )
        validation_error = validate_automation(model)
        response_text = render_automation_tree(model)
        if validation_error is not None:
            response_text = f"{response_text}\nvalidation_error: {validation_error.name}"
        return AutomationMatchResult(model, response_text, validation_error)

    def revise_pending_automation(
        self,
        text: str,
        model: AutomationModel,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
    ) -> AutomationMatchResult | None:
        """Apply a bounded spoken edit to an unconfirmed automation preview."""
        normalized = normalize(text)
        updated: AutomationModel | None = None

        time_match = re.fullmatch(
            r"(?:ändere|änder|verschiebe|setz(?:e)?)\s+(?:die\s+)?(?:uhrzeit|zeit)?\s*"
            r"(?:auf\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{1,2}))?\s*uhr[?.!]*",
            normalized,
            re.IGNORECASE,
        )
        if time_match is not None:
            hour = int(time_match.group("hour"))
            minute = int(time_match.group("minute") or 0)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            if model.calendar_schedule is not None:
                updated = replace(
                    model,
                    calendar_schedule=replace(
                        model.calendar_schedule, hour=hour, minute=minute
                    ),
                )
            elif len(model.triggers) == 1 and model.triggers[0].type is TriggerType.TIME:
                updated = replace(
                    model,
                    triggers=(
                        replace(
                            model.triggers[0],
                            time_hour=hour,
                            time_minute=minute,
                            time_second=0,
                        ),
                    ),
                )
            else:
                return None

        repeat_match = re.fullmatch(
            r"(?:führe\s+(?:sie|die\s+automation)\s+)?(?:doch\s+)?nur\s+"
            r"(?P<count>\d+|einmal|zweimal|dreimal|viermal|fünfmal)"
            r"(?:\s+(?:aus|ausführen))?[?.!]*",
            normalized,
            re.IGNORECASE,
        )
        if repeat_match is not None:
            raw = repeat_match.group("count").casefold()
            counts = {"einmal": 1, "zweimal": 2, "dreimal": 3, "viermal": 4, "fünfmal": 5}
            count = int(raw) if raw.isdigit() else counts[raw]
            if count <= 0:
                return None
            updated = replace(
                model,
                once=count == 1,
                max_runs=None if count == 1 else count,
            )

        if re.fullmatch(
            r"(?:entferne|lösch(?:e)?)\s+(?:die\s+)?bedingung[?.!]*",
            normalized,
            re.IGNORECASE,
        ):
            if not model.conditions:
                return None
            updated = replace(model, conditions=())

        parse_context = create_parse_context(entities, world_model=world_model)
        action_match = re.fullmatch(
            r"füge\s+(?:als\s+)?(?:weitere\s+|zweite\s+)?aktion\s+(.+?)\s+hinzu[?.!]*",
            normalized,
            re.IGNORECASE,
        )
        if action_match is not None:
            actions = self._parse_action_semantically(
                action_match.group(1), parse_context
            )
            if not actions:
                return None
            updated = replace(model, actions=(*model.actions, *actions))

        condition_match = re.fullmatch(
            r"füge\s+(?:die\s+)?bedingung\s+(.+?)\s+hinzu[?.!]*",
            normalized,
            re.IGNORECASE,
        )
        if condition_match is not None:
            condition = self._automation_condition_parser.parse(
                condition_match.group(1), parse_context
            )
            if condition is None:
                return None
            updated = replace(model, conditions=(*model.conditions, condition))

        if updated is None:
            return None
        validation_error = validate_automation(updated)
        return AutomationMatchResult(
            updated,
            render_automation_tree(updated),
            validation_error,
        )

    def match_relative_time_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Match a single-clause spoken command carrying a relative-time
        offset ("Fahre in 5 Minuten die Wohnzimmer Rolllade auf 30 Prozent")
        into an ``AutomationModel`` with one semantic
        ``TriggerType.RELATIVE_TIME`` trigger. The confirmation handler
        anchors it to an absolute, date-guarded ``TIME`` trigger. Called live from
        ``conversation.py`` after ``match_automation()`` and before the plain
        ``match()`` fallback: this sentence shape has no comma, so
        ``split_trigger_action()`` can never split it into trigger+action
        clauses (see ``relative_time_command.yaml``'s own comment) - a
        structurally new, single-clause entry point, not a branch inside
        ``match_automation()``.

        Always ``once=True``: a relative "in N Minuten" offset is inherently
        a one-shot request - there is no spoken way to ask for a *recurring*
        "in 5 Minuten" automation - so this reuses Wave 12's self-delete
        mechanism unconditionally (Regel 6, see
        ``ha_automation_generator.py``'s ``once``-handling) rather than
        detecting/stripping an "einmalig" qualifier like ``match_automation()``
        does.

        Gated by ``_RELATIVE_TIME_RE`` first, same cheap pre-check reasoning
        ``_AUTOMATION_TRIGGER_RE`` documents for ``match_automation()``.
        """
        if not _RELATIVE_TIME_RE.search(text):
            return None

        normalized = normalize(text)

        last_entities = context.last_entities if context is not None else ()
        last_area = context.last_area if context is not None else None
        parse_context = create_parse_context(
            entities,
            world_model=world_model,
            last_entities=tuple(last_entities),
            last_area=last_area,
        )

        parsed = None
        decomposed = self._relative_time_command_parser.decompose(normalized)
        if decomposed is not None:
            command_text, offset_seconds = decomposed
            direct = self.match(command_text, entities, world_model)
            action = self._action_from_direct_match(direct, entities)
            if action is not None:
                parsed = ((action,), offset_seconds)
        if parsed is None:
            parsed = self._relative_time_command_parser.parse(normalized, parse_context)
        if parsed is None:
            return None
        actions, offset_seconds = parsed

        trigger = TriggerModel(
            type=TriggerType.RELATIVE_TIME,
            relative_offset_seconds=offset_seconds,
        )

        model = AutomationModel(triggers=(trigger,), actions=actions, source_text=text, once=True)
        validation_error = validate_automation(model)
        response_text = render_automation_tree(model)
        if validation_error is not None:
            response_text = f"{response_text}\nvalidation_error: {validation_error.name}"
        return AutomationMatchResult(model=model, response_text=response_text, validation_error=validation_error)

    @staticmethod
    def _action_from_direct_match(
        result: MatchResult | CommandPlan | None,
        available_entities: list[EntitySnapshot],
    ) -> ActionModel | None:
        """Translate one validated direct command into an automation action.

        This is the semantic bridge used only after a relative-time phrase
        has been removed. It reuses the direct-command understanding instead
        of maintaining a second list of delayed-action sentences.
        """
        if not isinstance(result, MatchResult) or result.plan is None or result.command is None:
            return None
        entities = result.command.entities
        if not entities or len({entity.domain for entity in entities}) != 1:
            return None

        domain = entities[0].domain
        frame = result.command.source_frame
        if len(entities) == 1:
            entity = entities[0]
            equivalent = [
                candidate
                for candidate in available_entities
                if candidate.domain == entity.domain
                and candidate.device_class == entity.device_class
                and candidate.area_id == entity.area_id
            ]
            if entity.area_id is not None and len(equivalent) == 1:
                target = TriggerTarget(
                    domain=domain,
                    device_class=entity.device_class,
                    area_id=entity.area_id,
                )
            else:
                target = TriggerTarget(domain=domain, entity_id=entity.entity_id)
        elif result.command.area is not None and frame.quantifier is not None:
            target = TriggerTarget(
                domain=domain,
                area_id=result.command.area.area_id,
                quantifier=frame.quantifier.kind,
                quantifier_count=frame.quantifier.value,
            )
        elif frame.quantifier is not None:
            floor_ids = {entity.floor_id for entity in entities}
            if len(floor_ids) != 1 or None in floor_ids:
                # TriggerTarget must retain a real scope; never turn an
                # arbitrary concrete list into an all-house automation.
                return None
            target = TriggerTarget(
                domain=domain,
                floor_id=next(iter(floor_ids)),
                quantifier=frame.quantifier.kind,
                quantifier_count=frame.quantifier.value,
            )
        else:
            # TriggerTarget cannot represent an arbitrary concrete list.
            # Refuse instead of broadening it to every entity in the house.
            return None

        plan = result.plan
        if plan.domain == "cover" and plan.service == "open_cover":
            return ActionModel(type=ActionType.TURN_ON, target=target)
        if plan.domain == "cover" and plan.service == "close_cover":
            return ActionModel(type=ActionType.TURN_OFF, target=target)
        if plan.domain == "cover" and plan.service == "set_cover_position":
            position = plan.data.get("position")
            return (
                ActionModel(type=ActionType.SET_POSITION, target=target, value=float(position))
                if isinstance(position, (int, float))
                else None
            )
        if plan.domain == "light" and plan.service == "turn_on":
            brightness = plan.data.get("brightness_pct")
            if isinstance(brightness, (int, float)):
                return ActionModel(
                    type=ActionType.SET_BRIGHTNESS,
                    target=target,
                    value=float(brightness),
                )
        if plan.domain == "climate" and plan.service == "set_temperature":
            temperature = plan.data.get("temperature")
            if isinstance(temperature, (int, float)):
                return ActionModel(
                    type=ActionType.SET_TEMPERATURE,
                    target=target,
                    value=float(temperature),
                )
        if plan.service == "turn_on":
            return ActionModel(type=ActionType.TURN_ON, target=target)
        if plan.service == "turn_off":
            return ActionModel(type=ActionType.TURN_OFF, target=target)
        return None

    def match_calendar_time_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Match a date-bound command such as "morgen um 8 Uhr ..."."""
        if not _CALENDAR_TIME_RE.search(text):
            return None
        normalized = normalize(text)
        parse_context = create_parse_context(
            entities,
            world_model=world_model,
            last_entities=tuple(context.last_entities) if context is not None else (),
            last_area=context.last_area if context is not None else None,
        )
        parsed = self._scheduled_time_command_parser.parse(normalized, parse_context)
        if parsed is None:
            return None
        actions, schedule = parsed
        model = AutomationModel(
            triggers=(TriggerModel(type=TriggerType.CALENDAR_TIME),),
            actions=actions,
            source_text=text,
            once=True,
            calendar_schedule=schedule,
        )
        validation_error = validate_automation(model)
        response_text = render_automation_tree(model)
        if validation_error is not None:
            response_text = f"{response_text}\nvalidation_error: {validation_error.name}"
        return AutomationMatchResult(
            model=model,
            response_text=response_text,
            validation_error=validation_error,
        )

    def _split_trigger_condition(
        self, trigger_text: str, parse_context: ParseContext
    ) -> tuple[TriggerModel, ConditionNode] | None:
        """Fallback for ``match_automation()`` when ``trigger_text`` alone
        doesn't parse as a single Trigger: search every top-level "und"
        split point (``split_on_top_level_and()``, already time-window-safe)
        for exactly one point where the left half parses as a Trigger
        (``AutomationTriggerParser``) and the right half as a Condition
        (``AutomationConditionParser``) - both already-constructed instances
        this engine uses everywhere else, no parallel parser or resolver.
        Zero or more than one successful split both refuse (``None``) -
        "niemals raten" applied to sentence structure, the same way every
        other ambiguity in this engine already refuses rather than guesses.
        """
        matches: list[tuple[TriggerModel, ConditionNode]] = []
        for left, right in split_on_top_level_and(trigger_text):
            candidate_trigger = self._automation_trigger_parser.parse(left, parse_context)
            if candidate_trigger is None:
                continue
            candidate_condition = self._automation_condition_parser.parse(right, parse_context)
            if candidate_condition is None:
                continue
            matches.append((candidate_trigger, candidate_condition))
        if len(matches) != 1:
            return None
        return matches[0]

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

        Besides the basic ``INTENTS`` this also restores already-parsed
        parameters for query and contextual setpoint clarifications. That is
        required when "22 Grad" was understood before several thermostats
        were found: selecting one thermostat must retain the 22-degree value.
        """
        normalized = normalize(reply_text)
        normalized = re.sub(
            r"^(?:nein[, ]+)?(?:ich\s+meinte|gemeint\s+war)\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()

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

        matched = [entity]
        spec = INTENTS.get(clarification.pending_intent)
        if spec is not None:
            return MatchResult(plan=spec.build(matched), response_text=spec.response(matched))
        if (
            clarification.pending_intent in QUERY_INTENTS
            or clarification.pending_intent in CLIMATE_EXTENDED_INTENTS
            or clarification.pending_intent in FAN_EXTENDED_INTENTS
            or clarification.pending_intent in LIGHT_EXTENDED_INTENTS
            or clarification.pending_intent == "HassSetPercentage"
        ):
            area = (
                AreaReference(text=entity.area_name, area_id=entity.area_id)
                if entity.area_id is not None and entity.area_name is not None
                else None
            )
            return self._build_match_result(
                ParseResult(
                    frame=SemanticFrame(
                        intent=clarification.pending_intent,
                        target=TargetReference(
                            text=entity.friendly_name,
                            entity_id=entity.entity_id,
                            domain=entity.domain,
                        ),
                        area=area,
                        parameters=dict(clarification.pending_parameters),
                        source_text=reply_text,
                    ),
                    resolved_entities=matched,
                ),
                entities,
            )
        return None

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
        result = parser.parse(normalized, create_parse_context(entities))
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

        match_result = self._build_match_result(result, entities)
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
        result = parser.parse(normalized, create_parse_context(entities))
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
                result_kind="no_match",
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
                result_kind="ambiguous",
            )

        frame = result.frame
        matched = result.resolved_entities
        command = build_semantic_command(result)
        validation_error = validate_command(command)
        capabilities = tuple(sorted({capability for entity in matched for capability in entity.capabilities}))
        candidates = tuple(entity.entity_id for entity in matched)

        service = None
        data = None
        response_text = None
        validation = "OK"
        if validation_error is not None:
            validation = validation_error.name
        else:
            match_result = self._build_match_result(result, entities)
            if match_result is not None:
                response_text = match_result.response_text
                if match_result.plan is not None:
                    service = f"{match_result.plan.domain}.{match_result.plan.service}"
                    data = match_result.plan.data

        result_kind = "matched" if candidates else "empty"

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
            result_kind=result_kind,
            response_text=response_text,
        )

    @staticmethod
    def _build_match_result(
        result: ParseResult,
        entities: list[EntitySnapshot],
        context: ConversationContext | None = None,
    ) -> MatchResult | None:
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

        # ReasoningEngine (V6.25/26) composed centrally, once, for every
        # match that reaches here - additive/observational only (see
        # MatchResult.resolved_intent's own docstring for the known
        # current-turn-floor limitation). Not used to drive plan/response_text
        # below; each parser's own resolution (``matched``) stays authoritative.
        resolved_intent = ReasoningEngine.resolve(frame, entities, context)

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
                resolved_intent=resolved_intent,
            )

        light_extended_spec = LIGHT_EXTENDED_INTENTS.get(frame.intent)
        if light_extended_spec is not None:
            return MatchResult(
                plan=map_to_service_call(command),
                response_text=light_extended_spec.response(matched, frame.parameters),
                frame=frame,
                command=command,
                resolved_intent=resolved_intent,
            )

        fan_extended_spec = FAN_EXTENDED_INTENTS.get(frame.intent)
        if fan_extended_spec is not None:
            return MatchResult(
                plan=map_to_service_call(command),
                response_text=fan_extended_spec.response(matched, frame.parameters),
                frame=frame,
                command=command,
                resolved_intent=resolved_intent,
            )

        climate_extended_spec = CLIMATE_EXTENDED_INTENTS.get(frame.intent)
        if climate_extended_spec is not None:
            climate_plan = map_to_service_call(command)
            if climate_plan is None:
                # build() declined (e.g. missing "temperature" attribute) -
                # fall through to "not understood" rather than speaking a
                # success response with nothing actually executed.
                return None
            return MatchResult(
                plan=climate_plan,
                response_text=climate_extended_spec.response(matched, frame.parameters),
                frame=frame,
                command=command,
                resolved_intent=resolved_intent,
            )

        # WorldModelQuery wave: StateQueryParser's four intents (HassStateQuery/
        # HassCheckState/HassExistsQuery/HassDeviceQuery) now stash the full
        # QueryResult (status included, not just the matched entities) - when
        # present, ResponseGenerator speaks it directly instead of the
        # QUERY_INTENTS response lambda below, which loses QueryResultStatus.
        query_result = frame.parameters.get("query_result")
        if query_result is not None:
            return MatchResult(
                plan=None,
                response_text=_RESPONSE_GENERATOR.respond(query_result),
                frame=frame,
                command=command,
                resolved_intent=resolved_intent,
            )

        query_spec = QUERY_INTENTS.get(frame.intent)
        if query_spec is not None:
            return MatchResult(
                plan=None,
                response_text=query_spec.response(matched, frame.parameters),
                frame=frame,
                command=command,
                resolved_intent=resolved_intent,
            )

        spec = INTENTS.get(frame.intent)
        if spec is None:
            return None
        return MatchResult(
            plan=map_to_service_call(command),
            response_text=spec.response(matched),
            frame=frame,
            command=command,
            resolved_intent=resolved_intent,
        )
