# v2-Umbau, Phase 5: Alias-System

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Baseline bis Area Resolver
2.0 (Phasen 0-7)", Abschnitt "Phase 5 – Alias-System".
Vorstufe: `docs/architecture-v2-phase4.md` (EntitySnapshot erweitern).

## Was neu ist

`entities.py` bekommt eine neue Datenstruktur und eine neue Funktion:

```python
@dataclass(frozen=True)
class EntityAlias:
    entity_id: str
    text: str
    source: str

def generate_aliases(entity: EntitySnapshot) -> tuple[EntityAlias, ...]: ...
```

`generate_aliases()` ist pure (kein HA-/hassil-Import) und liefert für eine
Entity alle zusätzlichen Namens-Kandidaten jenseits von `friendly_name`, aus
zwei Quellen:

- **Entity Name / Entity ID:** der rohe `entity_id`-String sowie eine
  humanisierte Form des Object-ID-Teils (`"wohnzimmer_decke"` →
  `"Wohnzimmer Decke"` — reine Formatierung, keine Übersetzung, daher ohne
  Rate-Risiko).
- **Konfigurierte Aliases:** `EntitySnapshot.aliases`, befüllt in
  `hass_entities.py` aus `entity_registry_entry.aliases` — demselben Feld,
  das HAs eigenes Assist-Feature für alternative Bezeichnungen nutzt
  ("konfigurierte Aliases" aus dem Plan).

Duplikate (case-insensitive, auch gegen `friendly_name`) werden beim
Erzeugen herausgefiltert.

`resolve_entity()`/`build_name_map()` berücksichtigen jetzt zusätzlich zu
`friendly_name` auch alle generierten Aliase — sowohl beim exakten Match
als auch beim Contains-Match. Mehrdeutigkeit (mehrere Entities teilen sich
denselben Alias-Text) führt weiterhin zu `AMBIGUOUS`, nie zu Raten.

`hass_entities.py`: `_area_info()` und die neue `_entity_aliases()`
nutzen jetzt einen einzigen, vorab geholten `RegistryEntry` statt zweier
getrennter Registry-Lookups pro Entity.

## Was bewusst NICHT gemacht wurde

**Area und Device Class wurden nicht in `generate_aliases()` als
Text-Kandidaten aufgenommen**, obwohl der Plan sie unter "Quellen" nennt.
Begründung:
- Phase 6 (Entity Resolver 2.0) behandelt Area und Device Class laut Plan
  bereits als eigene, separat gewichtete Scoring-Dimensionen ("matching
  area +30", "matching device class +15") statt als Text-Matches — sie in
  Phase 5 zusätzlich als flache Alias-Strings einzumischen würde dieselbe
  Information doppelt und mit unklarer Gewichtung einbringen.
- Eine deutsche Übersetzung von `device_class`-Werten (z.B. `"temperature"`
  → "Temperatur") bräuchte eine Lookup-Tabelle wie `_UNIT_SPOKEN_DE` in
  `service_call.py`; für unbekannte/zukünftige HA-Device-Classes wäre das
  Raten statt Nachschlagen. Zurückgestellt, bis Phase 6 klärt, wie Device
  Class in der Scoring-Pipeline tatsächlich gebraucht wird.

**"HA Assist aliases" (im Plan als "optional später" markiert) wurde nicht
zusätzlich zu den konfigurierten Aliases implementiert** — beide Quellen
laufen im Plan-Text auseinander, aber `entry.aliases` (das hier verwendete
Feld) *ist* bereits das native HA-Assist-Alias-Feature; ein zusätzlicher,
separater Mechanismus wurde nicht identifiziert und wird bei Bedarf in
einer späteren Phase nachgezogen.

## Unerwarteter, aber erwünschter Nebeneffekt

`test_query_case_and_question_mark_do_not_matter` (Phase-Query-Tests)
prüfte bisher, dass Umlaut-Normalisierung außerhalb des Scopes liegt
("AUSSENTEMPERATUR" ohne Umlaut darf nicht auf "Außentemperatur" matchen).
Mit dem Alias-System matcht es jetzt doch — nicht durch Umlaut-Normalisierung
(die es weiterhin nicht gibt), sondern weil `sensor.aussentemperatur` per
HA-Konvention ASCII-only ist und die daraus generierte Entity-Name-Alias
"Aussentemperatur" eine echte, alternative Bezeichnung ist. Test umbenannt
zu `test_query_case_does_not_matter` und Assertion umgekehrt, mit
Begründung im Testkommentar.

## Tests

Neue Datei `tests/test_aliases.py` (7 Tests): `generate_aliases()`
(Entity-ID/humanisierter Name, konfigurierte Aliases, Dedup gegen
friendly_name, `EntityAlias`-Instanzen) sowie `resolve_entity()` über
konfigurierte Aliase, humanisierte Entity-IDs und Alias-Kollisionen
(→ AMBIGUOUS).

**Ergebnis:** 309/309 Tests grün (302 aus Phase 4 + 7 neu),
`pytest -q` Laufzeit weiterhin < 1s.
