"""Language model for safe trigger/condition edits of HomeIntent automations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class AutomationEditSection(Enum):
    TRIGGERS = auto()
    CONDITIONS = auto()


class AutomationEditOperation(Enum):
    REPLACE = auto()
    ADD = auto()
    CLEAR = auto()


@dataclass(frozen=True)
class AutomationStructureEditRequest:
    section: AutomationEditSection
    operation: AutomationEditOperation
    payload: str | None = None


_SECTION_RE = re.compile(
    r"\b(?P<trigger>auslöser|ausloeser|trigger)|(?P<condition>bedingung(?:en)?)\b",
    re.IGNORECASE,
)
_EDIT_RE = re.compile(
    r"\b(?:änder(?:e|n|t)?|aender(?:e|n|t)?|ersetz(?:e|en|t)?|"
    r"füg(?:e|en|t)?|fueg(?:e|en|t)?|hinzufüg(?:e|en|t)?|hinzufueg(?:e|en|t)?|"
    r"entfern(?:e|en|t)?|lösch(?:e|en|t)?|loesch(?:e|en|t)?)\b",
    re.IGNORECASE,
)


def parse_automation_structure_edit(text: str) -> AutomationStructureEditRequest | None:
    section_match = _SECTION_RE.search(text)
    if section_match is None or _EDIT_RE.search(text) is None:
        return None
    section = (
        AutomationEditSection.TRIGGERS
        if section_match.group("trigger")
        else AutomationEditSection.CONDITIONS
    )
    lowered = text.casefold()
    if re.search(r"\b(?:entfern|lösch|loesch)", lowered):
        if section is not AutomationEditSection.CONDITIONS or not re.search(r"\balle\w*\b", lowered):
            return None  # Never guess which one of several structural nodes to delete.
        return AutomationStructureEditRequest(section, AutomationEditOperation.CLEAR)
    operation = (
        AutomationEditOperation.ADD
        if re.search(r"\b(?:füg|fueg|hinzufüg|hinzufueg)", lowered)
        else AutomationEditOperation.REPLACE
    )
    payload: str | None = None
    if operation is AutomationEditOperation.REPLACE:
        split = list(re.finditer(r"\s+(?:auf|durch|zu)\s+", text, re.IGNORECASE))
        if split:
            payload = text[split[-1].end():].strip(" .,!?") or None
    else:
        tail = text[section_match.end():]
        tail = re.sub(r"\bhinzu(?:fügen|fuegen)?\b\s*$", "", tail, flags=re.IGNORECASE)
        marker = re.search(r"\b(?:dass|wenn|sobald|falls)\b", tail, re.IGNORECASE)
        if marker:
            payload = tail[marker.start():].strip(" .,!?") or None
    return AutomationStructureEditRequest(section, operation, payload)
