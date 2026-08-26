"""Small deterministic German morphology view for semantic composition."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..entities import normalize_for_compare


@dataclass(frozen=True)
class GermanToken:
    surface: str
    normalized: str
    roles: frozenset[str] = frozenset()
    lemma: str | None = None
    grammatical_case: str | None = None
    position: int = 0


_TOKEN_RE = re.compile(r"[\wäöüß]+", re.I)
_PRONOUNS = frozenset({"er", "sie", "es", "ihn", "ihm", "ihr", "das", "dieser", "diese", "dieses"})
_QUANTIFIERS = frozenset({"alle", "kein", "keine", "beide", "jeder", "jede", "jedes", "mehrere", "einige"})
_CONNECTORS = frozenset({"und", "oder", "aber", "wenn", "falls", "sobald", "dann", "danach"})
_NEGATIONS = frozenset({"nicht", "kein", "keine", "nie", "niemals"})
_DATIVE_ARTICLES = frozenset({"dem", "einem", "einer"})
_ACCUSATIVE_ARTICLES = frozenset({"den", "einen", "eine", "das"})
_SEPARABLE_PARTICLES = frozenset({
    "an", "aus", "auf", "ab", "ein", "zu", "hoch", "runter", "herunter",
})


def _lightweight_lemma(token: str) -> str:
    """Return a conservative stem used for equality, never for execution."""
    irregular = {
        "faehrt": "fahren", "fuhr": "fahren", "lief": "laufen",
        "laeuft": "laufen", "schaltet": "schalten", "stellst": "stellen",
        "machst": "machen", "macht": "machen", "oeffnet": "oeffnen",
        "schliesst": "schliessen",
    }
    if token in irregular:
        return irregular[token]
    for suffix in ("est", "test", "en", "ern", "eln", "st", "t", "e"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[:-len(suffix)]
    return token


def analyse_german_morphology(text: str) -> tuple[GermanToken, ...]:
    """Expose stable token roles without guessing syntax or dependencies."""
    tokens: list[GermanToken] = []
    previous: str | None = None
    for index, match in enumerate(_TOKEN_RE.finditer(text)):
        surface = match.group(0)
        normalized = normalize_for_compare(surface)
        roles: set[str] = set()
        if normalized in _PRONOUNS:
            roles.add("reference")
        if normalized in _QUANTIFIERS:
            roles.add("quantifier")
        if normalized in _CONNECTORS:
            roles.add("connector")
        if normalized in _NEGATIONS:
            roles.add("negation")
        if normalized.isdigit():
            roles.add("number")
        if normalized in _SEPARABLE_PARTICLES:
            roles.add("separable_particle")
        grammatical_case = None
        if previous in _DATIVE_ARTICLES:
            grammatical_case = "dative"
        elif previous in _ACCUSATIVE_ARTICLES:
            grammatical_case = "accusative"
        tokens.append(GermanToken(
            surface, normalized, frozenset(roles), _lightweight_lemma(normalized),
            grammatical_case, index,
        ))
        previous = normalized
    return tuple(tokens)
