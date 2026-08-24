"""Language and selection helpers for trigger-preserving action edits."""

from __future__ import annotations

import re

from .automation_summary import AutomationSummary, CREATED_BY_HOMEINTENT
from .entities import normalize_for_compare


_EDIT_RE = re.compile(
    r"\b(?:ändere|aendere|ersetz\w*|füg\w*|fueg\w*|hinzufüg\w*|hinzufueg\w*)\b"
    r".*\b(?:nur\s+)?(?:die\s+|eine\s+|als\s+)?aktion\b",
    re.I,
)


def is_action_edit_request(text: str) -> bool:
    """Require explicit action-edit language; never infer destructive scope."""
    return _EDIT_RE.search(text) is not None


def action_edit_operation(text: str) -> str:
    """Return the explicit bounded action edit operation."""
    return (
        "add"
        if re.search(r"\b(?:füg|fueg|hinzufüg|hinzufueg)", text, re.I)
        else "replace"
    )


def homeintent_candidates(
    automations: tuple[AutomationSummary, ...], text: str
) -> tuple[AutomationSummary, ...]:
    """Resolve a named alias/source when present, otherwise keep all choices."""
    candidates = tuple(
        item for item in automations if item.created_by == CREATED_BY_HOMEINTENT
    )
    spoken = normalize_for_compare(text)
    named = tuple(
        item
        for item in candidates
        if normalize_for_compare(item.alias) in spoken
        or (
            item.source_text is not None
            and normalize_for_compare(item.source_text) in spoken
        )
    )
    return named or candidates


def select_candidate_reply(
    text: str, candidates: tuple[AutomationSummary, ...]
) -> AutomationSummary | None:
    spoken = normalize_for_compare(text)
    matched = [
        item
        for item in candidates
        if normalize_for_compare(item.alias) in spoken
        or spoken in normalize_for_compare(item.alias)
    ]
    if len(matched) == 1:
        return matched[0]
    ordinal = re.search(
        r"\b(?:die\s+)?(erste|zweite|dritte|1\.?|2\.?|3\.?)\b", text, re.I
    )
    if ordinal is not None:
        indexes = {
            "erste": 0, "1": 0, "1.": 0,
            "zweite": 1, "2": 1, "2.": 1,
            "dritte": 2, "3": 2, "3.": 2,
        }
        index = indexes[ordinal.group(1).casefold()]
        if index < len(candidates):
            return candidates[index]
    return None
