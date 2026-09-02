"""Controlled German response planning and surface realization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


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


CRITICAL_CATEGORIES = frozenset(
    {"smoke", "carbon_monoxide", "water", "intrusion", "alarm", "medical", "safety_alarm"}
)


@dataclass(frozen=True)
class ResponsePlan:
    dialog_act: DialogAct
    result: str
    urgency: Urgency = Urgency.NORMAL
    safety_level: str = "low"
    concise: bool = True
    address: str | None = None
    operating_mode: str = "normal"
    banter_level: int = 0
    tts_suitable: bool = True
    category: str | None = None
    facts: tuple[str, ...] = ()


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
        result = plan.result.strip()
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
