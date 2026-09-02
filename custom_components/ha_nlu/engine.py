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
from datetime import datetime, timedelta
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
from .entities import EntitySnapshot
from .nlu.entity_resolution import (
    ResolveStatus,
    all_mentioned_entities,
    resolve_entity,
)
from .nlu.entity_clarification import render_candidate_question
from .nlu.composition import build_compositional_plan, project_target
from .nlu.command import SemanticCommand, build_semantic_command
from .nlu.context import ConversationContext
from .nlu.debug import DebugTrace, format_command
from .nlu.degree_semantics import extract_degree
from .nlu.frame import AreaReference, SemanticFrame, TargetReference
from .nlu.normalize import normalize
from .nlu.language_frontend import LanguageDocument, analyse_language
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
from .nlu.semantic_compiler import (
    SemanticCommandCompiler,
    SemanticQueryCompiler,
    has_exclusion_clause,
)
from .nlu.semantic_lexicon import SemanticKind, analyse_semantics
from .nlu.semantic_interpreter import InterpreterResult, SemanticInterpreter
from .nlu.semantic_catalog import (
    V7_AUTHORITATIVE_DIRECT_CAPABILITIES,
    V7_AUTHORITY_MIN_MARGIN,
)
from .nlu.meaning import SemanticTurn, analyse_turn
from .nlu.semantic_utterance import ClauseRole, SpeechAct, analyse_utterance
from .nlu.understanding import (
    ShadowComparison,
    UnderstandingAuthority,
    UnderstandingKind,
    UnderstandingOutcome,
    compare_outcomes,
)
from .nlu.verb_state_query import (
    match_contextual_verb_state_query,
    match_verb_state_query,
)
from .nlu.semantic_location import resolve_coordinated_locations
from .nlu.validator import validate_command
from .automation_action_parser import AutomationActionParser
from .automation_notification import is_notification_shaped, notification_action_from_request
from .automation_condition_parser import AutomationConditionParser, split_on_top_level_and
from .nlu.automation_shell_normalization import strip_automation_shell
from .calendar_automation import parse_calendar_automation_draft
from .automation_trigger_parser import _AUTOMATION_TRIGGER_RE, AutomationTriggerParser
from .location_property_query import LocationPropertyQueryParser, LocationQueryFeedback
from .contextual_property import ContextualPropertyResolver
from .conversation_correction import ConversationCorrectionResolver
from .relative_time_command_parser import RelativeTimeCommandParser
from .productivity import parse_duration_seconds
from .scheduled_time_command_parser import ScheduledTimeCommandParser
from .nlu.automation_model import AutomationModel, TriggerModel, TriggerType, render_automation_tree
from .nlu.automation_model import TriggerTarget
from .nlu.action_model import ActionGroup, ActionModel, ActionType
from .nlu.automation_sentence_split import split_trigger_action
from .nlu.automation_validator import validate_automation
from .nlu.automation_operations import validate_registered_operation
from .nlu.condition_model import ConditionModel, ConditionNode, ConditionType
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
    r"|\b(?:läuft|laeuft)\b"
    r"|\bwas\s+macht\b"
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

_RECURRING_TIME_RE = re.compile(
    r"\b(?:jede[nr]?|an\s+jedem)\s+"
    r"(?:(?P<interval>zweiten?)\s+)?"
    r"(?P<day>werktag|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)"
    r"(?:s|en)?\s+(?:um\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{1,2}))?\s*(?:uhr)?\b",
    re.IGNORECASE,
)
_PERSISTENT_STATE_RE = re.compile(
    r"\b(?P<amount>\d+|ein(?:e|en)?|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn)\s*"
    r"(?P<unit>sekunden?|minuten?|stunden?)\s+"
    r"(?P<state>offen|geöffnet|geschlossen|an|aus)\s+bleib(?:t|en)\b",
    re.IGNORECASE,
)
_REPEATED_EVENT_RE = re.compile(r"\b(?:zweimal|zwei\s*mal|2\s*mal)\b", re.IGNORECASE)
_WITHIN_WINDOW_RE = re.compile(
    r"\binnerhalb\s+von\s+"
    r"(?:\d+|ein(?:e|en|er)?|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn)\s*"
    r"(?:sekunden?|minuten?|stunden?)\b",
    re.IGNORECASE,
)
_RECURRING_WEEKDAYS = {
    "montag": ("mon",), "dienstag": ("tue",), "mittwoch": ("wed",),
    "donnerstag": ("thu",), "freitag": ("fri",), "samstag": ("sat",),
    "sonntag": ("sun",),
    "werktag": ("mon", "tue", "wed", "thu", "fri"),
}
_SMALL_NUMBERS = {
    "ein": 1, "eine": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9, "zehn": 10,
}


def _weekday_number(day: str) -> int:
    return {
        "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
        "freitag": 4, "samstag": 5, "sonntag": 6,
    }.get(day, 0)

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

_UNSAFE_DIRECT_COMMAND_MODIFIER_RE = re.compile(
    r"\b(?:nicht(?!\s+(?:höher|hoeher|niedriger|mehr|weniger)\s+als\b)|"
    r"kein\w*|ohne|vielleicht|normalerweise|gestern)\b",
    re.I,
)

