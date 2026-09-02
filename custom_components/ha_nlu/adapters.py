"""Optional, read-only adapters producing typed evidence only."""

from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Mapping


class EvidenceQuality(StrEnum):
    DIRECT = "direct"
    REPORTED = "reported"
    ESTIMATE = "estimate"


@dataclass(frozen=True)
class AdapterEvidence:
    evidence_id: str
    source: str
    kind: str
    observed_at: datetime
    content: Mapping[str, object]
    quality: EvidenceQuality


class FrigateMetadataAdapter:
    """Consume existing Frigate/MQTT metadata, never raw image meaning."""

    ALLOWED_LABELS = frozenset({"person", "package", "car", "dog", "cat"})

    def normalize(self, payload: Mapping[str, object]) -> AdapterEvidence | None:
        event_id = payload.get("id")
        label = payload.get("label")
        camera = payload.get("camera")
        score = payload.get("score")
        if not isinstance(event_id, str) or not isinstance(label, str):
            return None
        if label.casefold() not in self.ALLOWED_LABELS or not isinstance(camera, str):
            return None
        confidence = float(score) if isinstance(score, (int, float)) else 0.0
        return AdapterEvidence(
            f"frigate:{event_id}",
            "frigate_metadata",
            label.casefold(),
            datetime.now(timezone.utc),
            {"camera_id": camera, "confidence": max(0.0, min(1.0, confidence))},
            EvidenceQuality.ESTIMATE,
        )


@dataclass(frozen=True)
class DocumentHit:
    document_id: str
    relative_path: str
    title: str
    excerpt: str


