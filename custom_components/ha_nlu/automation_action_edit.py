"""Language and selection helpers for trigger-preserving action edits."""

from __future__ import annotations

import re

from .automation_summary import AutomationSummary, CREATED_BY_HOMEINTENT
from .entities import normalize_for_compare


_EDIT_RE = re.compile(
    r"\b(?:ändere|aendere|ersetz\w*)\b.*\b(?:nur\s+)?(?:die\s+)?aktion\b",
    re.I,
)


def is_action_edit_request(text: str) -> bool:
    """Require explicit action-edit language; never infer destructive scope."""
    return _EDIT_RE.search(text) is not None


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
    return matched[0] if len(matched) == 1 else None