def _clarification_question(clarification: ClarificationRequest) -> str:
    return render_candidate_question(clarification.candidates)


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
    # ReasoningEngine's composed view of the same match (V6.25/V6.26).
    # ``_build_match_result`` uses it as a consistency gate for explicit,
    # singular targets before a service plan can be returned.
    # For a current-turn floor reference ("oben"/"unten") this can diverge
    # from ``command`` - ``SemanticFrame`` has no floor field, so
    # ``ReasoningEngine.resolve()`` can only pick up a floor from
    # ``ConversationContext.last_floor`` (a remembered turn), never from the
    # sentence just parsed. Known, documented, not a behaviour regression
    # since nothing reads this field yet.
    resolved_intent: ResolvedSemanticIntent | None = None
    # Read-only answers that do not originate from a SemanticCommand still
    # need conversational focus for pronouns and elliptical follow-ups.
    context_entities: tuple[EntitySnapshot, ...] = ()
    context_predicate: str | None = None
    explanation_text: str | None = None


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
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
    ) -> MatchResult | CommandPlan | None:
        turn = analyse_turn(text)
        utterance = turn.utterance
        if utterance.speech_act is SpeechAct.QUERY:
            verb_answer = match_verb_state_query(
                text, entities, turn.temporal_perspective
            )
            if verb_answer is not None:
                return MatchResult(
                    plan=None,
                    response_text=verb_answer.response_text,
                    context_entities=verb_answer.entities,
                    context_predicate=verb_answer.predicate,
                    explanation_text=verb_answer.explanation_text,
                )
        # Trigger/condition clauses belong to the automation composer and
        # must never degrade into an immediate direct command. Likewise, a
        # hypothetical/uncertain or explicitly negated command is not a safe
        # service call. This one discourse gate protects every parser below.
        if utterance.speech_act is SpeechAct.AUTOMATION or (
            utterance.speech_act is SpeechAct.COMMAND
            and not utterance.safe_to_execute_directly
        ):
            return None
        coordinated_targets = self._match_coordinated_named_targets(
            text, entities, world_model, turn
        )
        if coordinated_targets is not None:
            return coordinated_targets
        # An explicit exception is a safety boundary: only the compiler that
        # resolves and subtracts every named exclusion may accept it.  Never
        # fall through to a broader legacy group grammar that could silently
        # execute the command for all entities, including the exception.
        if has_exclusion_clause(turn.normalized_text):
            exclusion_result = SemanticCommandCompiler.compile(
                turn.normalized_text,
                entities,
                world_model,
                turn.semantic_analysis,
            )
            if isinstance(exclusion_result, ParseResult):
                return self._build_match_result(exclusion_result, entities)
            if isinstance(exclusion_result, ClarificationRequest):
                return MatchResult(
                    plan=None,
                    response_text=_clarification_question(exclusion_result),
                    clarification=exclusion_result,
                )
            return None
        segments = [segment for segment in _AND_SPLIT_RE.split(text) if segment.strip()]
        if len(segments) > 1:
            # ``und`` can connect two commands, but it can also coordinate
            # locations or exclusions inside one command. Let the shared
            # semantic compiler prove the latter interpretation before the
            # established atomic multi-command path splits the utterance.
            normalized_whole = normalize(text)
            is_single_coordinated_meaning = (
                re.search(r"\b(?:außer|ausser|mit\s+ausnahme\s+von)\b", normalized_whole, re.I)
                is not None
                or resolve_coordinated_locations(
                    normalized_whole, entities, world_model
                ) is not None
            )
            if is_single_coordinated_meaning:
                whole_analysis = analyse_semantics(normalized_whole)
                whole_result = (
                    SemanticQueryCompiler.compile(
                        normalized_whole, entities, world_model, whole_analysis
                    )
                    if utterance.speech_act is SpeechAct.QUERY
                    else None
                )
                if whole_result is None and utterance.speech_act is not SpeechAct.QUERY:
                    whole_result = SemanticCommandCompiler.compile(
                        normalized_whole, entities, world_model, whole_analysis
                    )
                if isinstance(whole_result, ParseResult):
                    return self._build_match_result(whole_result, entities)
                if isinstance(whole_result, ClarificationRequest):
                    return MatchResult(
                        plan=None,
                        response_text=_clarification_question(whole_result),
                        clarification=whole_result,
                    )
            multi = self._match_multi(segments, entities, world_model)
            if (
                utterance.speech_act is SpeechAct.QUERY
                and multi is not None
                and any(command.plan is not None for command in multi.commands)
            ):
                return None
            return multi

        text = turn.normalized_text
        semantic_analysis = turn.semantic_analysis
        if (
            semantic_analysis.values(SemanticKind.COMMAND_MARKER)
            and _UNSAFE_DIRECT_COMMAND_MODIFIER_RE.search(text)
        ):
            return None
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
        if (
            utterance.speech_act is SpeechAct.QUERY
            and isinstance(result, ParseResult)
            and result.frame.intent not in QUERY_INTENTS
        ):
            result = None
        if isinstance(result, ClarificationRequest):
            # Legacy wildcard grammars may include politeness words in the
            # target or detect duplicate names before applying an explicitly
            # spoken area.  Let the constraint-based semantic compiler prove
            # a unique interpretation before asking an unnecessary question.
            if utterance.speech_act is SpeechAct.QUERY:
                result = None
            else:
                semantic_result = SemanticCommandCompiler.compile(
                    text, entities, world_model, semantic_analysis
                )
                if isinstance(semantic_result, ParseResult):
                    result = semantic_result
        if result is None:
            result = (
                SemanticQueryCompiler.compile(
                    text, entities, world_model, semantic_analysis
                )
                if utterance.speech_act is SpeechAct.QUERY
                else None
            )
            if result is None and utterance.speech_act is not SpeechAct.QUERY:
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

    def understand(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        document: LanguageDocument | None = None,
    ) -> UnderstandingOutcome[MatchResult | CommandPlan]:
        """Return a canonical, reason-carrying result for one direct turn.

        V7 interpretation runs first.  Capabilities listed in
        ``V7_AUTHORITATIVE_DIRECT_CAPABILITIES`` use its validated payload;
        all other capabilities retain ``match()`` as a compatibility
        fallback.  The explicit cohort is expanded only after a reproducible
        shadow comparison has classified every divergence.
        """
        document = document or analyse_language(text, entities)
        interpreted = SemanticInterpreter.interpret(
            document,
            entities,
            world_model,
            compile_result=True,
            # The compiler below performs authoritative target resolution.
            # A second all-mentions scan only enriches shadow evidence and is
            # prohibitively expensive for large registries, so production
            # keeps it disabled while ``compare_understanding_pipelines()``
            # explicitly enables it.
            resolve_registry=False,
        )
        v7_result = self._interpreted_match_result(interpreted, entities)
        if self._is_v7_authoritative(v7_result, interpreted):
            result: MatchResult | CommandPlan | None = v7_result
            authority = UnderstandingAuthority.V7_MIGRATED
        else:
            result = self.match(text, entities, world_model)
            if result is not None:
                authority = UnderstandingAuthority.LEGACY
            elif v7_result is not None:
                result = v7_result
                authority = UnderstandingAuthority.V7_FALLBACK
            else:
                authority = UnderstandingAuthority.NONE
        # The loss-aware frontend recognizes bounded safety-critical spelling
        # variants (especially a mistyped negation) that legacy grammars may
        # otherwise absorb into a wildcard entity name.  The canonical V7
        # boundary is authoritative for non-executability.
        if (
            document.utterance.speech_act is SpeechAct.COMMAND
            and not document.utterance.safe_to_execute_directly
        ):
            result = None
            authority = UnderstandingAuthority.NONE
        return self._direct_understanding_outcome(
            text, document, interpreted, result, entities, authority
        )

    def compare_understanding_pipelines(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        document: LanguageDocument | None = None,
    ) -> ShadowComparison:
        """Compare legacy and fully compiled V7 without executing either.

        This explicit diagnostic entry point keeps the production
        ``understand()`` fast: registry resolution and semantic compilation
        are only forced for the shadow side when a caller asks for a report.
        Both payloads are immutable plans or read-only answers; neither path
        invokes a Home Assistant service.
        """
        document = document or analyse_language(text, entities)
        interpreted = SemanticInterpreter.interpret(
            document,
            entities,
            world_model,
            compile_result=True,
            resolve_registry=True,
        )
        legacy_result = self.match(text, entities, world_model)
        v7_result = self._interpreted_match_result(interpreted, entities)
        if (
            document.utterance.speech_act is SpeechAct.COMMAND
            and not document.utterance.safe_to_execute_directly
        ):
            legacy_result = None
            v7_result = None
        legacy_outcome = self._direct_understanding_outcome(
            text,
            document,
            interpreted,
            legacy_result,
            entities,
            (
                UnderstandingAuthority.LEGACY
                if legacy_result is not None
                else UnderstandingAuthority.NONE
            ),
        )
        v7_outcome = self._direct_understanding_outcome(
            text,
            document,
            interpreted,
            v7_result,
            entities,
            (
                UnderstandingAuthority.V7_FALLBACK
                if v7_result is not None
                else UnderstandingAuthority.NONE
            ),
        )
        return compare_outcomes(legacy_outcome, v7_outcome)  # type: ignore[arg-type]

    def _interpreted_match_result(
        self,
        interpreted: InterpreterResult,
        entities: list[EntitySnapshot],
    ) -> MatchResult | CommandPlan | None:
        """Turn the interpreter parse into the same validated payload shape."""
        if interpreted.compositional_plan is not None:
            rendered: list[MatchResult] = []
            for selected in interpreted.compositional_plan.targets:
                candidate_text = project_target(
                    interpreted.compositional_plan, selected
                )
                parsed = SemanticCommandCompiler.compile(
                    candidate_text,
                    entities,
                    analysis=analyse_semantics(candidate_text),
                )
                if not isinstance(parsed, ParseResult):
                    return None
                result = self._build_match_result(parsed, entities)
                if result is None or result.plan is None:
                    return None
                rendered.append(result)
            return CommandPlan(tuple(rendered))
        if isinstance(interpreted.parse_result, ParseResult):
            if interpreted.parse_result.response_text is not None:
                return MatchResult(
                    plan=None,
                    response_text=interpreted.parse_result.response_text,
                    context_entities=tuple(interpreted.parse_result.resolved_entities),
                    context_predicate=interpreted.parse_result.context_predicate,
                    explanation_text=interpreted.parse_result.explanation_text,
                )
            return NluEngine._build_match_result(interpreted.parse_result, entities)
        if isinstance(interpreted.parse_result, ClarificationRequest):
            return MatchResult(
                plan=None,
                response_text=_clarification_question(interpreted.parse_result),
                clarification=interpreted.parse_result,
            )
        return None

    @staticmethod
    def _direct_capability(
        result: MatchResult | CommandPlan | None,
    ) -> tuple[str, str] | None:
        """Return the deterministic domain/intent authority key."""
        if isinstance(result, CommandPlan):
            intents = {
                command.frame.intent
                for command in result.commands
                if command.frame is not None
            }
            domains = {
                entity.domain
                for command in result.commands
                if command.command is not None
                for entity in command.command.entities
            }
            if len(intents) == 1 and len(domains) == 1:
                return next(iter(domains)), next(iter(intents))
            return None
        if not isinstance(result, MatchResult):
            return None
        if result.clarification is not None:
            domains = {entity.domain for entity in result.clarification.candidates}
            if len(domains) == 1:
                return next(iter(domains)), result.clarification.pending_intent
            return None
        if result.frame is None:
            domains = {entity.domain for entity in result.context_entities}
            if result.context_predicate is not None and len(domains) == 1:
                return next(iter(domains)), "HassVerbStateQuery"
            return None
        domains = {entity.domain for entity in result.command.entities} if (
            result.command is not None
        ) else set()
        if len(domains) == 1:
            return next(iter(domains)), result.frame.intent
        if result.frame.target is not None and result.frame.target.domain is not None:
            return result.frame.target.domain, result.frame.intent
        return None

    @classmethod
    def _is_v7_authoritative(
        cls,
        result: MatchResult | CommandPlan | None,
        interpreted: InterpreterResult,
    ) -> bool:
        if cls._direct_capability(result) not in V7_AUTHORITATIVE_DIRECT_CAPABILITIES:
            return False
        if isinstance(result, MatchResult) and result.clarification is not None:
            return True
        complete = tuple(
            candidate for candidate in interpreted.candidates if candidate.complete
        )
        return bool(complete) and (
            len(complete) == 1
            or complete[0].score - complete[1].score >= V7_AUTHORITY_MIN_MARGIN
        )

    @staticmethod
    def _candidate_margin(interpreted: InterpreterResult) -> float | None:
        complete = tuple(
            candidate for candidate in interpreted.candidates if candidate.complete
        )
        if len(complete) < 2:
            return None
        return complete[0].score - complete[1].score

    def _direct_understanding_outcome(
        self,
        text: str,
        document: LanguageDocument,
        interpreted: InterpreterResult,
        result: MatchResult | CommandPlan | None,
        entities: list[EntitySnapshot],
        authority: UnderstandingAuthority,
    ) -> UnderstandingOutcome[MatchResult | CommandPlan]:
        """Render one direct pipeline result as the canonical V7 outcome."""
        route = type(result).__name__ if result is not None else "no_match"
        margin = self._candidate_margin(interpreted)
        corrections = (
            (interpreted.selected_variant.source,)
            if interpreted.selected_variant is not None
            and interpreted.selected_variant.source != "original"
            else ()
        )

        if isinstance(result, CommandPlan):
            has_action = any(command.plan is not None for command in result.commands)
            return UnderstandingOutcome(
                kind=(UnderstandingKind.COMMAND if has_action else UnderstandingKind.QUERY),
                source_text=text,
                normalized_text=document.utterance.normalized_text,
                speech_act=document.utterance.speech_act,
                payload=result,
                candidates=interpreted.candidates,
                unexplained_tokens=document.semantics.unexplained_tokens,
                corrections=corrections,
                route=route,
                authority=authority,
                margin=margin,
            )

        if isinstance(result, MatchResult):
            if result.clarification is not None:
                return UnderstandingOutcome(
                    kind=(
                        UnderstandingKind.AMBIGUOUS
                        if len(result.clarification.candidates) > 1
                        else UnderstandingKind.CLARIFICATION
                    ),
                    source_text=text,
                    normalized_text=document.utterance.normalized_text,
                    speech_act=document.utterance.speech_act,
                    payload=result,
                    candidates=interpreted.candidates,
                    reason=ParseFailureReason.AMBIGUOUS_TARGET,
                    speech=result.response_text,
                    unexplained_tokens=document.semantics.unexplained_tokens,
                    corrections=corrections,
                    route=route,
                    authority=authority,
                    margin=margin,
                )
            return UnderstandingOutcome(
                kind=(
                    UnderstandingKind.COMMAND
                    if result.plan is not None
                    else UnderstandingKind.QUERY
                ),
                source_text=text,
                normalized_text=document.utterance.normalized_text,
                speech_act=document.utterance.speech_act,
                payload=result,
                candidates=interpreted.candidates,
                speech=result.response_text,
                unexplained_tokens=document.semantics.unexplained_tokens,
                corrections=corrections,
                route=(result.frame.intent if result.frame is not None else route),
                authority=authority,
                margin=margin,
            )

        feedback = self.understanding_feedback(text, entities)
        unsafe = (
            document.utterance.speech_act is SpeechAct.COMMAND
            and not document.utterance.safe_to_execute_directly
        )
        return UnderstandingOutcome(
            kind=(UnderstandingKind.UNSAFE if unsafe else UnderstandingKind.UNSUPPORTED),
            source_text=text,
            normalized_text=document.utterance.normalized_text,
            speech_act=document.utterance.speech_act,
            reason=(
                ParseFailureReason.UNSAFE_INFERENCE
                if unsafe
                else feedback.reason if feedback is not None
                else ParseFailureReason.NO_GRAMMAR
            ),
            speech=feedback.speech if feedback is not None else None,
            candidates=interpreted.candidates,
            unexplained_tokens=document.semantics.unexplained_tokens,
            corrections=corrections,
            route=route,
            authority=authority,
            margin=margin,
        )

    def understand_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
        document: LanguageDocument | None = None,
    ) -> UnderstandingOutcome[AutomationMatchResult]:
        """Canonical V7 boundary for a trigger/condition/action turn."""
        document = document or analyse_language(text, entities)
        result = self.match_automation(text, entities, world_model, context)
        interpreted = SemanticInterpreter.interpret(
            document,
            entities,
            world_model,
            compile_result=False,
            resolve_registry=result is None,
        )
        if result is not None:
            return UnderstandingOutcome(
                kind=UnderstandingKind.AUTOMATION,
                source_text=text,
                normalized_text=document.utterance.normalized_text,
                speech_act=document.utterance.speech_act,
                payload=result,
                candidates=interpreted.candidates,
                unexplained_tokens=document.semantics.unexplained_tokens,
                route="automation",
            )
        return UnderstandingOutcome(
            kind=(
                UnderstandingKind.UNSAFE
                if document.utterance.speech_act is SpeechAct.AUTOMATION
                and not document.utterance.safe_to_execute_directly
                and document.utterance.polarity.name == "NEGATIVE"
                else UnderstandingKind.UNSUPPORTED
            ),
            source_text=text,
            normalized_text=document.utterance.normalized_text,
            speech_act=document.utterance.speech_act,
            reason=ParseFailureReason.INCOMPLETE_REQUEST,
            candidates=interpreted.candidates,
            unexplained_tokens=document.semantics.unexplained_tokens,
            route="automation_no_match",
        )

    def _match_coordinated_named_targets(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None,
        turn: SemanticTurn,
    ) -> CommandPlan | None:
        """Distribute one direct action over explicitly coordinated names."""
        plan = build_compositional_plan(turn, entities)
        if plan is None:
            return None
        rendered: list[MatchResult] = []
        for selected in plan.targets:
            candidate = project_target(plan, selected)
            result = self.match(candidate, entities, world_model)
            if not isinstance(result, MatchResult) or result.plan is None:
                return None
            rendered.append(result)
        return CommandPlan(tuple(rendered))

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
            mentioned = all_mentioned_entities(text, entities or [])
            if mentioned:
                names = ", ".join(entity.friendly_name for entity in mentioned)
                return UnderstandingFeedback(
                    ParseFailureReason.UNSUPPORTED_CAPABILITY,
                    f"Ich habe {names} gefunden, aber die gewünschte Funktion "
                    "ist für diese Geräte nicht eindeutig unterstützt.",
                    {"entity_ids": tuple(entity.entity_id for entity in mentioned)},
                )
            return UnderstandingFeedback(
                ParseFailureReason.UNKNOWN_ENTITY,
                "Ich habe die Aktion erkannt, aber kein eindeutig passendes, "
                "für HomeIntent freigegebenes Gerät gefunden.",
            )
        if analyse_utterance(text).speech_act is SpeechAct.QUERY:
            return UnderstandingFeedback(
                ParseFailureReason.UNSUPPORTED_PROPERTY,
                "Ich habe die Frage erkannt, aber die gewünschte Eigenschaft oder das Ziel nicht gefunden.",
            )
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
                result is None
                and results
                and results[-1].command is not None
                and results[-1].plan is not None
            ):
                previous = results[-1].command
                # The splitter removes the conjunction. Re-add only its
                # discourse role and let the established follow-up grammar
                # prove whether this fragment can inherit the prior action.
                result = self.match_command_followup(
                    f"und {segment.strip()}",
                    entities,
                    ConversationContext(
                        last_command=previous,
                        last_entities=previous.entities,
                        last_area=previous.area,
                        pending_clarification=None,
                    ),
                )
            if (
                not isinstance(result, MatchResult)
                or result.clarification is not None
                or result.command is None
            ):
                return None
            results.append(result)
        actionable_commands = tuple(
            result.command
            for result in results
            if result.plan is not None and result.command is not None
        )
        query_commands = tuple(
            result.command
            for result in results
            if result.plan is None and result.command is not None
        )
        action_ids = {
            entity.entity_id
            for command in actionable_commands
            for entity in command.entities
        }
        query_ids = {
            entity.entity_id
            for command in query_commands
            for entity in command.entities
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
        adjustment = extract_degree(normalized)
        intent = self._context_followup_parser.parse(adjustment.text)
        if intent is None:
            return None

        if intent in LIGHT_EXTENDED_INTENTS:
            domain = "light"
            parameters = {"step_percent": adjustment.light_percent}
        elif intent in CLIMATE_EXTENDED_INTENTS:
            domain = "climate"
            parameters = {"step": adjustment.climate_degrees}
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

        normalized = re.sub(
            r"^(?:dann|danach|also)\s+", "", normalize(text), flags=re.IGNORECASE
        )
        remembered_entities = (
            context.memory.entities if context.memory is not None else context.last_entities
        )
        result = self._reference_parser.parse(
            normalized, entities, remembered_entities, context.last_area
        )
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
        if context is None:
            return None

        remembered_entities = (
            context.memory.entities if context.memory is not None else context.last_entities
        )
        remembered_predicate = (
            context.memory.predicate
            if context.memory is not None and context.memory.predicate is not None
            else context.last_query_predicate
        )
        contextual_answer = match_contextual_verb_state_query(
            text,
            entities,
            remembered_entities,
            remembered_predicate,
        )
        if contextual_answer is not None:
            return MatchResult(
                plan=None,
                response_text=contextual_answer.response_text,
                context_entities=contextual_answer.entities,
                context_predicate=contextual_answer.predicate,
                explanation_text=contextual_answer.explanation_text,
            )

        if (
            context.last_command is None
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
        if re.match(
            r"^(?:welche\b|(?:in der|in dem|im|am|beim)\b|oben\b|unten\b)",
            normalized,
            re.IGNORECASE,
        ):
            # The follow-up grammar stores deltas, not discourse particles.
            # "Und" is optional in natural dialogue; canonicalize both forms
            # to the same grammar instead of duplicating every sentence.
            normalized = f"Und {normalized}"
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

        automation = next(iter(match.matched))
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

        automation = next(iter(match.matched))
        return AutomationToggleMatchResult(
            automation=automation,
            enable=match.enable,
            response_text=(
                f"Automation wurde {'aktiviert' if match.enable else 'deaktiviert'}."
            ),
        )

    def _try_extract_notification_from_trigger_clause(
        self,
        text: str,
        parse_context: ParseContext,
        entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...],
    ) -> tuple[str, str] | None:
        """Extract a trailing notification action from a trigger-first clause
        with no comma at all, e.g. "sobald das Fenster geöffnet wird eine
        Push-Nachricht an Philipp schickt" - the shape left behind once
        ``strip_automation_shell()`` removes a meta-shell that had no comma
        of its own before "die" either.

        Returns (trigger_text, action_text) only once both halves
        independently validate through their own dedicated parser
        (``AutomationTriggerParser``/``notification_action_from_request()``)
        - never a guess. Returns ``None`` if no trigger connector is found,
        no trailing notification pattern is detected, or either half fails
        to parse.
        """
        notification_pattern_re = re.compile(
            r"\b(?:eine\s+)?(?:push[\s-]nachricht|benachrichtigung|nachricht|meldung|mitteilung)\s+"
            r"(?:an\s+den|an\s+die|an\s+dem|an|dem|der)\s+"
            r"[a-zäöüß][a-z0-9äöüß_-]*"
            r"(?:\s+(?:schick\w*|send\w*|geb\w*|sag\w*))?",
            re.IGNORECASE,
        )
        # ``(?<!\S)`` (not preceded by a non-whitespace char) instead of a
        # literal leading ``\s+`` so the connector is also recognized right
        # at the start of the string - the common case once an automation
        # shell has been stripped off the front of the sentence.
        for marker in re.finditer(r"(?<!\S)(wenn|sobald|falls)\b", text, re.IGNORECASE):
            trigger_with_action = text[marker.end():].strip(" ,")
            if not trigger_with_action:
                continue

            notification_match = notification_pattern_re.search(trigger_with_action)
            if notification_match is None:
                continue

            trigger_only = trigger_with_action[: notification_match.start()].strip(" ,")
            if not trigger_only:
                continue

            trigger_text = f"{marker.group(1)} {trigger_only}"
            parsed_trigger = self._automation_trigger_parser.parse(trigger_text, parse_context)
            if parsed_trigger is None:
                continue

            action_text = trigger_with_action[notification_match.start():].strip()
            notification = notification_action_from_request(action_text, trigger_text, entities)
            if notification is None:
                continue

            return (trigger_text, action_text)

        return None

    def _parse_action_or_notification(
        self,
        action_text: str,
        trigger_text: str,
        entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...],
        parse_context: ParseContext,
    ) -> tuple[ActionModel | ActionGroup, ...] | None:
        """Prefer the dedicated notification-vocabulary reader in
        ``automation_notification.py`` over the general action parser for a
        recipient-shaped clause; fall back to the general parser otherwise.

        ``notify_action.yaml``'s pre-existing grammar branches ("benachrichtige
        [mich|uns] [dass] {message}", "[schick|sende] ... eine Nachricht [dass]
        {message}") all end in a free-form wildcard ``{message}`` slot. Given a
        bare recipient clause with no "dass ..." content of its own (e.g.
        "benachrichtige mich" or "sende eine Nachricht an Philipp"), that
        wildcard can still match by swallowing the recipient token/prepositional
        phrase itself, producing a nonsensical raw message and never resolving
        a named recipient to its notify.* target.
        ``notification_action_from_request()``'s three patterns all
        ``fullmatch`` a tightly scoped verb+recipient / message+recipient
        shape with no trailing free text, so they never match a genuine
        explicit-content dictation ("... dass der Akku leer ist") - trying
        them first only ever intercepts the recipient-shaped clauses this
        module is meant to own, and falls through to the general parser
        (unchanged) for everything else.

        If the clause matches a notification shape but the recipient itself
        could not be resolved (unknown or ambiguous), that is a hard failure
        - falling through to the general parser here would let the same
        wildcard ``{message}`` slot swallow the unresolved recipient token
        as free-text message content, silently producing a wrong automation
        instead of refusing (never guess).
        """
        notification = notification_action_from_request(action_text, trigger_text, entities)
        if notification is not None:
            return (notification,)
        if is_notification_shaped(action_text):
            return None
        return self._parse_action_semantically(action_text, parse_context)

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
        # The live conversation router also supports capability-driven
        # device operations that have not yet migrated to MatchResult. Lift
        # those only through the closed automation operation allow-list.
        from .device_control import match_device_control

        legacy = match_device_control(text, context.entities)
        action = self._action_from_service_plan(
            legacy.plan if legacy is not None else None,
            context.entities,
        )
        if action is not None:
            return (action,)
        return self._automation_action_parser.parse(text, context)

    def parse_automation_actions(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
    ) -> tuple[ActionModel | ActionGroup, ...] | None:
        """Parse one replacement action through the shared semantic pipeline."""
        return self._parse_action_semantically(
            text, create_parse_context(entities, world_model=world_model)
        )

    def parse_automation_trigger(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
    ) -> TriggerModel | None:
        normalized = normalize(text)
        normalized = re.sub(
            r"^(?:wenn\s+)?(?:die\s+)?sonne\s+(?:untergeht|untergegangen\s+ist)$",
            "bei sonnenuntergang",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^(?:wenn\s+)?(?:die\s+)?sonne\s+(?:aufgeht|aufgegangen\s+ist)$",
            "bei sonnenaufgang",
            normalized,
            flags=re.IGNORECASE,
        )
        if not _AUTOMATION_TRIGGER_RE.search(normalized):
            normalized = "wenn " + normalized
        return self._automation_trigger_parser.parse(
            normalized, create_parse_context(entities, world_model=world_model)
        )

    def parse_automation_condition(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
    ) -> ConditionNode | None:
        normalized = normalize(text)
        normalized = re.sub(r"^nur\s+", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"^dass\s+", "wenn ", normalized, flags=re.IGNORECASE)
        if not re.search(r"\b(?:wenn|falls|sofern)\b", normalized, re.IGNORECASE):
            normalized = "wenn " + normalized
        return self._automation_condition_parser.parse(
            normalized, create_parse_context(entities, world_model=world_model)
        )

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
        # Strip optional automation meta-shells ("Erstelle eine Automation, die...")
        # before clause analysis, so trigger/action boundaries are recognized correctly.
        automation_shell_stripped_text, shell_was_present = strip_automation_shell(text)

        utterance = analyse_utterance(automation_shell_stripped_text)
        if utterance.speech_act is SpeechAct.QUERY or not _AUTOMATION_TRIGGER_RE.search(automation_shell_stripped_text):
            return None

        normalized = normalize(automation_shell_stripped_text)
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
        if split is not None:
            # ``split_trigger_action`` assumes trigger-then-action order
            # around the first comma. When the action actually comes first
            # ("Benachrichtige Philipp, wenn ..."), the first half won't
            # parse as a Trigger while the second half will - and the first
            # half parses as a valid Action on its own. Swap the halves in
            # that one specific, verified case rather than guessing.
            first_half, second_half = split
            if self._automation_trigger_parser.parse(first_half, parse_context) is None:
                second_as_trigger = self._automation_trigger_parser.parse(
                    second_half, parse_context
                )
                if second_as_trigger is not None:
                    first_as_action = self._parse_action_semantically(
                        first_half, parse_context
                    )
                    if not first_as_action:
                        notification = notification_action_from_request(
                            first_half, second_half, entities
                        )
                        first_as_action = (notification,) if notification is not None else None
                    if first_as_action:
                        split = (second_half, first_half)
        if split is None:
            candidates: list[tuple[str, str]] = []
            # The common utterance model already knows an action-first
            # clause followed by a trigger clause, independent of the
            # concrete action vocabulary. Let the established trigger and
            # action compilers validate the two meanings; no service call is
            # built here.
            action_clause = next(
                (clause for clause in utterance.clauses if clause.role is ClauseRole.ACTION),
                None,
            )
            trigger_clause = next(
                (clause for clause in utterance.clauses if clause.role is ClauseRole.TRIGGER),
                None,
            )
            if action_clause is not None and trigger_clause is not None:
                semantic_trigger = (
                    f"{trigger_clause.connector or 'wenn'} {trigger_clause.text}"
                )
                if (
                    self._automation_trigger_parser.parse(semantic_trigger, parse_context)
                    is not None
                    and self._parse_action_semantically(action_clause.text, parse_context)
                ):
                    candidates.append((semantic_trigger, action_clause.text))
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
                parsed_trigger = self._automation_trigger_parser.parse(
                    trigger_candidate, parse_context
                )
                parsed_actions = self._parse_action_semantically(
                    action_candidate, parse_context
                )
                if not parsed_actions:
                    notification = notification_action_from_request(
                        action_candidate, trigger_candidate, entities
                    )
                    parsed_actions = (notification,) if notification is not None else None
                if (
                    action_candidate
                    and parsed_trigger is not None
                    and parsed_actions
                ):
                    candidates.append((trigger_candidate, action_candidate))
            candidates = list(dict.fromkeys(candidates))
            if len(candidates) != 1:
                # Fallback for notification patterns trailing in trigger-first clauses:
                # "sobald das Fenster geöffnet wird eine Push-Nachricht an Philipp schicken"
                # Extract trailing notification action, then try to parse the trigger alone.
                split_candidate = self._try_extract_notification_from_trigger_clause(
                    normalized, parse_context, entities
                )
                if split_candidate is not None:
                    candidates.append(split_candidate)
                candidates = list(dict.fromkeys(candidates))
            if len(candidates) != 1:
                return None
            split = candidates[0]
        trigger_text, action_text = split

        condition_node: ConditionNode | None = None
        trigger = self._automation_trigger_parser.parse(trigger_text, parse_context)
        triggers: tuple[TriggerModel, ...] = ()
        if trigger is not None:
            triggers = (trigger,)
        else:
            parts = re.split(
                r"\s+oder\s+(?=(?:wenn|sobald|falls)\b)",
                trigger_text,
                flags=re.IGNORECASE,
            )
            if len(parts) > 1:
                parsed = tuple(
                    candidate
                    for part in parts
                    if (candidate := self._automation_trigger_parser.parse(part, parse_context))
                    is not None
                )
                if len(parsed) == len(parts):
                    triggers = tuple(
                        replace(candidate, trigger_id=f"ausloeser_{index}")
                        for index, candidate in enumerate(parsed, start=1)
                    )
        if not triggers:
            split_result = self._split_trigger_condition(trigger_text, parse_context)
            if split_result is None:
                return None
            trigger, condition_node = split_result
            triggers = (trigger,)

        actions = self._parse_action_or_notification(
            action_text, trigger_text, entities, parse_context
        )
        if not actions:
            return None

        conditions = (condition_node,) if condition_node is not None else ()
        model = AutomationModel(
            triggers=triggers, conditions=conditions, actions=actions, source_text=text,
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
            actions = self._parse_action_semantically(command_text, parse_context)
            if actions is not None:
                parsed = (actions, offset_seconds)
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

    def match_recurring_time_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        now: datetime,
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Build native time+weekday rules without enumerating word orders."""
        schedule = _RECURRING_TIME_RE.search(text)
        if schedule is None:
            return None
        hour = int(schedule.group("hour"))
        minute = int(schedule.group("minute") or 0)
        if hour > 23 or minute > 59:
            return None
        action_text = (text[:schedule.start()] + " " + text[schedule.end():]).strip(" ,.")
        action_text = re.sub(
            r"\bnur\s+zwischen\s+\w+\s+und\s+\w+\b", " ", action_text,
            flags=re.IGNORECASE,
        )
        action_text = re.sub(r"^(?:dann\s+)", "", action_text, flags=re.IGNORECASE)
        parse_context = create_parse_context(
            entities,
            world_model=world_model,
            last_entities=tuple(context.last_entities) if context is not None else (),
            last_area=context.last_area if context is not None else None,
        )
        actions = self._parse_action_semantically(action_text, parse_context)
        if not actions:
            return None
        day = schedule.group("day").casefold()
        conditions = [
            ConditionNode(condition=ConditionModel(
                type=ConditionType.WEEKDAY,
                weekdays=_RECURRING_WEEKDAYS[day],
            ))
        ]
        if schedule.group("interval"):
            # "Jeden zweiten Samstag" starts with the next occurrence and
            # then follows ISO-week parity. The anchor is fixed at creation.
            delta = (_weekday_number(day) - now.weekday()) % 7
            anchor = (now + timedelta(days=delta)).isocalendar().week % 2
            conditions.append(ConditionNode(condition=ConditionModel(
                type=ConditionType.TEMPLATE,
                raw_state=f"{{{{ (now().isocalendar().week % 2) == {anchor} }}}}",
            )))
        month_range = re.search(
            r"\bnur\s+zwischen\s+(?P<start>januar|februar|märz|maerz|april|mai|juni|"
            r"juli|august|september|oktober|november|dezember)\s+und\s+"
            r"(?P<end>januar|februar|märz|maerz|april|mai|juni|juli|august|september|"
            r"oktober|november|dezember)\b",
            text, re.IGNORECASE,
        )
        if month_range:
            months = {"januar": 1, "februar": 2, "märz": 3, "maerz": 3,
                      "april": 4, "mai": 5, "juni": 6, "juli": 7,
                      "august": 8, "september": 9, "oktober": 10,
                      "november": 11, "dezember": 12}
            start = months[month_range.group("start").casefold()]
            end = months[month_range.group("end").casefold()]
            expression = (
                f"{start} <= now().month <= {end}" if start <= end
                else f"now().month >= {start} or now().month <= {end}"
            )
            conditions.append(ConditionNode(condition=ConditionModel(
                type=ConditionType.TEMPLATE,
                raw_state="{{ " + expression + " }}",
            )))
        model = AutomationModel(
            triggers=(TriggerModel(type=TriggerType.TIME, time_hour=hour, time_minute=minute),),
            conditions=tuple(conditions), actions=actions, source_text=text,
        )
        error = validate_automation(model)
        return AutomationMatchResult(model, render_automation_tree(model), error)

    def match_persistent_state_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Understand "offen bleibt" as HA trigger ``for``, not an action delay."""
        persistent = _PERSISTENT_STATE_RE.search(text)
        if persistent is None:
            return None
        raw_amount = persistent.group("amount").casefold()
        amount = int(raw_amount) if raw_amount.isdigit() else _SMALL_NUMBERS.get(raw_amount)
        if amount is None:
            return None
        unit = persistent.group("unit").casefold()
        seconds = amount * (3600 if unit.startswith("st") else 60 if unit.startswith("min") else 1)
        state = persistent.group("state")
        replacement = f"{state} wird"
        rewritten = text[:persistent.start()] + replacement + text[persistent.end():]
        base = self.match_automation(rewritten, entities, world_model, context)
        if base is None or base.validation_error is not None or len(base.model.triggers) != 1:
            return None
        trigger = base.model.triggers[0]
        if trigger.type not in {TriggerType.STATE, TriggerType.NUMERIC_STATE}:
            return None
        model = replace(
            base.model,
            triggers=(replace(trigger, for_seconds=seconds),),
            source_text=text,
        )
        error = validate_automation(model)
        return AutomationMatchResult(model, render_automation_tree(model), error)

    def match_repeated_event_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Require the same state transition twice inside a bounded window."""
        trigger_clause = text.split(",", 1)[0]
        repeated = _REPEATED_EVENT_RE.search(trigger_clause)
        window = _WITHIN_WINDOW_RE.search(trigger_clause)
        if repeated is None or window is None:
            return None
        seconds = parse_duration_seconds(window.group())
        if seconds is None:
            return None
        rewritten = text
        for match in sorted((repeated, window), key=lambda item: item.start(), reverse=True):
            rewritten = rewritten[:match.start()] + " " + rewritten[match.end():]
        rewritten = re.sub(r"\s+", " ", rewritten)
        base = self.match_automation(rewritten, entities, world_model, context)
        if base is None or base.validation_error is not None or len(base.model.triggers) != 1:
            return None
        trigger = base.model.triggers[0]
        if trigger.type not in {TriggerType.STATE, TriggerType.NUMERIC_STATE}:
            return None
        model = replace(
            base.model,
            triggers=(replace(trigger, repeat_within_seconds=seconds),),
            source_text=text,
        )
        error = validate_automation(model)
        return AutomationMatchResult(model, render_automation_tree(model), error)

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
        if validate_registered_operation(
            plan.domain,
            plan.service,
            plan.data,
            frozenset({domain}),
        ):
            return ActionModel(
                type=ActionType.REGISTERED_SERVICE,
                target=target,
                service_domain=plan.domain,
                service_name=plan.service,
                service_data=dict(plan.data),
            )
        if plan.service == "turn_on":
            return ActionModel(type=ActionType.TURN_ON, target=target)
        if plan.service == "turn_off":
            return ActionModel(type=ActionType.TURN_OFF, target=target)
        return None

    @staticmethod
    def _action_from_service_plan(
        plan: ServiceCallPlan | None,
        available_entities: list[EntitySnapshot],
    ) -> ActionModel | None:
        """Lift one legacy direct plan through the same closed allow-list."""
        if plan is None:
            return None
        entity_ids = (
            tuple(plan.entity_id)
            if isinstance(plan.entity_id, list)
            else (plan.entity_id,)
        )
        selected = [
            entity for entity in available_entities if entity.entity_id in entity_ids
        ]
        if len(selected) != len(entity_ids):
            return None
        target_domains = frozenset(entity.domain for entity in selected)
        if not validate_registered_operation(
            plan.domain, plan.service, plan.data, target_domains
        ):
            return None
        target = TriggerTarget(
            domain=selected[0].domain,
            entity_id=(entity_ids[0] if len(entity_ids) == 1 else None),
            entity_ids=(entity_ids if len(entity_ids) > 1 else ()),
        )
        return ActionModel(
            type=ActionType.REGISTERED_SERVICE,
            target=target,
            service_domain=plan.domain,
            service_name=plan.service,
            service_data=dict(plan.data),
        )

    def match_calendar_event_automation(
        self,
        text: str,
        entities: list[EntitySnapshot],
        world_model: WorldModel | None = None,
        context: ConversationContext | None = None,
    ) -> AutomationMatchResult | None:
        """Create an automation driven by a real HA calendar event."""
        draft = parse_calendar_automation_draft(text, entities)
        if draft is None:
            return None
        parse_context = create_parse_context(
            entities,
            world_model=world_model,
            last_entities=tuple(context.last_entities) if context is not None else (),
            last_area=context.last_area if context is not None else None,
        )
        actions = self._parse_action_semantically(draft.action_text, parse_context)
        if not actions and re.search(r"\berinner(?:e|n|t)?\s+(?:mich|uns)\b", draft.action_text, re.IGNORECASE):
            message = (
                f"Kalendertermin {draft.summary_contains} {draft.event == 'start' and 'beginnt' or 'endet'}."
                if draft.summary_contains
                else f"Ein Kalendertermin {draft.event == 'start' and 'beginnt' or 'endet'}."
            )
            actions = (ActionModel(type=ActionType.NOTIFY, message=message),)
        if not actions:
            return None
        conditions = (
            (
                ConditionNode(
                    condition=ConditionModel(
                        type=ConditionType.CALENDAR_EVENT,
                        raw_state=draft.summary_contains,
                    )
                ),
            )
            if draft.summary_contains
            else ()
        )
        model = AutomationModel(
            triggers=(
                TriggerModel(
                    type=TriggerType.CALENDAR,
                    calendar_entity_id=draft.calendar_entity_id,
                    calendar_event=draft.event,
                    offset_minutes=draft.offset_minutes,
                ),
            ),
            conditions=conditions,
            actions=actions,
            source_text=text,
        )
        validation_error = validate_automation(model)
        response_text = render_automation_tree(model)
        if validation_error is not None:
            response_text = f"{response_text}\nvalidation_error: {validation_error.name}"
        return AutomationMatchResult(model, response_text, validation_error)

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
        decomposed = self._scheduled_time_command_parser.decompose(normalized)
        if decomposed is None:
            return None
        command_text, schedule = decomposed
        actions = self._parse_action_semantically(command_text, parse_context)
        if actions is None:
            return None
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

        # Defense in depth for every caller of this builder: a syntactic
        # question can only use registered read-only query intents. Never
        # return a service plan with a success sentence for a question.
        if (
            analyse_utterance(frame.source_text).speech_act is SpeechAct.QUERY
            and frame.intent not in QUERY_INTENTS
        ):
            return None

        # Gate on the Command Validator (v2 plan Phase 11) before building
        # anything. Today's parsers already self-police everything this
        # checks, so this never actually rejects a real match (see the 5
        # "real matches validate clean" regression tests in
        # tests/test_validator.py) - it is wired in now so a future,
        # non-self-policing parser (LLM Adapter) gets a real gatekeeper
        # instead of a silent no-op.
        if validate_command(command) is not None:
            return None

        # Compose the central semantic view once. For an explicitly resolved
        # singular target it is an execution gate: entity, domain, room/floor
        # and capability constraints must still agree after composition.
        resolved_intent = ReasoningEngine.resolve(frame, entities, context)
        if (
            context is None
            and frame.target is not None
            and frame.target.entity_id is not None
            and (
                len(matched) != 1
                or tuple(entity.entity_id for entity in resolved_intent.entities)
                != (matched[0].entity_id,)
            )
        ):
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
