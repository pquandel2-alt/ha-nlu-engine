"""Deterministic multi-turn wizard for building one automation AST."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

from .nlu.action_model import ActionGroup, ActionModel
from .nlu.automation_model import TriggerModel
from .nlu.condition_model import ConditionNode


class AutomationWizardStage(Enum):
    TRIGGER = auto()
    CONDITION_DECISION = auto()
    CONDITION = auto()
    ACTION = auto()
    LIFETIME = auto()


@dataclass(frozen=True)
class AutomationWizardState:
    stage: AutomationWizardStage = AutomationWizardStage.TRIGGER
    trigger: TriggerModel | None = None
    condition: ConditionNode | None = None
    actions: tuple[ActionModel | ActionGroup, ...] = ()
    source_parts: tuple[str, ...] = ()


_START_RE = re.compile(
    r"^\s*(?:(?:bitte|kannst\s+du)\s+)?(?:erstelle|erstell|baue|bau|lege|leg)"
    r"\s+(?:mir\s+)?(?:eine\s+)?(?:neue\s+)?automation\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def starts_automation_wizard(text: str) -> bool:
    return _START_RE.match(text) is not None


def parse_lifetime(text: str) -> tuple[bool, int | None] | None:
    lowered = text.casefold().strip(" .!?")
    if re.search(r"\b(?:dauerhaft|immer|unbegrenzt|wiederkehrend)\b", lowered):
        return False, None
    if re.search(r"\b(?:einmal|einmalig|nur\s+einmal)\b", lowered):
        return True, None
    match = re.search(
        r"\b(?:nur\s+)?(zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|[2-9]|10)\s*mal\b",
        lowered,
    )
    if match is None:
        return None
    words = {
        "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
        "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    }
    raw = match.group(1)
    return False, int(raw) if raw.isdigit() else words[raw]