class LocalDocumentIndex:
    """Allowlisted local TXT/Markdown index with SQLite FTS5 and path guards."""

    ALLOWED_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".pdf"})

    def __init__(
        self,
        root: str | Path,
        database: str | Path,
        *,
        enabled: bool = False,
        max_file_bytes: int = 2_000_000,
        max_files: int = 1000,
    ) -> None:
        self.root = Path(root).resolve()
        self.database = Path(database)
        self.enabled = enabled
        self.max_file_bytes = max(1024, max_file_bytes)
        self.max_files = max(1, max_files)

    async def async_reindex(self) -> int:
        if not self.enabled:
            return 0
        return await asyncio.to_thread(self._reindex)

    async def async_search(self, query: str, *, limit: int = 5) -> tuple[DocumentHit, ...]:
        if not self.enabled:
            return ()
        cleaned = " ".join(token for token in query.split() if token.isalnum())
        if not cleaned:
            return ()
        return await asyncio.to_thread(self._search, cleaned, max(1, min(20, limit)))

    def _documents(self) -> Iterable[Path]:
        if not self.root.is_dir():
            return ()
        selected: list[Path] = []
        for candidate in sorted(self.root.rglob("*")):
            if len(selected) >= self.max_files:
                break
            resolved = candidate.resolve()
            if self.root not in resolved.parents or not resolved.is_file():
                continue
            if resolved.suffix.casefold() not in self.ALLOWED_SUFFIXES:
                continue
            if resolved.stat().st_size > self.max_file_bytes:
                continue
            selected.append(resolved)
        return tuple(selected)

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(document_id UNINDEXED, relative_path UNINDEXED, title, body)"
        )
        return connection

    def _reindex(self) -> int:
        rows: list[tuple[str, str, str, str]] = []
        for path in self._documents():
            raw = path.read_bytes()
            if path.suffix.casefold() == ".pdf":
                text = _extract_pdf_text(raw, max_output=self.max_file_bytes * 4)
                if not text:
                    continue
            else:
                if b"\x00" in raw:
                    continue
                text = raw.decode("utf-8", errors="replace")
            relative = str(path.relative_to(self.root))
            document_id = "doc_" + hashlib.sha256(relative.encode()).hexdigest()[:20]
            title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.strip()), path.stem)
            rows.append((document_id, relative, title[:300], text))
        with self._connect() as connection:
            connection.execute("DELETE FROM documents")
            connection.executemany("INSERT INTO documents VALUES (?, ?, ?, ?)", rows)
        return len(rows)

    def _search(self, query: str, limit: int) -> tuple[DocumentHit, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document_id, relative_path, title, "
                "snippet(documents, 3, '[', ']', '…', 18) AS excerpt "
                "FROM documents WHERE documents MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            )
            return tuple(
                DocumentHit(
                    str(row["document_id"]),
                    str(row["relative_path"]),
                    str(row["title"]),
                    str(row["excerpt"]),
                )
                for row in rows
            )


class HomeAssistantSourceAdapter:
    """Label already structured HA data without adding interpretations."""

    ALLOWED_SOURCES = frozenset(
        {"calendar", "weather", "recorder", "logbook", "energy", "presence", "todo", "timer"}
    )

    def wrap(
        self,
        source: str,
        stable_id: str,
        content: Mapping[str, object],
        *,
        observed_at: datetime,
    ) -> AdapterEvidence:
        if source not in self.ALLOWED_SOURCES:
            raise ValueError("Nicht freigegebene Home-Assistant-Quelle")
        if observed_at.tzinfo is None:
            raise ValueError("Quellzeit benötigt eine Zeitzone")
        return AdapterEvidence(
            f"ha:{source}:{stable_id}",
            source,
            "structured_record",
            observed_at,
            dict(content),
            EvidenceQuality.DIRECT,
        )


_PDF_STREAM_RE = re.compile(rb"(?P<dict><<.{0,4096}?>>)[\r\n ]*stream\r?\n(?P<data>.*?)\r?\nendstream", re.S)
_PDF_TEXT_RE = re.compile(rb"\((?P<text>(?:\\.|[^\\)])*)\)\s*Tj|\[(?P<array>.*?)\]\s*TJ", re.S)
_PDF_ARRAY_STRING_RE = re.compile(rb"\((?P<text>(?:\\.|[^\\)])*)\)", re.S)


def _extract_pdf_text(raw: bytes, *, max_output: int) -> str:
    """Extract literal text operators from bounded, non-encrypted PDFs.

    This deliberately does not OCR images or claim meaning for scanned or
    encrypted documents. Unsupported encodings yield no indexed document.
    """
    if not raw.startswith(b"%PDF-") or b"/Encrypt" in raw:
        return ""
    chunks: list[str] = []
    total = 0
    for match in _PDF_STREAM_RE.finditer(raw):
        data = match.group("data")
        if b"/FlateDecode" in match.group("dict"):
            try:
                data = zlib.decompress(data)
            except zlib.error:
                continue
        if len(data) > max_output:
            continue
        for text_match in _PDF_TEXT_RE.finditer(data):
            literals = (
                (text_match.group("text"),)
                if text_match.group("text") is not None
                else tuple(
                    item.group("text")
                    for item in _PDF_ARRAY_STRING_RE.finditer(
                        text_match.group("array") or b""
                    )
                )
            )
            for literal in literals:
                decoded = _decode_pdf_literal(literal)
                if decoded:
                    chunks.append(decoded)
                    total += len(decoded)
                    if total >= max_output:
                        return " ".join(chunks)[:max_output]
    return " ".join(chunks)


def _decode_pdf_literal(value: bytes) -> str:
    value = re.sub(
        rb"\\([0-7]{1,3})",
        lambda match: bytes((int(match.group(1), 8),)),
        value,
    )
    replacements = {
        rb"\n": b"\n",
        rb"\r": b"\r",
        rb"\t": b"\t",
        rb"\(": b"(",
        rb"\)": b")",
        rb"\\": b"\\",
    }
    for escaped, replacement in replacements.items():
        value = value.replace(escaped, replacement)
    if value.startswith((b"\xfe\xff", b"\xff\xfe")):
        try:
            return value.decode("utf-16").strip()
        except UnicodeDecodeError:
            return ""
    return value.decode("latin-1", errors="ignore").strip()
