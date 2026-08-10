# v2-Umbau, Phase 15: Cover-NLU erweitern

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Domain-Erweiterungen
Light/Cover/Fan/Climate/Query & Response (Phasen 14-19)", Abschnitt "Phase
15 - Cover-NLU". Vorstufe: `docs/architecture-v2-phase13.md` (Licht-NLU
erweitern).

## Ausgangslage: die meisten Anforderungen waren bereits erfüllt

Der Plan nennt für Phase 15 vier Anforderungen:

1. "Öffne/Schließe die Rollläden" - bereits seit v1 über `HassOpenCover`/
   `HassCloseCover` (`cover.yaml`) abgedeckt.
2. "Fahre die Rollläden hoch/runter" - dieselben zwei Intents, andere
   Formulierung, ebenfalls bereits v1.
3. "Stell die Rollläden auf 50 Prozent" - bereits seit der Prozent-
   Steuerung (v1.1, dokumentiert in `docs/architecture-v1.md`) über die
   domain-generische `HassSetPercentage`-Grammatik (`PERCENT_INTENTS["cover"]`
   in `service_call.py`) abgedeckt, inkl. Regressionstest für Position 100
   in `tests/test_engine_percentage.py`.
4. **"Zusätzlich 'ganz auf'/'ganz zu' -> intern 100/0"** - dies ist die
   einzige tatsächlich neue Anforderung dieser Phase.

## Was neu ist

Zwei neue Satzalternativen in `cover.yaml`: `"mach [den|die|das] {name}
ganz auf"` (für `HassOpenCover`) und `"mach [den|die|das] {name} ganz zu"`
(für `HassCloseCover`). Kein neuer Intent, keine neue Grammatik, kein neuer
Code-Pfad: "ganz auf"/"ganz zu" sind im Deutschen reine Betonungsformen von
"öffnen"/"schließen" - dieselbe Bedeutung (vollständig offen/geschlossen),
die `open_cover`/`close_cover` bereits liefern. Der Plan-Wortlaut "intern
100/0" beschreibt die *Bedeutung* der Phrase (ganz offen = Position 100,
ganz zu = Position 0), nicht einen eigenen Service-Call-Pfad über
`set_cover_position` - dieser existiert für explizite Prozentangaben bereits
(Punkt 3 oben) und wird hier bewusst nicht dupliziert.

## Ein während dieser Phase erneut aufgetretener hassil-Bug (Bug 2 aus Phase 14)

Die naive Umsetzung - "ganz auf"/"ganz zu" einfach ans Ende der jeweiligen
`sentences:`-Liste anhängen - hätte denselben in Phase 15 bereits
dokumentierten Fehler reproduziert (Brain-Knoten "ha-nlu-engine:
hassil-Grammatik-Fallstricke"): das bereits vorhandene, unverankerte
`"mach [den|die|das] {name} auf"` matcht "mach das Rollladen ganz auf"
GENAUSO strukturell, indem `{name}` das Wort "ganz" mitverschluckt
(`name="Rollladen ganz"` statt `"Rollladen"`). Da beide Sätze zum selben
Intent (`HassOpenCover`) gehören und hassil den ersten strukturell
passenden Satz in Listen-Reihenfolge wählt, hätte die falsche Reihenfolge
zu einem fehlschlagenden Entity-Resolve geführt (kein Crash, aber ein
"nicht verstanden" für einen eigentlich validen Satz).

Empirisch mit einem isolierten Skript gegen `hassil.recognize()`
verifiziert (siehe Tabelle):

| Reihenfolge | `{name}`-Wert für "mach das Rollladen ganz auf" |
|---|---|
| "ganz auf" zuerst | `"Rollladen"` (korrekt) |
| "auf" zuerst | `"Rollladen ganz"` (falsch) |

**Fix:** `"... ganz auf"`/`"... ganz zu"` stehen jeweils als erster Satz in
der `sentences:`-Liste ihres Intents, vor der allgemeineren `"... auf"`/
`"... zu"`-Variante - konsistent mit der in Phase 14 etablierten Regel
"spezifischer vor allgemeiner".

## Was bewusst NICHT gemacht wurde

**Keine Erweiterung von `quantifiers/cover_all.yaml`** ("alle Rollläden
ganz auf") - nicht Teil der Plan-Anforderung für diese Phase, würde den
Scope ohne konkrete Anforderung erweitern.

**Kein eigener `set_cover_position`-Pfad für "ganz auf"/"ganz zu"** - siehe
oben; `open_cover`/`close_cover` liefern bereits exakt die geforderte
Bedeutung, ein zweiter Code-Pfad für dasselbe Ergebnis wäre unnötige
Duplikation.

## Tests

`tests/conftest.py`s `COVER_OPEN_PHRASES`/`COVER_CLOSE_PHRASES` um "Mach
{name} ganz auf"/"Mach {name} ganz zu" ergänzt - dadurch laufen die
bestehenden parametrisierten Tests in `test_engine_covers.py`
(`test_open_cover`/`test_close_cover`, alle 6 Cover-Fixtures) automatisch
mit den neuen Phrasen mit, ohne neue Testfälle von Hand pflegen zu müssen.

Zusätzlich ein dedizierter Test
`test_ganz_auf_ganz_zu_do_not_swallow_ganz_into_entity_name` in
`test_engine_covers.py`, der explizit die *Namensauflösung* pinnt (nicht
nur den Match) - der eigentlich interessante Regressionsfall aus dem oben
beschriebenen Bug.

**Ergebnis:** 391/391 Tests grün (378 aus Phase 14 + 13 neu: 12 aus den
erweiterten parametrisierten Phrasenlisten [6 Cover-Fixtures × 2 neue
Phrasen] + 1 dedizierter Namensauflösungs-Test), `pytest -q` weiterhin
< 1s. `pyflakes` clean.
