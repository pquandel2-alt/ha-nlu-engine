"""Controlled German response planning and surface realization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .nlu.german_morphology import dative_location_phrase, sentence_initial


class DialogAct(StrEnum):
    INFORM = "inform"
    ASK = "ask"
    CONFIRM = "confirm"
    WARN = "warn"
    EXPLAIN = "explain"
    REJECT = "reject"


class PersonaStyle(StrEnum):
    NEUTRAL = "neutral"
    PRECISE = "precise"
    JARVIS = "jarvis"


class Urgency(StrEnum):
    NORMAL = "normal"
    IMPORTANT = "important"
    CRITICAL = "critical"


class QueryAnswerKind(StrEnum):
    """Supported semantic shapes for deterministic query answers."""

    NOT_UNDERSTOOD = "not_understood"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    FILTERED_LIST = "filtered_list"
    COUNT = "count"
    AREA_LIST = "area_list"
    DEVICE_LIST = "device_list"
    AUTOMATION_LIST = "automation_list"
    AUTOMATION_RELATION = "automation_relation"
    EXISTS = "exists"
    ALL = "all"
    NONE = "none"
    LOCATIONS = "locations"
    SINGLE = "single"
    UNKNOWN_SINGLE = "unknown_single"
    UNDETERMINED_SINGLE = "undetermined_single"


@dataclass(frozen=True)
class QueryResponsePlan:
    """Grounded facts needed to realize one query answer.

    Fields contain registry-backed names or controlled vocabulary selected by
    the query generator. No field is interpreted as a service instruction.
    """

    kind: QueryAnswerKind
    noun_plural: str = "Geräte"
    noun_singular: str = "Gerät"
    names: tuple[str, ...] = ()
    area_names: tuple[str, ...] = ()
    state: str | None = None
    matched: bool = False
    causal: bool = False
    current_state: str | None = None


CRITICAL_CATEGORIES = frozenset(
    {"smoke", "carbon_monoxide", "water", "intrusion", "alarm", "medical", "safety_alarm"}
)


@dataclass(frozen=True)
class ResponsePlan:
    dialog_act: DialogAct
    result: str | None = None
    urgency: Urgency = Urgency.NORMAL
    safety_level: str = "low"
    concise: bool = True
    address: str | None = None
    operating_mode: str = "normal"
    banter_level: int = 0
    tts_suitable: bool = True
    category: str | None = None
    facts: tuple[str, ...] = ()
    query: QueryResponsePlan | None = None


def _join_names(names: tuple[str, ...]) -> str:
    """Join already-grounded names as a natural German list."""

    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} und {names[1]}"
    return ", ".join(names[:-1]) + f" und {names[-1]}"


class GermanResponseRealizer:
    """Realize only supplied results and grounded facts."""

    def realize(
        self,
        plan: ResponsePlan,
        *,
        style: PersonaStyle = PersonaStyle.NEUTRAL,
        grounded_facts: Mapping[str, str] | None = None,
    ) -> str:
        critical = (
            plan.urgency is Urgency.CRITICAL
            or plan.category in CRITICAL_CATEGORIES
            or plan.safety_level == "critical"
        )
        result = (
            self._realize_query(plan.query)
            if plan.query is not None
            else (plan.result or "").strip()
        )
        if not result:
            raise ValueError("Ein Antwortplan benötigt ein fachliches Ergebnis")
        if critical:
            # Critical wording is deliberately style-independent and banter-free.
            return result[:350]
        prefix = ""
        if plan.address:
            prefix = f"{plan.address}, "
        if style is PersonaStyle.PRECISE:
            text = f"{prefix}{result}"
        elif style is PersonaStyle.JARVIS and plan.banter_level > 0:
            # Fixed variants add tone but never a fact or a safety judgment.
            text = f"{prefix}{result} Wie gewünscht."
        else:
            text = f"{prefix}{result}"
        if plan.dialog_act is DialogAct.EXPLAIN and plan.facts:
            evidence = grounded_facts or {}
            grounded = [evidence[key] for key in plan.facts if key in evidence]
            if grounded:
                if plan.tts_suitable and len(grounded) > 3:
                    grounded = grounded[:3]
                    grounded.append("Weitere Details sind in Home Assistant sichtbar.")
                text += " Grundlage: " + "; ".join(grounded)
        return text

    @staticmethod
    def _realize_query(query: QueryResponsePlan) -> str:
        """Realize a query solely from its structured, grounded fields."""

        kind = query.kind
        noun = query.noun_plural
        names = query.names
        state = query.state
        if kind is QueryAnswerKind.NOT_UNDERSTOOD:
            return "Das habe ich nicht verstanden."
        if kind is QueryAnswerKind.NOT_FOUND:
            return f"Ich konnte keine passenden {noun} finden."
        if kind is QueryAnswerKind.AMBIGUOUS:
            return f"Ich habe mehrere passende {noun} gefunden."
        if kind is QueryAnswerKind.FILTERED_LIST:
            if not names:
                return f"Es sind keine {noun} {state}."
            verb = "ist" if len(names) == 1 else "sind"
            return f"{_join_names(names)} {verb} {state}."
        if kind is QueryAnswerKind.COUNT:
            count = len(names)
            count_noun = query.noun_singular if count == 1 else noun
            verb = "ist" if count == 1 else "sind"
            return f"{count} {count_noun} {verb} {state}."
        if kind is QueryAnswerKind.AREA_LIST:
            location = (
                f" {dative_location_phrase(query.area_names[0])}"
                if query.area_names
                else ""
            )
            if not names:
                return f"Keine {noun} gefunden{location}."
            verb = "ist" if len(names) == 1 else "sind"
            return f"{_join_names(names)} {verb}{location}."
        if kind is QueryAnswerKind.DEVICE_LIST:
            location = dative_location_phrase(query.area_names[0])
            if not names:
                suffix = f" {state}" if state is not None else " bekannt"
                return f"{sentence_initial(location)} sind keine Geräte{suffix}."
            if state is not None:
                verb = "ist" if len(names) == 1 else "sind"
                return f"{_join_names(names)} {verb} {state}."
            verb = "ist" if len(names) == 1 else "sind"
            return f"{_join_names(names)} {verb} {location}."
        if kind is QueryAnswerKind.AUTOMATION_LIST:
            if not names:
                return "Es sind keine Automationen vorhanden."
            return f"Es gibt folgende Automationen: {_join_names(names)}."
        if kind is QueryAnswerKind.AUTOMATION_RELATION:
            entity_name = query.area_names[0]
            if not names:
                relation = "beeinflussen könnte" if query.causal else "steuert"
                return f"Ich habe keine Automation gefunden, die {entity_name} {relation}."
            joined = _join_names(names)
            if query.causal:
                noun = "Automationen" if len(names) > 1 else "Automation"
                return (
                    f"{entity_name} könnte durch folgende {noun} "
                    f"beeinflusst werden: {joined}."
                )
            qualifier = "folgenden Automationen" if len(names) > 1 else "folgender Automation"
            return f"{entity_name} wird von {qualifier} gesteuert: {joined}."
        if kind is QueryAnswerKind.EXISTS:
            if not names:
                return f"Nein, es gibt keine {noun}."
            return f"Ja, es gibt {len(names)} {noun}."
        if kind is QueryAnswerKind.ALL:
            if not names:
                return f"Ich habe keine {noun} gefunden."
            prefix = "Ja, alle" if query.matched else "Nein, nicht alle"
            return f"{prefix} {noun} sind {state}."
        if kind is QueryAnswerKind.NONE:
            if not names:
                return f"Ich habe keine {noun} gefunden."
            if query.matched:
                return f"Ja, es sind keine {noun} {state}."
            return f"Nein, mindestens eines der {noun} ist {state}."
        if kind is QueryAnswerKind.LOCATIONS:
            if state is None:
                if not query.area_names:
                    return f"Ich kenne für {noun} keinen Raum."
                locations = tuple(
                    dative_location_phrase(area) for area in query.area_names
                )
                return f"{noun} befinden sich {_join_names(locations)}."
            if not query.area_names:
                return f"In keinem bekannten Raum sind {noun} {state}."
            locations = tuple(dative_location_phrase(area) for area in query.area_names)
            return f"{sentence_initial(_join_names(locations))} sind {noun} {state}."
        if kind is QueryAnswerKind.UNKNOWN_SINGLE:
            return f"Der Zustand von {names[0]} ist unbekannt."
        if kind is QueryAnswerKind.UNDETERMINED_SINGLE:
            return (
                f"Ob {names[0]} {state} ist, kann ich aus dem aktuellen Zustand "
                f"„{query.current_state}“ nicht sicher ableiten."
            )
        if kind is QueryAnswerKind.SINGLE:
            if state is None:
                return f"{names[0]} ist {query.current_state}."
            negation = "" if query.matched else "nicht "
            prefix = "Ja" if query.matched else "Nein"
            return f"{prefix}, {names[0]} ist {negation}{state}."
        raise ValueError(f"Nicht unterstützte Query-Antwortform: {kind}")
