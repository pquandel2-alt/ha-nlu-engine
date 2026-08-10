# v2-Umbau, Phase 20: Golden Tests

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Golden/Negative Tests,
Debug-Modus, Performance (Phasen 23-27, 29-30)", Abschnitt "27. Golden
Tests". Vorstufe: `docs/architecture-v2-phase18.md` (Antwortsystem).

## Ausgangslage

Die bestehende Testsuite deckt die Grammatik pro Feature bereits ab
(`test_engine_lights.py`, `test_engine_covers.py` etc. - teils kombinatorisch
über `conftest.py`s Phrasen-Templates × Entity-Dicts), prüft aber jede
Domäne isoliert. Der Plan verlangt zusätzlich kuratierte, JSON-basierte
End-to-End-Fixtures unter `tests/golden/` (mindestens 100-200 Beispiele),
die die komplette Pipeline (Parser-Auswahl → Entity-Auflösung → Command →
Validator → Service-Call/Antworttext) über alle Feature-Bereiche hinweg als
lesbare, versionierte Snapshots festhalten.

## Golden/Snapshot-Ansatz statt Hand-Rechnen

`scripts/generate_golden_tests.py` berechnet die erwarteten Werte nicht von
Hand (fehleranfällig bei 100+ Fällen), sondern lässt jeden Kandidatensatz
durch die echte `NluEngine` laufen, prüft dabei nur Erfolg/Misserfolg wie
vom Autor beabsichtigt (`assert result is not None` bzw. `is None`), und
serialisiert das tatsächliche `MatchResult` (Plan + Antworttext) als
JSON-Datei. Damit sind die Fixtures beim Erzeugen bereits selbstverifizierend
(ein Tippfehler in einem Satz lässt die Assertion im Generator fehlschlagen,
nicht erst beim Test-Replay) und decken danach echte Regressionen auf.

`tests/golden_fixtures.py` (`GOLDEN_ENTITIES`) ist die einzige Entity-Quelle
für Generator UND Replay-Test (`tests/test_golden.py`) - beide müssen gegen
dieselben Entities auflösen, sonst könnte ein Replay eine andere Kandidatin
treffen als die Generierung. Bewusst eine eigene, kleine Entity-Liste statt
`conftest.py`s `ALL_ENTITIES`: Golden Cases brauchen Capabilities/Attribute
(Farbe, Farbtemperatur, Lüfterstufen, Klima-Zieltemperatur, ein
Flächen-Paar für Quantoren), die `ALL_ENTITIES`s einfache Fixtures nicht
tragen.

## Abgrenzung zu den bestehenden kombinatorischen Tests

`test_engine_lights.py`/`test_engine_covers.py` sind Python-native,
parametrisierte Tests (Phrasen-Templates × Entity-Namen), die die
Grund-Grammatik (an/aus/toggle, auf/zu) pro Domäne breit abdecken - nicht
JSON-basiert, nicht als eigenständig lesbare Datei-Snapshots gedacht. Die
Golden Tests sind bewusst ein zusätzliches, andersartiges Artefakt: sie
spannen alle Feature-Bereiche (inkl. der erweiterten Grammatiken aus Phase
14-18: Licht-Helligkeit/Farbe, Fan-Stufen, Climate-Temperatur, Prozent,
Quantoren, Abfragen) in einer einzigen, für Menschen durchsuchbaren
Fixture-Sammlung, und sind als Ganzes committed - eine Regression zeigt sich
im `git diff` einer JSON-Datei, nicht nur als roter Testname.

## Kategorien (`tests/golden/*.json`)

| Datei | Fälle | Deckt ab |
|---|---|---|
| `commands.json` | 27 | HassTurnOn/Off/Toggle über Light/Switch/Fan/Climate |
| `cover_open_close.json` | 22 | HassOpenCover/HassCloseCover, alle Verbformen |
| `percentage.json` | 20 | Rollladen-Position + Licht-Helligkeit via `{percent}` |
| `quantifiers.json` | 17 | "alle"/"beide", mit/ohne Raumbezug |
| `light_extended.json` | 23 | Heller/Dunkler, alle 12 Farbwörter, Warm-/Kaltweiß |
| `fan_extended.json` | 12 | Stufen 1-5, schneller/langsamer |
| `climate_extended.json` | 15 | Zieltemperatur, wärmer/kälter (alle Präpositionsvarianten) |
| `queries.json` | 10 | Sensor-Zustand (Temperatur, Feuchtigkeit), Licht-Helligkeits-Abfrage |
| `negative.json` | 15 | Siehe unten |

**Gesamt: 161 Fälle** (Plan-Vorgabe: 100-200).

## Negative Tests (`negative.json`)

15 Fälle, die bewusst zu `None` führen müssen - kein Ratefall, sondern jeder
mit einer dokumentierten, spezifischen Ursache: kein Template-Treffer
(Kauderwelsch, unvollständiger Satz), fehlende Capability (Farbe auf einer
Lampe ohne `COLOR`, Zieltemperatur auf einer Heizung ohne `TEMPERATURE`),
unbekannter Geräte-/Raumname, Prozent außerhalb 0-100, `"beide"` bei einer
Trefferzahl ungleich 2, und eine Abfrage auf eine nicht-abfragbare Domain
(Cover). Diese Fälle wurden im selben Durchgang wie die Positiv-Fälle
generiert (`assert result is None`) - Phase 21 des Plans ("Negative Tests")
erweitert diese Kategorie bei Bedarf gezielt, statt sie zu duplizieren.

## Replay (`tests/test_golden.py`)

Lädt alle `tests/golden/*.json`, parametrisiert einen Test pro Fall
(`category:text` als Test-ID, direkt in `pytest -v`-Output lesbar). Bei
`expect_match: false` genügt `result is None`; bei einem Treffer wird gegen
`response_text` sowie `plan.domain`/`service`/`entity_id`/`data` verglichen
(kein Objekt-Vergleich über `dataclasses.asdict`, um bei einem künftigen
neuen `ServiceCallPlan`-Feld nicht versehentlich stillschweigend `None`
mitzuvergleichen).

## Was bewusst NICHT gemacht wurde

**Kein Ersatz der bestehenden kombinatorischen Tests** - beide Testarten
bleiben nebeneinander bestehen, siehe Abgrenzung oben.

**Kein Vergleich über volle Objektgleichheit (`asdict(result) == case`)** -
die Replay-Assertions prüfen die vom Plan genannten, für einen Nutzer
sichtbaren Felder (Plan-Inhalt, Antworttext) explizit einzeln.

**Keine Kombination Prozent+Quantor in den Golden Cases** - laut
`docs/architecture-v2-phase*.md`-Historie (Prozent-Design-Entscheidung aus
v1) bewusst außerhalb des Scopes; nicht Teil dieser Phase.

## Tests

**Ergebnis:** 577/577 Tests grün (416 aus Phase 19 + 161 neue Golden-Replay-
Fälle), `pytest -q` weiterhin < 2s. `pyflakes` clean (inkl. `scripts/`).
