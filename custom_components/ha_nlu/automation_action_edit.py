"""Language and selection helpers for trigger-preserving action edits."""

from __future__ import annotations

import re

from .automation_summary import AutomationSummary, CREATED_BY_HOMEINTENT
from .entities import normalize_for_compare


_EDIT_RE = re.compile(
    r"\b(?:ändere|aendere|ersetz\w*|füg\w*|fueg\w*|hinzufüg\w*|hinzufueg\w*|verschieb\w*)\b"
    r".*\b(?:nur\s+)?(?:die\s+|eine\s+|als\s+)?aktion\b",
    re.I,
)


def is_action_edit_request(text: str) -> bool:
    """Require explicit action-edit language; never infer destructive scope."""
    return _EDIT_RE.search(text) is not None


def action_edit_operation(text: str) -> str:
    """Return the explicit bounded action edit operation."""
    reorder = re.search(
        r"\bverschieb\w*\s+(?:die\s+)?(?P<source>erste|zweite|dritte|vierte|1\.?|2\.?|3\.?|4\.?)\s+aktion\s+"
        r"(?:an|auf)\s+(?:die\s+)?(?P<target>erste|zweite|dritte|vierte|letzte|1\.?|2\.?|3\.?|4\.?)\s+(?:stelle|position)",
        text, re.I,
    )
    if reorder:
        values = {"erste": 0, "zweite": 1, "dritte": 2, "vierte": 3,
                  "1": 0, "1.": 0, "2": 1, "2.": 1, "3": 2,
                  "3.": 2, "4": 3, "4.": 3, "letzte": -1}
        return f"reorder:{values[reorder.group('source').casefold()]}:{values[reorder.group('target').casefold()]}"
    return (
        "add"
        if re.search(r"\b(?:füg|fueg|hinzufüg|hinzufueg)", text, re.I)
        else "replace"
    )


def reordered_actions(
    actions: tuple[dict, ...], operation: str
) -> tuple[dict, ...] | None:
    if not operation.startswith("reorder:"):
        return None
    if any("delay" in action for action in actions):
        # A leading delay may belong to the trigger semantics ("N Minuten
        # nachdem …"). Its provenance is not encoded in HA YAML, so moving
        # around it would be unsafe.
        return None
    user_actions = [
        dict(action) for action in actions
        if not (
            action.get("action") in {
                "ha_nlu.delete_automation", "ha_nlu.record_automation_run"
            }
        )
    ]
    _, source_raw, target_raw = operation.split(":")
    source, target = int(source_raw), int(target_raw)
    if source < 0 or source >= len(user_actions):
        return None
    item = user_actions.pop(source)
    if target == -1:
        target = len(user_actions)
    if target < 0 or target > len(user_actions):
        return None
    user_actions.insert(target, item)
    return tuple(user_actions)


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
