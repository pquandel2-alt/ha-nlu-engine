# v2-Umbau, Phase 7: Area Resolver 2.0

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Baseline bis Area Resolver
2.0 (Phasen 0-7)", Abschnitt "Phase 7 – Area Resolver 2.0".
Vorstufe: `docs/architecture-v2-phase6.md` (Entity Resolver 2.0).

## Was neu ist

`areas.py` bekommt dieselbe Vierstufen-Architektur wie `resolve_entity_scored`
(Phase 6), reduziert auf die Dimensionen, die für Räume tatsächlich existieren
- ein Raum hat nur einen Namen, keine Aliase/Entity-ID/Domain/Device-Class:

```python
@dataclass(frozen=True)
class AreaSnapshot:
    area_id: str
    name: str

class AreaResolutionStatus(Enum):
    RESOLVED = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()

@dataclass(frozen=True)
class AreaResolutionResult:
    status: AreaResolutionStatus
    area: AreaSnapshot | None = None
    candidates: tuple[AreaSnapshot, ...] = ()
    score: float | None = None

def resolve_area_scored(name, entities) -> AreaResolutionResult: ...
```

Vier Tiers (gleiche Werte wie bei den namensbasierten Tiers in Phase 6):
Exact +100, Normalized exact +85, Contains +50, Reverse contains +40,
`_AMBIGUITY_MARGIN = 5` identisch zu Phase 6. `AreaSnapshot`s werden aus der
bereits übergebenen Entity-Liste dedupliziert (`area_id` -> erster gesehener
`area_name`) - kein separater Registry-Zugriff, `areas.py` bleibt hass-frei.

`resolve_area_name()` (bisherige öffentliche API) ist jetzt ein dünner
Wrapper um `resolve_area_scored()`, exakt nach dem Muster von
`resolve_entity()` in Phase 6. Alle 7 bestehenden Tests in
`test_area_resolution.py` blieben dabei **unverändert grün**.

**Geteilte Normalisierung:** `_normalize_for_compare()` war bisher privat in
`entities.py`. Um Duplikation der Lowercase+Whitespace-Collapse-Logik in
`areas.py` zu vermeiden, wurde sie zu `normalize_for_compare()` (öffentlich)
umbenannt und von `areas.py` importiert - konsistent mit dem Rest des
Projekts, das keine Cross-Modul-Importe privater Symbole kennt.

## Was bewusst NICHT gemacht wurde

**Kein Kontext-Bonus-Mechanismus für Areas** - anders als bei Entities gibt
es keine zusätzliche Dimension (kein "Area-in-Area"-Konzept), die Phase 6s
`area_id`/`domain`/`device_class`-Bonusmuster hier sinnvoll übertragbar
machen würde. Die vier Namens-Tiers sind vollständig.

**`resolve_area_scored()` wird noch nirgends direkt aufgerufen** -
`parsers.QuantifierParser` nutzt weiterhin `resolve_area_name()` (den
Wrapper) unverändert. Das Verdrahten von echtem Scoring/Kandidatenlisten in
den Quantifier-Pfad ist nicht Teil dieser Phase; der Wrapper ist
verhaltensgleich zur alten Implementierung.

## Tests

Neue Datei `tests/test_area_resolver_scored.py` (8 Tests): pinnt jede Tier
einzeln (Exact, Normalized exact, Contains, Reverse contains), Ambiguity bei
echten Score-Ties, NOT_FOUND, leerer Name, und dass Entities ohne Area
(`area_id`/`area_name is None`) korrekt ignoriert werden.

**Ergebnis:** 328/328 Tests grün (320 aus Phase 6 + 8 neu),
`pytest -q` Laufzeit weiterhin < 1s. `pyflakes` clean.
