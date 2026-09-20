"""Closed language meanings for named, revalidated household procedures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .entities import normalize_for_compare
from .nlu.language_frontend import LanguageDocument


class ProcedureOperation(StrEnum):
    SAVE_ACTIVE_PLAN = "save_active_plan"
    LIST = "list"
    RUN = "run"
    FORGET = "forget"


@dataclass(frozen=True)
class ProcedureIntent:
    operation: ProcedureOperation
    name: str | None = None


_NAME = r"(?P<name>[\wäöüß]+(?:\s+[\wäöüß]+){0,3})"
_SAVE_RE = re.compile(
    rf"^\s*(?:speichere|merk\w*\s+dir)\s+(?:diesen|den)\s+plan\s+als\s+{_NAME}\s*$"
)
_RUN_RE = re.compile(
    r"^\s*(?:fuehre|starte)\s+(?:die\s+)?(?:prozedur|routine|szenario)\s+"
    r"(?P<name>[\wäöüß]+(?:\s+(?!aus\s*$)[\wäöüß]+){0,3})(?:\s+aus)?\s*$"
)
_FORGET_RE = re.compile(
    rf"^\s*(?:vergiss|loesche)\s+(?:die\s+)?(?:prozedur|routine|szenario)\s+{_NAME}\s*$"
)
_LIST_RE = re.compile(
    r"^\s*(?:welche|was\s+fuer)\s+(?:prozeduren|szenarien|benannte\s+routinen)\s+(?:kennst|hast)\s+du\s*\??\s*$"
)


def interpret_procedure_intent(document: LanguageDocument) -> ProcedureIntent | None:
    text = normalize_for_compare(document.normalized_text)
    if _LIST_RE.fullmatch(text):
        return ProcedureIntent(ProcedureOperation.LIST)
    for operation, pattern in (
        (ProcedureOperation.SAVE_ACTIVE_PLAN, _SAVE_RE),
        (ProcedureOperation.RUN, _RUN_RE),
        (ProcedureOperation.FORGET, _FORGET_RE),
    ):
        match = pattern.fullmatch(text)
        if match is not None:
            return ProcedureIntent(operation, match.group("name").strip())
    return None


__all__ = (
    "ProcedureIntent",
    "ProcedureOperation",
    "interpret_procedure_intent",
)
