"""Deterministic parsing and read-only resolution for automation management."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from .automation_summary import AutomationSummary, CREATED_BY_HOMEINTENT
from .entities import EntitySnapshot, ResolveStatus, resolve_entity


class AutomationManagementKind(Enum):
    LIST_HOMEINTENT = auto()
    LIST_SCHEDULED = auto()
    WHEN = auto()
    RESCHEDULE = auto()
    CLEAN_EXPIRED = auto()
    SET_MAX_RUNS = auto()


@dataclass(frozen=True)
class AutomationManagementRequest:
    kind: AutomationManagementKind
    entity_name: str | None = None
    hour: int | None = None
    minute: int = 0
    max_runs: int | None = None


@dataclass(frozen=True)
class AutomationManagementSelection:
    request: AutomationManagementRequest
    automations: tuple[AutomationSummary, ...]
    entity: EntitySnapshot | None = None
    error_text: str | None = None


_RESCHEDULE_RE = re.compile(
    r"\bverschieb\w*\s+(?:den|die)\s+(?:auftrag|automation)"
    r"(?:\s+für\s+(?P<name>.+?))?\s+auf\s+(?P<hour>\d{1,2})"
    r"(?::(?P<minute>\d{1,2}))?\s*uhr\b",
    re.IGNORECASE,
)
_WHEN_RE = re.compile(
    r"\bwann\s+wird\s+(?P<name>.+?)\s+"
    r"(?:gefahren|geschaltet|eingeschaltet|ausgeschaltet|gestartet|ausgeführt)\b",
    re.IGNORECASE,
)
_SET_MAX_RUNS_RE = re.compile(
    r"\bwiederhol\w*\s+(?:die\s+)?automation"
    r"(?:\s+für\s+(?P<name>.+?))?\s+nur\s+"
    r"(?P<count>zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|[2-9]|10)\s*mal\b",
    re.IGNORECASE,
)
_RUN_COUNTS = {
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
}


def parse_automation_management(text: str) -> AutomationManagementRequest | None:
    """Recognize the bounded management vocabulary without fuzzy matching."""
    normalized = re.sub(r"[?.!]", "", text).strip()
    if re.search(r"\blösch\w*\s+alle\s+abgelaufenen\b", normalized, re.IGNORECASE):
        return AutomationManagementRequest(AutomationManagementKind.CLEAN_EXPIRED)
    match = _SET_MAX_RUNS_RE.search(normalized)
    if match is not None:
        raw_count = match.group("count").casefold()
        return AutomationManagementRequest(
            AutomationManagementKind.SET_MAX_RUNS,
            entity_name=match.group("name"),
            max_runs=int(raw_count) if raw_count.isdigit() else _RUN_COUNTS[raw_count],
        )
    match = _RESCHEDULE_RE.search(normalized)
    if match is not None:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return AutomationManagementRequest(
                AutomationManagementKind.RESCHEDULE,
                entity_name=match.group("name"),
                hour=hour,
                minute=minute,
            )
        return None
    match = _WHEN_RE.search(normalized)
    if match is not None:
        return AutomationManagementRequest(
            AutomationManagementKind.WHEN,
            entity_name=match.group("name"),
        )
    if re.search(
        r"\b(?:welche|zeige)\b.*\bhomeintent[- ]automationen\b",
        normalized,
        re.IGNORECASE,
    ) or re.search(
        r"\bzeige\s+nur\s+homeintent\s+automationen\b",
        normalized,
        re.IGNORECASE,
    ):
        return AutomationManagementRequest(AutomationManagementKind.LIST_HOMEINTENT)
    if re.search(
        r"\bwelche\s+(?:einmaligen\s+)?(?:aufträge|automationen)\s+sind\s+(?:noch\s+)?geplant\b",
        normalized,
        re.IGNORECASE,
    ):
        return AutomationManagementRequest(AutomationManagementKind.LIST_SCHEDULED)
    return None


def select_automation_management(
    request: AutomationManagementRequest,
    entities: list[EntitySnapshot],
    automations: tuple[AutomationSummary, ...],
    now: datetime | None = None,
) -> AutomationManagementSelection:
    """Apply HomeIntent/schedule/entity filters and preserve ambiguity."""
    homeintent = tuple(
        automation
        for automation in automations
        if automation.created_by == CREATED_BY_HOMEINTENT
    )
    scheduled = tuple(
        automation
        for automation in homeintent
        if automation.once and automation.scheduled_for is not None
        and (
            now is None
            or _comparable_target(automation.scheduled_for, now) > now
        )
    )
    if request.kind is AutomationManagementKind.LIST_HOMEINTENT:
        return AutomationManagementSelection(request, homeintent)
    if request.kind in (
        AutomationManagementKind.LIST_SCHEDULED,
        AutomationManagementKind.CLEAN_EXPIRED,
    ):
        return AutomationManagementSelection(request, scheduled)

    candidates = (
        tuple(automation for automation in homeintent if not automation.once)
        if request.kind is AutomationManagementKind.SET_MAX_RUNS
        else scheduled
    )
    if request.entity_name:
        resolved = resolve_entity(request.entity_name.strip(), entities)
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return AutomationManagementSelection(
                request,
                (),
                error_text=(
                    "Das Gerät ist nicht eindeutig. Bitte nenne den vollständigen Gerätenamen."
                    if resolved.status is ResolveStatus.AMBIGUOUS
                    else "Ich habe das genannte Gerät nicht gefunden."
                ),
            )
        matched = tuple(
            automation
            for automation in candidates
            if resolved.entity.entity_id in automation.referenced_entity_ids
        )
        return AutomationManagementSelection(request, matched, entity=resolved.entity)
    return AutomationManagementSelection(request, candidates)


def _comparable_target(value: str, now: datetime) -> datetime:
    target = datetime.fromisoformat(value)
    if target.tzinfo is None and now.tzinfo is not None:
        return target.replace(tzinfo=now.tzinfo)
    if target.tzinfo is not None and now.tzinfo is None:
        return target.replace(tzinfo=None)
    return target


def format_scheduled_time(value: str) -> str:
    target = datetime.fromisoformat(value)
    return target.strftime("%d.%m.%Y um %H:%M Uhr")
