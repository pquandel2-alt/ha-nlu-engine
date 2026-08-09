# v2-Umbau, Phase 4: EntitySnapshot erweitern

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Baseline bis Area Resolver
2.0 (Phasen 0-7)", Abschnitt "Phase 4 – EntitySnapshot erweitern".
Vorstufe: `docs/architecture-v2-phase3.md` (Normalisierung).

## Was neu ist

`EntitySnapshot` (`entities.py`) hat fünf neue Felder, alle mit sicheren
Defaults (bestehende positionale Aufrufe wie in `tests/conftest.py`
`EntitySnapshot(eid, name, domain, state)` bleiben unverändert gültig):

- `device_class: str | None = None`
- `state_class: str | None = None`
- `aliases: tuple[str, ...] = ()`
- `attributes: Mapping[str, Any] = field(default_factory=dict)`
- `capabilities: frozenset[str] = field(default_factory=frozenset)`

`hass_entities.py`s `build_entity_snapshots()` befüllt `device_class`,
`state_class` und `attributes` direkt aus dem echten HA-`State`-Objekt
(`state.attributes.get("device_class"/"state_class")`, sowie die vollen
`state.attributes` roh durchgereicht - spätere domänenspezifische
Erweiterungen (ab Phase 14) können daraus lesen, ohne dass für jedes neue
Attribut ein eigenes `EntitySnapshot`-Feld nötig wird).

## Was bewusst NICHT gemacht wurde

`aliases` und `capabilities` sind strukturell vorhanden, aber überall noch
leer (`()`/`frozenset()`) - ihre Befüllung ist Gegenstand eigener,
folgender Phasen: das Alias-System (nächste Phase, "05 Alias-System" in
der Aufgabenliste dieses Projekts / Plan-Phase 5) bzw. das
Capability-Konzept (Plan-Phase 9, deutlich später). Das jetzt schon leere
Feld anzulegen vermeidet einen späteren Breaking Change an der
`EntitySnapshot`-Signatur.

## Bekannte Lücke (unverändert seit v1)

Wie in `docs/architecture-v1.md` dokumentiert, hat `hass_entities.py`
weiterhin keine automatisierte Testabdeckung (kein Mocking-Setup für eine
echte `hass`-Instanz im Repo) - die neue `device_class`/`state_class`/
`attributes`-Befüllung dort ist entsprechend nur durch die
Dataclass-Feld-Tests (s.u.) und manuelle Verifikation gegen die reale
HA-Instanz abgesichert, nicht durch automatisierte Tests.

## Tests

Neue Datei `tests/test_entity_snapshot_fields.py` (3 Tests): Default-Werte
bei Weglassen der neuen Felder, explizites Setzen aller neuen Felder, und
dass `attributes` als `default_factory=dict` nicht zwischen Instanzen
geteilt wird (klassische Mutable-Default-Falle).

**Ergebnis:** 302/302 Tests grün (299 aus Phase 3 + 3 neu),
`pytest -q` Laufzeit weiterhin < 1s.
