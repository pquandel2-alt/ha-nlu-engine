"""Deterministic utterance and clause semantics for natural German.

This module deliberately models reusable meaning dimensions instead of full
sentence templates.  It is HA-free and cheap enough to run before every
parser.  Consumers still validate all targets, capabilities and values; the
analysis here only identifies the kind and safety shape of an utterance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

from .normalize import normalize


class SpeechAct(Enum):
    COMMAND = auto()
    QUERY = auto()
    AUTOMATION = auto()
    CONFIRMATION = auto()
    CORRECTION = auto()
    STATEMENT = auto()


class Modality(Enum):
    DIRECT = auto()
    POLITE = auto()
    WISH = auto()
    HYPOTHETICAL = auto()
    UNCERTAIN = auto()


class Polarity(Enum):
    POSITIVE = auto()
    NEGATIVE = auto()


class ClauseRole(Enum):
    MAIN = auto()
    TRIGGER = auto()
    CONDITION = auto()
    ACTION = auto()


@dataclass(frozen=True)
class MeaningClause:
    text: str
    role: ClauseRole
    connector: str | None = None


@dataclass(frozen=True)
class SemanticUtterance:
    source_text: str
    normalized_text: str
    speech_act: SpeechAct
    modality: Modality
    polarity: Polarity
    clauses: tuple[MeaningClause, ...]

    @property
    def safe_to_execute_directly(self) -> bool:
        return (
            self.speech_act is SpeechAct.COMMAND
            and self.modality not in {Modality.HYPOTHETICAL, Modality.UNCERTAIN}
            and self.polarity is Polarity.POSITIVE
        )


_QUESTION_RE = re.compile(
    r"^\s*(?:wer|was|wie|wo|wann|warum|wieso|welch\w*|ist|sind|hat|haben|"
    r"gibt|kann|kannst|könnte|koennte)\b",
    re.I,
)
_QUERY_REQUEST_RE = re.compile(
    r"^\s*(?:sag|sage|zeig|zeige|nenn|nenne)\s+(?:mir\s+)?(?:bitte\s+)?",
    re.I,
)
_AUTOMATION_RE = re.compile(
    r"\b(?:wenn|sobald|falls|sofern|jedes\s+mal\s+wenn|immer\s+wenn)\b",
    re.I,
)
_META_AUTOMATION_QUERY_RE = re.compile(
    r"^\s*(?:was\s+(?:passiert|geschieht)|wie\s+wäre\s+es|was\s+wäre)\b.*\b(?:wenn|falls)\b",
    re.I,
)
_INFORMATIONAL_CAN_RE = re.compile(r"^\s*kann\s+man\b", re.I)
_CONFIRMATION_RE = re.compile(
    r"^\s*(?:ja|nein|okay|ok|bestätigen|abbrechen|mach das)\s*[.!?]*$",
    re.I,
)
_CORRECTION_RE = re.compile(
    r"^\s*(?:nein[,.]?\s*)?(?:ich\s+meinte|nicht\s+.+?\s+sondern|nur\s+)",
    re.I,
)
_HYPOTHETICAL_RE = re.compile(
    r"\b(?:wäre|waere|würde|wuerde|hätte|haette)\b.*\b(?:wenn|falls)\b"
    r"|\bangenommen\b|\bwas\s+wäre\s+wenn\b|\bwas\s+(?:passiert|geschieht)\b.*\bwenn\b",
    re.I,
)
_UNCERTAIN_RE = re.compile(
    r"\b(?:vielleicht|eventuell|möglicherweise|moeglicherweise|normalerweise)\b",
    re.I,
)
_WISH_RE = re.compile(
    r"\b(?:ich\s+(?:hätte|haette|möchte|moechte|will)\s+(?:gern|gerne)?|"
    r"ich\s+wünsche\s+mir)\b",
    re.I,
)
_POLITE_RE = re.compile(
    r"\b(?:bitte|kannst\s+du|könntest\s+du|koenntest\s+du|"
    r"wäre\s+es\s+möglich|waere\s+es\s+moeglich)\b",
    re.I,
)
_NEGATION_RE = re.compile(
    r"\b(?:nicht(?!\s+(?:höher|hoeher|niedriger|mehr|weniger)\s+als\b)|"
    r"kein\w*|niemals|keinesfalls|auf\s+keinen\s+fall)\b",
    re.I,
)
_COMMAND_RE = re.compile(
    r"\b(?:mach|mache|schalt|schalte|einschalt|ausschalt|stell|stelle|setz|setze|fahr|fahre|"
    r"öffn|oeffn|schließ|schliess|start|aktivier|deaktivier|regel|regle|zeig|zeige|"
    r"lass|sorge|pause|pausier|spiel|weiterspiel|stopp|schick|schicke|"
    r"hätte\s+gern|haette\s+gern|möchte|moechte)\w*\b",
    re.I,
)
_ELLIPTICAL_COMMAND_RE = re.compile(
    r"\b(?:licht|lampe|leuchte|beleuchtung|roll(?:laden|läden|aden|äden)|rollo|jalousie|"
    r"ventilator|lüfter|heizung|thermostat|schalter|steckdose)\w*\b.*"
    r"\b(?:an|aus|ein|hoch|runter|herunter|offen|geschlossen)\b",
    re.I,
)
_TRIGGER_CUE_RE = re.compile(r"\b(?P<cue>wenn|sobald|falls)\b", re.I)
_CONDITION_CUE_RE = re.compile(r"\b(?P<cue>nur\s+wenn|sofern)\b", re.I)


def _modality(text: str) -> Modality:
    if _HYPOTHETICAL_RE.search(text):
        return Modality.HYPOTHETICAL
    if _UNCERTAIN_RE.search(text):
        return Modality.UNCERTAIN
    if _WISH_RE.search(text):
        return Modality.WISH
    if _POLITE_RE.search(text):
        return Modality.POLITE
    return Modality.DIRECT


def _clauses(text: str, speech_act: SpeechAct) -> tuple[MeaningClause, ...]:
    if speech_act is not SpeechAct.AUTOMATION:
        return (MeaningClause(text, ClauseRole.MAIN),)
    condition = _CONDITION_CUE_RE.search(text)
    trigger = _TRIGGER_CUE_RE.search(text)
    cue = condition or trigger
    if cue is None:
        return (MeaningClause(text, ClauseRole.MAIN),)
    before = text[: cue.start()].strip(" ,")
    after = text[cue.end() :].strip(" ,")
    dependent_role = ClauseRole.CONDITION if condition is not None else ClauseRole.TRIGGER
    # This is intentionally only a role-preserving first split. Existing
    # automation parsers still determine the exact trigger/action boundary.
    clauses: list[MeaningClause] = []
    if before:
        clauses.append(MeaningClause(before, ClauseRole.ACTION))
    if after:
        clauses.append(MeaningClause(after, dependent_role, cue.group("cue")))
    return tuple(clauses) or (MeaningClause(text, ClauseRole.MAIN),)


def analyse_utterance(text: str) -> SemanticUtterance:
    """Return the deterministic discourse/safety shape of ``text``."""
    normalized = normalize(text)
    if _CONFIRMATION_RE.fullmatch(normalized):
        speech_act = SpeechAct.CONFIRMATION
    elif _CORRECTION_RE.search(normalized):
        speech_act = SpeechAct.CORRECTION
    elif _META_AUTOMATION_QUERY_RE.search(normalized):
        speech_act = SpeechAct.QUERY
    elif _AUTOMATION_RE.search(normalized):
        speech_act = SpeechAct.AUTOMATION
    # A polite question that contains an executable operation is still a
    # command ("Kannst du das Licht einschalten?").  The generic question
    # shape is evaluated afterwards.  "Kann man ...?" remains an
    # informational question and must never execute anything.
    elif (
        _COMMAND_RE.search(normalized) or _ELLIPTICAL_COMMAND_RE.search(normalized)
    ) and not _INFORMATIONAL_CAN_RE.search(normalized):
        speech_act = SpeechAct.COMMAND
    elif _QUERY_REQUEST_RE.search(normalized) or _QUESTION_RE.search(normalized):
        speech_act = SpeechAct.QUERY
    else:
        speech_act = SpeechAct.STATEMENT
    return SemanticUtterance(
        source_text=text,
        normalized_text=normalized,
        speech_act=speech_act,
        # Natural-shell normalization intentionally removes constructions
        # such as "ich hätte gerne".  Modality is discourse information, so
        # classify it from both original and normalized text.
        modality=_modality(f"{text} {normalized}"),
        polarity=(Polarity.NEGATIVE if _NEGATION_RE.search(normalized) else Polarity.POSITIVE),
        clauses=_clauses(normalized, speech_act),
    )
