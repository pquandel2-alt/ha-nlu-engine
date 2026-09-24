"""Atomic, bounded and corruption-tolerant local ExperienceStore."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence, cast

from .experience import ExperienceRecord
from .learning_policy import LearningPolicy


SCHEMA_VERSION = 1


class ExperienceStore:
    def __init__(self, path: str | Path, policy: LearningPolicy) -> None:
        self.path = Path(path)
        self.policy = policy
        self._lock = asyncio.Lock()

    async def async_append(self, record: ExperienceRecord) -> bool:
        if record.timestamp.tzinfo is None:
            return False
        async with self._lock:
            records = await asyncio.to_thread(self._read)
            if any(item.experience_id == record.experience_id for item in records):
                return False
            cutoff = datetime.now(timezone.utc) - self.policy.retention
            kept = [item for item in records if item.timestamp >= cutoff]
            kept.append(record)
            await asyncio.to_thread(
                self._write, kept[-max(1, self.policy.experience_limit):]
            )
        return True

    async def async_extend(self, records: Sequence[ExperienceRecord]) -> int:
        appended = 0
        for record in records:
            appended += int(await self.async_append(record))
        return appended

    async def async_list(self) -> tuple[ExperienceRecord, ...]:
        return tuple(await asyncio.to_thread(self._read))

    async def async_forget_model_inputs(self, model_id: str) -> int:
        """Remove explicit model links, without broad person-history deletion."""
        marker = f"model:{model_id}"
        async with self._lock:
            records = await asyncio.to_thread(self._read)
            retained = [item for item in records if marker not in item.evidence]
            if len(retained) == len(records):
                return 0
            await asyncio.to_thread(self._write, retained)
            return len(records) - len(retained)

    def _read(self) -> list[ExperienceRecord]:
        try:
            raw: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        if not isinstance(raw, Mapping):
            return []
        document = cast(Mapping[str, object], raw)
        if document.get("schema_version") != SCHEMA_VERSION:
            return []
        values = document.get("experiences", ())
        if not isinstance(values, list):
            return []
        records: list[ExperienceRecord] = []
        for value in cast(list[object], values):
            if not isinstance(value, Mapping):
                continue
            try:
                records.append(ExperienceRecord.from_dict(cast(Mapping[str, object], value)))
            except (KeyError, TypeError, ValueError):
                continue
        return records

    def _write(self, records: Sequence[ExperienceRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".homeintent_experiences_", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "experiences": [item.to_dict() for item in records],
                    },
                    handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                )
                handle.flush()
                # Closing the same-directory temporary file before os.replace()
                # makes the JSON snapshot atomically visible.  Do not force a
                # synchronous device flush for every observation: learning is
                # advisory, and a per-sample fsync can block an otherwise
                # bounded GoalRun callback for hundreds of milliseconds on
                # virtualised Home Assistant storage.
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


__all__ = ("ExperienceStore", "SCHEMA_VERSION")
