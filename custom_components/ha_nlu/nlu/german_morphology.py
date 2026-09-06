"""Small deterministic helpers for German surface morphology."""

from __future__ import annotations

from enum import StrEnum


class GrammaticalGender(StrEnum):
    """Grammatical gender used for German area-name realization."""

    MASCULINE = "masculine"
    FEMININE = "feminine"
    NEUTER = "neuter"


_AREA_GENDERS: dict[str, GrammaticalGender] = {
    "abstellraum": GrammaticalGender.MASCULINE,
    "arbeitszimmer": GrammaticalGender.NEUTER,
    "bad": GrammaticalGender.NEUTER,
    "balkon": GrammaticalGender.MASCULINE,
    "büro": GrammaticalGender.NEUTER,
    "dachboden": GrammaticalGender.MASCULINE,
    "diele": GrammaticalGender.FEMININE,
    "einfahrt": GrammaticalGender.FEMININE,
    "esszimmer": GrammaticalGender.NEUTER,
    "flur": GrammaticalGender.MASCULINE,
    "garage": GrammaticalGender.FEMININE,
    "garten": GrammaticalGender.MASCULINE,
    "keller": GrammaticalGender.MASCULINE,
    "kinderzimmer": GrammaticalGender.NEUTER,
    "küche": GrammaticalGender.FEMININE,
    "sauna": GrammaticalGender.FEMININE,
    "schlafzimmer": GrammaticalGender.NEUTER,
    "speisekammer": GrammaticalGender.FEMININE,
    "terrasse": GrammaticalGender.FEMININE,
    "toilette": GrammaticalGender.FEMININE,
    "treppenhaus": GrammaticalGender.NEUTER,
    "waschküche": GrammaticalGender.FEMININE,
    "werkstatt": GrammaticalGender.FEMININE,
    "wohnzimmer": GrammaticalGender.NEUTER,
}

_COMPOUND_HEADS: tuple[tuple[str, GrammaticalGender], ...] = (
    ("arbeitszimmer", GrammaticalGender.NEUTER),
    ("schlafzimmer", GrammaticalGender.NEUTER),
    ("kinderzimmer", GrammaticalGender.NEUTER),
    ("treppenhaus", GrammaticalGender.NEUTER),
    ("speisekammer", GrammaticalGender.FEMININE),
    ("abstellraum", GrammaticalGender.MASCULINE),
    ("terrasse", GrammaticalGender.FEMININE),
    ("werkstatt", GrammaticalGender.FEMININE),
    ("garage", GrammaticalGender.FEMININE),
    ("kammer", GrammaticalGender.FEMININE),
    ("küche", GrammaticalGender.FEMININE),
    ("diele", GrammaticalGender.FEMININE),
    ("zimmer", GrammaticalGender.NEUTER),
    ("geschoss", GrammaticalGender.NEUTER),
    ("keller", GrammaticalGender.MASCULINE),
    ("boden", GrammaticalGender.MASCULINE),
    ("raum", GrammaticalGender.MASCULINE),
    ("flur", GrammaticalGender.MASCULINE),
    ("gang", GrammaticalGender.MASCULINE),
    ("halle", GrammaticalGender.FEMININE),
    ("bad", GrammaticalGender.NEUTER),
    ("hof", GrammaticalGender.MASCULINE),
)


def area_gender(name: str) -> GrammaticalGender | None:
    """Return a proven gender for an area name, or ``None`` if unknown.

    Exact common names take precedence. German compounds are then recognized
    by a known final head. Free-form labels with trailing qualifiers deliberately
    remain unknown instead of receiving a guessed article.
    """

    normalized = name.strip().casefold()
    if not normalized:
        return None
    exact = _AREA_GENDERS.get(normalized)
    if exact is not None:
        return exact
    for head, gender in _COMPOUND_HEADS:
        if normalized.endswith(head):
            return gender
    return None


def dative_location_phrase(name: str) -> str:
    """Build an article-safe German location phrase for an HA area name."""

    clean_name = name.strip()
    if not clean_name:
        return "im angegebenen Bereich"
    gender = area_gender(clean_name)
    if gender is GrammaticalGender.FEMININE:
        return f"in der {clean_name}"
    if gender in {GrammaticalGender.MASCULINE, GrammaticalGender.NEUTER}:
        return f"im {clean_name}"
    return f"im Bereich {clean_name}"


def sentence_initial(text: str) -> str:
    """Uppercase only the first character of a non-empty realized phrase."""

    return text[:1].upper() + text[1:]
