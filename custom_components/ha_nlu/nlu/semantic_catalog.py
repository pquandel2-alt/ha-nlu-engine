"""Single declarative catalogue for reusable German semantic expressions.

Values in this module describe meanings, never complete sentences.  The
language frontend, semantic interpreter and drift tests consume the same
catalogue so a synonym cannot accidentally work only for one router.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain_operations import (
    ACTION_EXPRESSIONS,
    COMMAND_MARKER_EXPRESSIONS,
    DOMAIN_EXPRESSIONS,
    DOMAIN_WORDS,
    INTENT_BY_DOMAIN_ACTION,
)
from .semantic_state import SemanticState


@dataclass(frozen=True)
class CatalogueEntry:
    value: object
    expressions: tuple[str, ...]


DEVICE_CLASS_ENTRIES = (
    CatalogueEntry(("binary_sensor", "window"), (r"fenster(?:kontakte?)?",)),
    CatalogueEntry(("binary_sensor", "door"), (r"tür(?:en)?",)),
    CatalogueEntry(("binary_sensor", "garage_door"), (r"garagentor(?:e)?",)),
    CatalogueEntry(
        ("binary_sensor", "motion"),
        (r"bewegungsmelder", r"bewegungssensor(?:en)?"),
    ),
)

STATE_ENTRIES = (
    CatalogueEntry(
        SemanticState.OPEN,
        (r"offen\w*", r"geöffnet\w*", r"hochgefahren\w*", r"oben"),
    ),
    CatalogueEntry(
        SemanticState.CLOSED,
        (
            r"geschlossen\w*",
            r"runtergefahren\w*",
            r"heruntergefahren\w*",
            r"unten",
            r"zu",
        ),
    ),
    CatalogueEntry(
        SemanticState.ON,
        (r"an", r"ein", r"eingeschaltet\w*", r"angeschaltet\w*"),
    ),
    CatalogueEntry(SemanticState.OFF, (r"aus", r"ausgeschaltet\w*")),
    CatalogueEntry(
        SemanticState.ACTIVE,
        (r"läuft", r"laeuft", r"laufend", r"aktiv", r"in\s+betrieb"),
    ),
    CatalogueEntry(
        SemanticState.INACTIVE,
        (r"inaktiv", r"steht", r"gestoppt", r"pausiert"),
    ),
)

QUANTIFIER_ENTRIES = (
    CatalogueEntry("all", (r"alle", r"sämtliche\w*", r"jede\w*", r"die\s+ganzen")),
    CatalogueEntry("both", (r"beide\w*",)),
)

QUERY_SCOPE_ENTRIES = (
    CatalogueEntry("count", (r"wie\s+viele",)),
    CatalogueEntry(
        "locations", (r"wo", r"in\s+welchen\s+räumen", r"welche\s+räume")
    ),
    CatalogueEntry(
        "exists", (r"gibt\s+es", r"haben\s+wir", r"irgendein\w*", r"irgendwelche")
    ),
    CatalogueEntry("none", (r"kein\w*",)),
    CatalogueEntry("average", (r"durchschnitt\w*",)),
    CatalogueEntry(
        "measurement", (r"wie\s+viel", r"aktuell\w*", r"momentan", r"gerade")
    ),
)

AUTOMATION_CUE_ENTRIES = (
    CatalogueEntry("predicate", (r"wenn", r"sobald", r"falls", r"sofern", r"nur\s+wenn")),
)

PROPERTY_ENTRIES = (
    CatalogueEntry("temperature", (r"temperatur", r"wärme", r"warm", r"kalt", r"grad")),
    CatalogueEntry("humidity", (r"luftfeuchtigkeit", r"feuchtigkeit", r"feucht")),
    CatalogueEntry("battery", (r"batteriestand", r"batterie", r"batterien")),
    CatalogueEntry("power", (r"leistung",)),
    CatalogueEntry("energy", (r"stromverbrauch", r"energieverbrauch")),
    CatalogueEntry("brightness", (r"helligkeit", r"hell")),
    CatalogueEntry("position", (r"position", r"höhe", r"oeffnung", r"öffnung")),
    CatalogueEntry("volume", (r"lautstärke", r"lautstaerke", r"laut", r"leise")),
)

COMPARATOR_ENTRIES = (
    CatalogueEntry("lt", (r"unter", r"weniger\s+als", r"dunkler\s+als")),
    CatalogueEntry("gt", (r"über", r"mehr\s+als", r"heller\s+als")),
    CatalogueEntry("lte", (r"höchstens", r"nicht\s+höher\s+als")),
    CatalogueEntry("gte", (r"mindestens",)),
)

MEASUREMENT_PROPERTY_SPECS = {
    "temperature": ("sensor", "temperature", "Temperatur", "temperatur"),
    "humidity": ("sensor", "humidity", "Luftfeuchtigkeit", "luftfeuchtigkeit"),
    "battery": ("sensor", "battery", "Batteriestand", "batterie"),
    "power": ("sensor", "power", "Leistung", "leistung"),
    "energy": ("sensor", "energy", "Energieverbrauch", "energieverbrauch"),
    "brightness": ("light", None, "Helligkeit", "helligkeit"),
}

# Literal canonical surfaces used only for bounded spelling candidates. Regex
# expressions above remain the semantic source; this set intentionally lists
# their ordinary dictionary forms, not sentence shapes.
CANONICAL_SPELLING_FORMS = frozenset({
    "anmachen", "ausmachen", "einschalten", "ausschalten", "umschalten",
    "öffnen", "schließen", "hochfahren", "runterfahren", "herunterfahren",
    "stellen", "setzen", "starten", "stoppen", "pausieren", "spielen",
    "aktivieren", "deaktivieren", "erhöhen", "senken", "dimmen",
    "temperatur", "helligkeit", "lautstärke", "luftfeuchtigkeit", "position",
    "prozent", "automatik", "wiedergabe",
    *(word for words in DOMAIN_WORDS.values() for word in words if " " not in word),
})


def catalogue_expression_groups() -> dict[str, tuple[CatalogueEntry, ...]]:
    """Return every non-domain semantic group for tooling and drift checks."""
    return {
        "device_class": DEVICE_CLASS_ENTRIES,
        "state": STATE_ENTRIES,
        "quantifier": QUANTIFIER_ENTRIES,
        "query_scope": QUERY_SCOPE_ENTRIES,
        "automation_cue": AUTOMATION_CUE_ENTRIES,
        "property": PROPERTY_ENTRIES,
        "comparator": COMPARATOR_ENTRIES,
    }


__all__ = [
    "ACTION_EXPRESSIONS",
    "AUTOMATION_CUE_ENTRIES",
    "COMMAND_MARKER_EXPRESSIONS",
    "COMPARATOR_ENTRIES",
    "CatalogueEntry",
    "CANONICAL_SPELLING_FORMS",
    "DEVICE_CLASS_ENTRIES",
    "DOMAIN_EXPRESSIONS",
    "DOMAIN_WORDS",
    "INTENT_BY_DOMAIN_ACTION",
    "MEASUREMENT_PROPERTY_SPECS",
    "PROPERTY_ENTRIES",
    "QUANTIFIER_ENTRIES",
    "QUERY_SCOPE_ENTRIES",
    "STATE_ENTRIES",
    "catalogue_expression_groups",
]
