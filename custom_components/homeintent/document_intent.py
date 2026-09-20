"""Explicit read-only document search meaning after LanguageDocument."""

from __future__ import annotations

import re

from .nlu.language_frontend import LanguageDocument


_SEARCH_RE = re.compile(
    r"\b(?:suche|finde)\s+(?:bitte\s+)?(?:in\s+)?(?:meinen\s+|den\s+)?"
    r"(?:lokalen\s+)?dokumenten\s+(?:nach\s+)?(?P<query>.+)$",
    re.IGNORECASE,
)


def interpret_document_search(document: LanguageDocument) -> str | None:
    match = _SEARCH_RE.search(document.normalized_text.strip().rstrip(".?!"))
    if match is None:
        return None
    query = match.group("query").strip()
    return query if len(query) >= 2 else None
