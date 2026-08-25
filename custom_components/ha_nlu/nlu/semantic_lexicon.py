"""Shared deterministic German lexicon with source spans.

The semantic compiler must reason about *meaning components*, not complete
sentences.  This module is the single dependency-free vocabulary used for
that purpose.  It returns every recognised component together with its
position in the utterance, so consumers can detect overlaps, conflicts and
unexplained meaningful words without depending on word order.

The lexicon deliberately contains no Home Assistant runtime objects and no
statistical model.  Adding a synonym extends every permutation in which that
meaning can occur; it does not add another sentence template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from typing import Iterable

from ..entities import normalize_for_compare
from .semantic_state import SemanticState
from .domain_operations import ACTION_EXPRESSIONS, COMMAND_MARKER_EXPRESSIONS, DOMAIN_EXPRESSIONS


class SemanticKind(Enum):
    """Kinds of independently observable meaning components."""

    COMMAND_MARKER = auto()
    ACTION = auto()
    DOMAIN = auto()
    DEVICE_CLASS = auto()
    STATE = auto()
    QUANTIFIER = auto()
    QUERY_SCOPE = auto()
    AUTOMATION_CUE = auto()
    PROPERTY = auto()
    COMPARATOR = auto()


@dataclass(frozen=True)
class Lexeme:
    kind: SemanticKind
    value: object
    expressions: tuple[str, ...]


@dataclass(frozen=True)
class SemanticSpan:
    kind: SemanticKind
    value: object
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SemanticAnalysis:
    text: str
    spans: tuple[SemanticSpan, ...]
    unexplained_tokens: tuple[str, ...]

    def values(self, kind: SemanticKind) -> frozenset[object]:
        return frozenset(span.value for span in self.spans if span.kind is kind)

    def matching(self, kind: SemanticKind) -> tuple[SemanticSpan, ...]:
        return tuple(span for span in self.spans if span.kind is kind)

    def conflicts(self, kind: SemanticKind) -> bool:
        return len(self.values(kind)) > 1


# Expressions are regular-expression fragments.  They describe individual
# meanings, never whole sentences.  Inflection is therefore centralised once.
LEXEMES: tuple[Lexeme, ...] = (
    Lexeme(SemanticKind.COMMAND_MARKER, True, COMMAND_MARKER_EXPRESSIONS),
    *(Lexeme(SemanticKind.ACTION, action, expressions)
      for action, expressions in ACTION_EXPRESSIONS.items()),
    *(Lexeme(SemanticKind.DOMAIN, domain, expressions)
      for domain, expressions in DOMAIN_EXPRESSIONS.items()),
    Lexeme(SemanticKind.DEVICE_CLASS, ("binary_sensor", "window"), (
        r"fenster(?:kontakte?)?",
    )),
    Lexeme(SemanticKind.DEVICE_CLASS, ("binary_sensor", "door"), (r"tür(?:en)?",)),
    Lexeme(SemanticKind.DEVICE_CLASS, ("binary_sensor", "garage_door"), (
        r"garagentor(?:e)?",
    )),
    Lexeme(SemanticKind.DEVICE_CLASS, ("binary_sensor", "motion"), (
        r"bewegungsmelder", r"bewegungssensor(?:en)?",
    )),
    Lexeme(SemanticKind.STATE, SemanticState.OPEN, (
        r"offen\w*", r"geöffnet\w*", r"hochgefahren\w*", r"oben",
    )),
    Lexeme(SemanticKind.STATE, SemanticState.CLOSED, (
        r"geschlossen\w*", r"runtergefahren\w*", r"heruntergefahren\w*", r"unten", r"zu",
    )),
    Lexeme(SemanticKind.STATE, SemanticState.ON, (
        r"an", r"ein", r"eingeschaltet\w*", r"angeschaltet\w*",
    )),
    Lexeme(SemanticKind.STATE, SemanticState.OFF, (r"aus", r"ausgeschaltet\w*",)),
    Lexeme(SemanticKind.QUANTIFIER, "all", (
        r"alle", r"sämtliche\w*", r"jede\w*", r"die\s+ganzen",
    )),
    Lexeme(SemanticKind.QUANTIFIER, "both", (r"beide\w*",)),
    Lexeme(SemanticKind.QUERY_SCOPE, "count", (r"wie\s+viele",)),
    Lexeme(SemanticKind.QUERY_SCOPE, "locations", (
        r"wo", r"in\s+welchen\s+räumen", r"welche\s+räume",
    )),
    Lexeme(SemanticKind.QUERY_SCOPE, "exists", (
        r"gibt\s+es", r"haben\s+wir", r"irgendein\w*", r"irgendwelche",
    )),
    Lexeme(SemanticKind.QUERY_SCOPE, "none", (r"kein\w*",)),
    Lexeme(SemanticKind.AUTOMATION_CUE, "predicate", (
        r"wenn", r"sobald", r"falls", r"sofern", r"nur\s+wenn",
    )),
    Lexeme(SemanticKind.PROPERTY, "temperature", (
        r"temperatur", r"wärme", r"warm", r"kalt", r"grad",
    )),
    Lexeme(SemanticKind.PROPERTY, "humidity", (
        r"luftfeuchtigkeit", r"feuchtigkeit", r"feucht",
    )),
    Lexeme(SemanticKind.PROPERTY, "battery", (
        r"batteriestand", r"batterie", r"batterien",
    )),
    Lexeme(SemanticKind.PROPERTY, "power", (r"leistung",)),
    Lexeme(SemanticKind.PROPERTY, "energy", (
        r"stromverbrauch", r"energieverbrauch",
    )),
    Lexeme(SemanticKind.PROPERTY, "brightness", (r"helligkeit", r"hell",)),
    Lexeme(SemanticKind.COMPARATOR, "lt", (
        r"unter", r"weniger\s+als", r"dunkler\s+als",
    )),
    Lexeme(SemanticKind.COMPARATOR, "gt", (
        r"über", r"mehr\s+als", r"heller\s+als",
    )),
    Lexeme(SemanticKind.COMPARATOR, "lte", (r"höchstens", r"nicht\s+höher\s+als")),
    Lexeme(SemanticKind.COMPARATOR, "gte", (r"mindestens",)),
    Lexeme(SemanticKind.QUERY_SCOPE, "average", (r"durchschnitt\w*",)),
    Lexeme(SemanticKind.QUERY_SCOPE, "measurement", (
        r"wie\s+viel", r"aktuell\w*", r"momentan", r"gerade",
    )),
)


MEASUREMENT_PROPERTY_SPECS = {
    "temperature": ("sensor", "temperature", "Temperatur", "temperatur"),
    "humidity": ("sensor", "humidity", "Luftfeuchtigkeit", "luftfeuchtigkeit"),
    "battery": ("sensor", "battery", "Batteriestand", "batterie"),
    "power": ("sensor", "power", "Leistung", "leistung"),
    "energy": ("sensor", "energy", "Energieverbrauch", "energieverbrauch"),
    "brightness": ("light", None, "Helligkeit", "helligkeit"),
}


_WORD_RE = re.compile(r"[\wäöüß]+", re.I)
_FILLERS = frozenset(
    normalize_for_compare(word)
    for word in (
        "der die das den dem des ein eine einen einem einer bitte kannst du mir mal doch "
        "jetzt vorhanden vorhandenen im in am auf beim nach von zur zum und oder soll sollen dort "
        "möchte will ich dass ob davon denn noch es sie sein sind ist stehen steht hat haben werde werden wird welche welcher welches was wie "
        "kannste könntest koenntest würdest wuerdest würd wuerd gern wär waer nett "
        "wiedergabe "
        "komplett ganz ganze ganzen ganzer ganzes vollständig halb halbe halber halben hälfte höhe prozent einmal zwar"
    ).split()
)


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[Lexeme, re.Pattern[str]], ...]:
    compiled: list[tuple[Lexeme, re.Pattern[str]]] = []
    for lexeme in LEXEMES:
        # Longest textual alternative first makes the chosen spans stable.
        expressions = sorted(lexeme.expressions, key=len, reverse=True)
        compiled.append((lexeme, re.compile(r"\b(?:" + "|".join(expressions) + r")\b", re.I)))
    return tuple(compiled)


def _remove_shadowed(spans: Iterable[SemanticSpan]) -> tuple[SemanticSpan, ...]:
    """Remove shorter same-kind/same-value spans contained in longer ones."""
    ordered = sorted(spans, key=lambda span: (span.start, -(span.end - span.start), span.kind.value))
    selected: list[SemanticSpan] = []
    for span in ordered:
        if any(
            other.kind is span.kind
            and other.value == span.value
            and other.start <= span.start
            and other.end >= span.end
            for other in selected
        ):
            continue
        selected.append(span)
    return tuple(sorted(selected, key=lambda span: (span.start, span.end, span.kind.value)))


def analyse_semantics(text: str) -> SemanticAnalysis:
    """Scan ``text`` once and return order-independent semantic evidence."""
    found: list[SemanticSpan] = []
    for lexeme, pattern in _compiled():
        for match in pattern.finditer(text):
            found.append(SemanticSpan(
                kind=lexeme.kind,
                value=lexeme.value,
                start=match.start(),
                end=match.end(),
                text=match.group(0),
            ))
    spans = _remove_shadowed(found)
    covered = [False] * len(text)
    for span in spans:
        for position in range(span.start, span.end):
            covered[position] = True
    unexplained = tuple(
        match.group(0)
        for match in _WORD_RE.finditer(text)
        if not all(covered[position] for position in range(match.start(), match.end()))
        and normalize_for_compare(match.group(0)) not in _FILLERS
        and not match.group(0).isdigit()
    )
    return SemanticAnalysis(text=text, spans=spans, unexplained_tokens=unexplained)
