"""Shared German strength modifiers for relative property adjustments."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .primitives import SemanticDegree


@dataclass(frozen=True)
class DegreeAdjustment:
    text: str
    degree: SemanticDegree | None
    light_percent: int
    climate_degrees: float


_DEGREES = (
    (re.compile(r"\b(?:etwas|ein\s+bisschen|leicht)\b", re.I), SemanticDegree.SLIGHT, 5, 0.5),
    (re.compile(r"\b(?:deutlich|merklich)\b", re.I), SemanticDegree.MODERATE, 15, 1.0),
    (re.compile(r"\b(?:viel|stark)\b", re.I), SemanticDegree.LARGE, 25, 2.0),
)


def extract_degree(text: str) -> DegreeAdjustment:
    """Remove exactly one unambiguous degree modifier and return its steps."""
    matches = [entry for entry in _DEGREES if entry[0].search(text)]
    if len(matches) != 1:
        return DegreeAdjustment(text, None, 10, 1.0)
    pattern, degree, light_percent, climate_degrees = matches[0]
    cleaned = re.sub(r"\s+", " ", pattern.sub(" ", text)).strip()
    return DegreeAdjustment(cleaned, degree, light_percent, climate_degrees)
