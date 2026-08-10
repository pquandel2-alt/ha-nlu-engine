# v2-Umbau, Phase 23: Performance/Indexing

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Golden/Negative Tests,
Debug-Modus, Performance (Phasen 23-27, 29-30)", Abschnitt "30.
Performance". Vorstufe: `docs/architecture-v2-phase21.md` (Debug-Modus).

## Ausgangslage

Der Plan nennt drei Performance-Anforderungen: (1) Entity Snapshot einmal
pro Conversation Request statt pro Parser, (2) Parser-Grammatiken beim Setup
laden statt pro Anfrage, (3) Candidate Indexing "später vorbereiten"
(normalized_name→entities, area→entities, domain→entities, alias→entities),
damit Entity Resolution nicht O(n) über alle Entities für jeden einzelnen
Kandidaten läuft.

## (1) und (2) bereits erfüllt - verifiziert, nicht neu gebaut

Beide Punkte sind strukturell bereits so umgesetzt, seit `engine.py`
existiert:

- **Parser-Grammatiken beim Setup:** `NluEngine.__init__()` lädt alle sechs
  `Intents`-Objekte (`Intents.from_files(...)`) und baut alle sechs
  `IntentParser`-Instanzen genau einmal. `match()`/`respond()`/`debug()`
  greifen nur noch auf die bereits gebauten `self._*_parser`-Attribute zu -
  kein YAML-Parsing pro Anfrage.
- **Entity Snapshot einmal pro Request:** `conversation.py`s
  `_async_handle_message()` ruft `build_entity_snapshots(self.hass,
  self.entry)` genau einmal pro eingehender Nachricht auf und übergibt die
  resultierende Liste als ein einziges Argument an `self._engine.match(...)`
  - der `NluEngine` selbst (`self._engine = NluEngine()`) wird einmalig im
  `__init__` der Conversation-Entity erzeugt, nicht pro Nachricht.

Kein Code-Änderungsbedarf; beide Punkte hier als verifizierter Ist-Zustand
dokumentiert, damit der "Nächster Schritt"-Status im Plan-Knoten nicht
fälschlich offene Arbeit suggeriert.

## (3) Candidate Indexing: `entities.py`, `EntityIndex`/`build_entity_index()`

Der Plan formuliert diesen Punkt selbst als "später vorbereiten" - im
aktuellen Code löst jeder Parser pro Äußerung höchstens einen Namen
(`resolve_entity`) oder einen Domain+Area-Filter (`resolve_entities_by_domain`)
auf, nie mehrere Kandidaten hintereinander gegen dieselbe Entity-Liste. Ein
Index lohnt sich rechnerisch erst, wenn er einmal gebaut und danach mehrfach
wiederverwendet wird; für die heutigen Ein-Abfrage-pro-Utterance-Parser wäre
er reiner Mehraufwand (Index-Aufbau ist selbst ein O(n)-Scan, ohne dass eine
zweite Abfrage die Ersparnis wieder hereinholt).

Trotzdem jetzt gebaut und getestet, bewusst additiv - derselbe Vorgriff, den
`SemanticFrame`/`SemanticCommand`/`respond()` in ihren jeweiligen Phasen
schon vor ihrem ersten Konsumenten bekommen haben:

- `EntityIndex` (frozen Dataclass): `by_domain`, `by_area`,
  `by_normalized_name`, `by_normalized_alias` - je ein `Mapping[str,
  tuple[EntitySnapshot, ...]]`.
- `build_entity_index(entities)`: ein einziger Scan über `entities`, der alle
  vier Lookups gleichzeitig befüllt. `by_normalized_alias` nutzt
  `generate_aliases()` (entity_id, humanisierte entity_id-Form, konfigurierte
  Aliase) - dieselben Quellen, die `resolve_entity_scored` schon bewertet,
  hier nur für O(1)-Exakt-Lookup gruppiert statt bei jedem Aufruf neu
  gescannt. `by_normalized_name` deckt den Friendly-Name-Tier ab;
  `generate_aliases()` schließt den Friendly Name über sein eigenes
  `seen`-Set aus, die beiden Indizes überlappen also nicht.

**Bewusst nicht in `resolve_entity`/`resolve_entities_by_domain` verdrahtet:**
diese Funktionen bewerten weiterhin Contains-/Reverse-Contains-Tiers
(Teilstring-Vergleich), die ein Hash-Index strukturell nicht beschleunigen
kann - nur die Exakt-Tiers (Friendly Name, Alias, normalisiert-exakt)
profitieren überhaupt von einem Index. Eine Verdrahtung heute, bei
höchstens einer Abfrage pro Utterance, würde die bestehenden, bereits
getesteten Resolver-Funktionen verkomplizieren, ohne einen messbaren
Vorteil zu bringen. Vorgesehener künftiger Konsument: eine
Mehrfach-Kandidaten-Phase (Pronomen/Referenzen, Hierarchische Orte, Phasen
27/28), die pro Utterance mehrere Namen auflösen muss - dort baut der
Aufrufer dann einmal einen `EntityIndex` pro Turn und reicht ihn an alle
Resolutions-Aufrufe weiter, statt die Entity-Liste pro Kandidat erneut zu
scannen.

## Tests

Neue `tests/test_entity_index.py` (5 Fälle): Domain-Gruppierung,
Area-Gruppierung (Entities ohne `area_id` werden ausgeschlossen),
Normalisierung (Groß-/Kleinschreibung, Whitespace) für `by_normalized_name`,
Alias-Abdeckung (entity_id, humanisierte Form, konfigurierter Alias) für
`by_normalized_alias`, leere Entity-Liste → leere Indizes.

**Ergebnis:** 589/589 Tests grün (584 aus Phase 22 + 5 neue
`EntityIndex`-Fälle), `pytest -q` weiterhin < 2s. `pyflakes` clean (inkl.
`scripts/`).
