# v2-Umbau, Phase 6: Entity Resolver 2.0

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Baseline bis Area Resolver
2.0 (Phasen 0-7)", Abschnitt "Phase 6 – Entity Resolver 2.0".
Vorstufe: `docs/architecture-v2-phase5.md` (Alias-System).

## Was neu ist

Neue Datenstruktur und Funktion in `entities.py`:

```python
class ResolutionStatus(Enum):
    RESOLVED = auto()
    AMBIGUOUS = auto()
    NOT_FOUND = auto()

@dataclass(frozen=True)
class ResolutionResult:
    status: ResolutionStatus
    entity: EntitySnapshot | None = None
    candidates: tuple[EntitySnapshot, ...] = ()
    score: float | None = None

def resolve_entity_scored(
    name, entities, *, area_id=None, domain=None, device_class=None
) -> ResolutionResult: ...
```

Vierstufige Pipeline pro Aufruf, wie im Plan beschrieben:

1. **Candidate Generation:** für jede Entity werden `friendly_name` +
   alle `generate_aliases()`-Ergebnisse (entity_id, humanisierter Name,
   konfigurierte Aliase - Phase 5) als Namens-Kandidaten geprüft.
2. **Scoring** (Beispielwerte aus dem Plan, unverändert übernommen):
   Exact friendly name +100, Exact alias +90, Normalized exact +85,
   Entity-ID-Match +70, Contains +50, Reverse contains +40. Pro Entity
   zählt der höchste erreichte Tier-Wert über alle ihre Namens-Kandidaten.
3. **Context Filtering:** optionale `area_id`/`domain`/`device_class`-Hints
   addieren Bonus-Punkte (+30/+20/+15), aber nur wenn der Aufrufer sie
   tatsächlich kennt - ohne Hint kein Bonus, kein Rate-Versuch.
4. **Ambiguity Detection:** die Kandidaten mit dem höchsten Score werden
   gesammelt; liegen mehrere innerhalb von 5 Punkten des Spitzenwerts
   (`_AMBIGUITY_MARGIN`), gilt das Ergebnis als `AMBIGUOUS` statt eine
   davon zu raten.

`resolve_entity()` (bisherige öffentliche API, Phase 1-5) ist jetzt ein
dünner, kontextfreier Wrapper um `resolve_entity_scored()` - `build_name_map()`
entfällt ersatzlos (war nur intern von `resolve_entity()` genutzt). Alle 23
bestehenden Tests in `test_entity_resolution.py`/`test_aliases.py` blieben
dabei **unverändert grün** - der Score-Abstand zwischen den
Exact/Normalized-Tiers (100/90/85) und den Contains-Tiers (50/40) ist groß
genug, dass ein exakter Treffer nie von einem zufälligen Contains-Konkurrenten
eingeholt wird, und exakt gleich bewertete Contains-Treffer erzeugen wie
zuvor AMBIGUOUS.

## Was bewusst NICHT gemacht wurde

**`resolve_entity_scored()` wird noch nirgends mit `area_id`/`domain`/
`device_class`-Kontext aufgerufen** - `resolve_entity()` (weiterhin von
`parsers.py` genutzt) ruft ohne Hints auf. Das Threading von echtem
Area-Kontext in den Single-Target-Resolutionspfad ist Gegenstand von Phase 7
("Area Resolver 2.0", nächste Phase) - hier zwei separate Konzepte in einem
Schritt zu vermischen hätte das Risiko unklarer werden lassen, welche
Verhaltensänderung von welcher Phase stammt.

**Scoring-Gewichte wurden nicht verändert oder "getuned"** - der Plan nennt
sie explizit als vorläufige Beispielwerte; sie durch echte Nutzungsdaten zu
kalibrieren ist keine Aufgabe dieser Phase.

## Tests

Neue Datei `tests/test_resolver.py` (11 Tests): pinnt jede Scoring-Tier
einzeln (Exact friendly name, Exact alias, Normalized exact, Entity-ID,
Contains, Reverse contains), den Area-Bonus als Tie-Breaker, addierte
Domain+Device-Class-Boni, sowie Ambiguity Detection bei echten Score-Ties
und den NOT_FOUND-Fall.

**Ergebnis:** 320/320 Tests grün (309 aus Phase 5 + 11 neu),
`pytest -q` Laufzeit weiterhin < 1s.
