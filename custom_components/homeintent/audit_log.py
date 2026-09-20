"""Privacy-minimised bounded execution history for spoken diagnostics."""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuditEntry:
    timestamp: datetime
    actor: str
    domain: str
    service: str
    entity_ids: tuple[str, ...]


class AuditTrail:
    def __init__(self, limit: int = 250) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=limit)

    def record(self, now: datetime, user_id: str | None, plan) -> None:
        actor = (
            hashlib.sha256(user_id.encode()).hexdigest()[:10]
            if user_id else "voice"
        )
        raw_ids = plan.entity_id
        entity_ids = (raw_ids,) if isinstance(raw_ids, str) else tuple(raw_ids)
        self._entries.append(AuditEntry(
            now, actor, plan.domain, plan.service, entity_ids,
        ))

    def today(self, now: datetime) -> tuple[AuditEntry, ...]:
        return tuple(entry for entry in self._entries if entry.timestamp.date() == now.date())


def render_today(entries: tuple[AuditEntry, ...]) -> str:
    if not entries:
        return "Heute wurde noch nichts durch HomeIntent ausgeführt."
    recent = entries[-10:]
    parts = [
        f"{entry.timestamp:%H:%M} Uhr {entry.domain}.{entry.service} für "
        + ", ".join(entry.entity_ids)
        for entry in recent
    ]
    prefix = f"Heute wurden {len(entries)} Aktionen ausgeführt. "
    if len(entries) > len(recent):
        prefix += "Die letzten zehn sind: "
    return prefix + "; ".join(parts) + "."
