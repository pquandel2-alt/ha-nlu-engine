"""Local, structured and revocable household memory backed by SQLite.

Only explicitly confirmed durable memories are accepted.  Working memory is
kept separately in RAM and intentionally disappears on restart.  SQLite work
is exposed through async methods so Home Assistant's event loop is never
blocked by file I/O.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Sequence

from .house_graph import ConfidenceClass, FactProvenance


SCHEMA_VERSION = 1


class MemoryKind(StrEnum):
    EPISODE = "episode"
    HOUSEHOLD_FACT = "household_fact"
    PREFERENCE = "preference"
    PROCEDURE = "procedure"
    DECISION = "decision"
    ROUTINE_GRANT = "routine_grant"


PERSONAL_KINDS = frozenset({MemoryKind.PREFERENCE, MemoryKind.ROUTINE_GRANT})


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    kind: MemoryKind
    content: Mapping[str, object]
    provenance: FactProvenance
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    person_id: str | None = None
    confidence: ConfidenceClass = ConfidenceClass.CONFIRMED
    deleted_at: datetime | None = None

    @property
    def active(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.deleted_at is None and (
            self.expires_at is None or self.expires_at > now
        )


@dataclass
class WorkingMemory:
    """Conversation-bound facts; never serialized or restored."""

    conversation_id: str
    facts: dict[str, object] = field(default_factory=lambda: _empty_facts())
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def remember(self, key: str, value: object) -> None:
        self.facts[key] = value
        self.last_updated = datetime.now(timezone.utc)

    def forget(self, key: str) -> None:
        self.facts.pop(key, None)
        self.last_updated = datetime.now(timezone.utc)


class MemoryStore:
    """Migration-aware memory store with controlled deletion and export."""

    def __init__(
        self,
        path: str | Path,
        *,
        enabled: bool = False,
        retention_days: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.retention_days = (
            max(0, retention_days) if isinstance(retention_days, int) else None
        )
        self._working: dict[str, WorkingMemory] = {}
        self._init_lock = asyncio.Lock()
        self._initialized = False

    def working(self, conversation_id: str) -> WorkingMemory:
        return self._working.setdefault(conversation_id, WorkingMemory(conversation_id))

    def clear_working(self, conversation_id: str | None = None) -> None:
        if conversation_id is None:
            self._working.clear()
        else:
            self._working.pop(conversation_id, None)

    async def async_initialize(self) -> None:
        if self._initialized or not self.enabled:
            return
        async with self._init_lock:
            if not self._initialized:
                await asyncio.to_thread(self._initialize)
                self._initialized = True

    async def async_remember(
        self,
        kind: MemoryKind,
        content: Mapping[str, object],
        *,
        provenance: FactProvenance,
        confirmed: bool,
        person_id: str | None = None,
        confidence: ConfidenceClass = ConfidenceClass.CONFIRMED,
        expires_at: datetime | None = None,
        memory_id: str | None = None,
    ) -> MemoryRecord:
        if not self.enabled:
            raise RuntimeError("Das dauerhafte Gedächtnis ist deaktiviert")
        if not confirmed:
            raise ValueError("Dauerhafte Erinnerungen benötigen eine Bestätigung")
        if kind in PERSONAL_KINDS and not person_id:
            raise ValueError("Persönliche Erinnerungen benötigen eine Person")
        encoded = _encode_content(content)
        await self.async_initialize()
        now = datetime.now(timezone.utc)
        normalized_expiry = _as_utc(expires_at)
        if normalized_expiry is None and self.retention_days is not None:
            normalized_expiry = now + timedelta(days=self.retention_days)
        record = MemoryRecord(
            memory_id or f"mem_{uuid.uuid4().hex}",
            kind,
            dict(content),
            provenance,
            now,
            now,
            normalized_expiry,
            person_id,
            confidence,
        )
        await asyncio.to_thread(self._upsert, record, encoded)
        return record

    async def async_list(
        self,
        *,
        person_id: str | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        include_deleted: bool = False,
    ) -> tuple[MemoryRecord, ...]:
        if not self.enabled:
            return ()
        await self.async_initialize()
        return await asyncio.to_thread(
            self._list, person_id, tuple(kinds or ()), include_deleted
        )

    async def async_correct(
        self,
        memory_id: str,
        content: Mapping[str, object],
        *,
        confirmed: bool,
    ) -> MemoryRecord | None:
        if not confirmed:
            raise ValueError("Eine dauerhafte Korrektur benötigt eine Bestätigung")
        _encode_content(content)
        existing = next(
            (item for item in await self.async_list(include_deleted=False) if item.memory_id == memory_id),
            None,
        )
        if existing is None:
            return None
        updated = MemoryRecord(
            existing.memory_id,
            existing.kind,
            dict(content),
            existing.provenance,
            existing.created_at,
            datetime.now(timezone.utc),
            existing.expires_at,
            existing.person_id,
            existing.confidence,
        )
        await asyncio.to_thread(self._upsert, updated, _encode_content(content))
        return updated

    async def async_forget(self, memory_id: str) -> bool:
        if not self.enabled:
            return False
        await self.async_initialize()
        return await asyncio.to_thread(self._soft_delete_ids, (memory_id,)) > 0

    async def async_forget_person(
        self, person_id: str, *, kinds: Sequence[MemoryKind] | None = None
    ) -> int:
        records = await self.async_list(person_id=person_id, kinds=kinds)
        return await asyncio.to_thread(
            self._soft_delete_ids, tuple(item.memory_id for item in records)
        )

    async def async_reset(self) -> int:
        if not self.enabled:
            return 0
        await self.async_initialize()
        records = await self.async_list()
        self.clear_working()
        return await asyncio.to_thread(
            self._soft_delete_ids, tuple(item.memory_id for item in records)
        )

    async def async_apply_retention(
        self, retention_days: Mapping[MemoryKind, int]
    ) -> int:
        """Expire records using per-kind policy; zero means delete immediately."""
        if not self.enabled:
            return 0
        await self.async_initialize()
        now = datetime.now(timezone.utc)
        records = await self.async_list()
        expired = tuple(
            record.memory_id
            for record in records
            if (
                record.expires_at is not None
                and record.expires_at <= now
            )
            or (
                record.kind in retention_days
                and record.created_at
                + timedelta(days=max(0, retention_days[record.kind]))
                <= now
            )
        )
        return await asyncio.to_thread(self._soft_delete_ids, expired)

    async def async_redacted_export(self) -> dict[str, object]:
        records = await self.async_list()
        counts: dict[str, int] = {}
        sources: dict[str, int] = {}
        for record in records:
            counts[record.kind.value] = counts.get(record.kind.value, 0) + 1
            sources[record.provenance.value] = sources.get(record.provenance.value, 0) + 1
        return {
            "schema_version": SCHEMA_VERSION,
            "record_counts": counts,
            "provenance_counts": sources,
            "contains_transcripts": False,
            "person_ids_included": False,
            "content_included": False,
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("Die Gedächtnisdatenbank stammt aus einer neueren Version")
            if version < 1:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS memories (
                        memory_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        content_json TEXT NOT NULL,
                        provenance TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT,
                        person_id TEXT,
                        confidence TEXT NOT NULL,
                        deleted_at TEXT
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_person ON memories(person_id, deleted_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind, deleted_at)"
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _upsert(self, record: MemoryRecord, encoded: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    kind=excluded.kind, content_json=excluded.content_json,
                    provenance=excluded.provenance, updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at, person_id=excluded.person_id,
                    confidence=excluded.confidence, deleted_at=excluded.deleted_at""",
                (
                    record.memory_id,
                    record.kind.value,
                    encoded,
                    record.provenance.value,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.expires_at.isoformat() if record.expires_at else None,
                    record.person_id,
                    record.confidence.value,
                    record.deleted_at.isoformat() if record.deleted_at else None,
                ),
            )

    def _list(
        self,
        person_id: str | None,
        kinds: tuple[MemoryKind, ...],
        include_deleted: bool,
    ) -> tuple[MemoryRecord, ...]:
        clauses: list[str] = []
        parameters: list[object] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            parameters.append(datetime.now(timezone.utc).isoformat())
        if person_id is not None:
            clauses.append("person_id = ?")
            parameters.append(person_id)
        if kinds:
            clauses.append("kind IN (" + ",".join("?" for _ in kinds) + ")")
            parameters.extend(kind.value for kind in kinds)
        query = "SELECT * FROM memories"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, memory_id"
        with self._connect() as connection:
            return tuple(_record_from_row(row) for row in connection.execute(query, parameters))

    def _soft_delete_ids(self, memory_ids: tuple[str, ...]) -> int:
        if not memory_ids:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE memories SET content_json = '{}', person_id = NULL, "
                "expires_at = NULL, deleted_at = ?, updated_at = ? "
                "WHERE deleted_at IS NULL AND memory_id IN ("
                + ",".join("?" for _ in memory_ids)
                + ")",
                (now, now, *memory_ids),
            )
            deleted = cursor.rowcount
        with self._connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return deleted


def _encode_content(content: Mapping[str, object]) -> str:
    if not content:
        raise ValueError("Eine Erinnerung benötigt strukturierten Inhalt")
    if any(key.casefold() in {"transcript", "utterance", "raw_text"} for key in content):
        raise ValueError("Vollständige Sprachtranskripte werden nicht gespeichert")
    try:
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as err:
        raise ValueError("Erinnerungsinhalt muss JSON-strukturiert sein") from err
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("Erinnerungsinhalt ist zu groß")
    return encoded


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        memory_id=str(row["memory_id"]),
        kind=MemoryKind(str(row["kind"])),
        content=json.loads(str(row["content_json"])),
        provenance=FactProvenance(str(row["provenance"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        expires_at=(datetime.fromisoformat(str(row["expires_at"])) if row["expires_at"] else None),
        person_id=str(row["person_id"]) if row["person_id"] else None,
        confidence=ConfidenceClass(str(row["confidence"])),
        deleted_at=(datetime.fromisoformat(str(row["deleted_at"])) if row["deleted_at"] else None),
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("Zeitpunkte müssen eine Zeitzone besitzen")
    return value.astimezone(timezone.utc)


def _empty_facts() -> dict[str, object]:
    return {}
