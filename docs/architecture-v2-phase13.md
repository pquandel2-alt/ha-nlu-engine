# v2-Umbau, Phase 14: Licht-NLU erweitern

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Implementierungsreihenfolge
(01-31) & Ausführungsprotokoll", Abschnitt "Phase 14 - Licht-NLU erweitern".
Vorstufe: `docs/architecture-v2-phase12.md` (Service Mapper +
Validator-Anbindung).

Nutzer-Entscheidungen (AskUserQuestion, vorige Session): Dimm-Schrittweite
ohne explizite Prozentangabe = **10 Prozent pro Befehl**; Farbvokabular =
**Basis-Set** (rot, grün, blau, gelb, orange, lila/violett, weiß, pink/rosa,
türkis/cyan).

## Was neu ist

Vier neue Intents - `HassLightBrighten`, `HassLightDim`,
`HassLightSetColor`, `HassLightSetColorTemp` - als **vierte** separat
kompilierte hassil-Grammatik (`{name}`/`{percent}`/`{color}`/`{color_temp}`),
analog zum bestehenden Muster (Single-Target/Quantifier/Percentage). Neuer
Ordner `intents/de/light_extended/color_brightness.yaml`, geladen über
`engine.py`s neuen `light_extended_dir`-Parameter.

Neue `LightExtendedParser`-Klasse in `parsers.py` (gleiches `IntentParser`-
Protokoll wie die drei bestehenden Parser): löst `{name}` wie gehabt auf,
verlangt Domain `light`, liest je nach Intent `{percent}` (mit Default 10,
falls abwesend), `{color}` oder `{color_temp}`.

Neue `LightExtendedIntentSpec`-Dataclass in `service_call.py` (Registry
`LIGHT_EXTENDED_INTENTS`), analog zu `IntentSpec`/`PercentIntentSpec`/
`QueryIntentSpec`:

```python
@dataclass(frozen=True)
class LightExtendedIntentSpec:
    capability: Capability
    build: Callable[[list[EntitySnapshot], Mapping[str, Any]], ServiceCallPlan]
    response: Callable[[list[EntitySnapshot], Mapping[str, Any]], str]
```

`capability` ist die einzige Quelle der Wahrheit, die `nlu/validator.py`
liest, um pro Intent die passende `Capability` (`BRIGHTNESS`, `COLOR`,
`COLOR_TEMPERATURE`) gegen `EntitySnapshot.capabilities` zu prüfen - kein
zweites, separat zu pflegendes Intent-zu-Capability-Dict.

Service-Parameter sind HA-native: `brightness_step_pct` (relativ, negativ
für Dim), `color_name` (CSS-Farbname, von HA selbst validiert/konvertiert -
keine hier erfundenen RGB-Tripel), `kelvin` (2700/6500 für warm-/kaltweiß).

`nlu/service_mapper.py` und `nlu/validator.py` bekamen je einen neuen
Dispatch-Zweig (`LIGHT_EXTENDED_INTENTS.get(...)`), `engine.py`s
`_build_match_result()` ebenso für die Response-Text-Erzeugung - alle drei
nach demselben Muster, das der `percent`-Zweig seit Phase 9 vorgibt.

Routing in `engine.py`: neuer `_LIGHT_EXTENDED_RE`
(`heller|dunkler|rot|grün|blau|...`), geprüft **vor** `_PERCENT_RE`, weil
"mach das Licht um 20 Prozent heller" sowohl "Prozent" als auch "heller"
enthält und sonst in `PercentageParser`s absolute `{name}/{percent}`-
Grammatik fallen würde statt in die neue relative Grammatik.

## Zwei empirisch gefundene hassil-Bugs (kritisch für künftige Grammatik-Arbeit)

Beide wurden nicht angenommen, sondern direkt gegen die echte
`hassil==3.11.0`-Bibliothek per isoliertem Testskript verifiziert (Projekt-
Grundsatz: nie raten, immer gegen die echte Library prüfen).

**1. Unverankertes `{name}` direkt vor `{percent}` (RangeSlotList) liefert
still `0` statt zu scheitern oder den echten Wert zu liefern.** Der Plan
schlägt wörtlich "Mach das Licht 20 Prozent heller" vor (unverankertes
`{name} {percent} Prozent heller`). Isoliert gegen `hassil.recognize()`
getestet: dieses Template matcht zwar strukturell, aber `percent` kommt
immer als `(0.0, '0')` zurück - unabhängig vom tatsächlichen Zahlenwert im
Text. Das ist ein anderer (und gefährlicherer) Fehlermodus als das bereits
in einer früheren Phase verifizierte `{name}{color}` (unverankertes
`WildcardSlotList` direkt neben `TextSlotList`), das korrekt funktioniert.
**Lektion: TextSlotList-Adjazenz zu einem unverankerten Wildcard ist sicher,
RangeSlotList-Adjazenz ist es nicht - jede neue Grammatik dieser Form muss
pro Slot-List-Typ einzeln empirisch verifiziert werden.**

Fix: literales Ankerwort "um" vor `{percent}` eingefügt (`"{name} um
{percent} Prozent heller"`) - entspricht ohnehin dem idiomatischen
Deutsch. Dadurch weicht die finale Grammatik leicht vom Plan-Beispiel ab:
"Mach das Licht **um** 20 Prozent heller" statt "Mach das Licht 20 Prozent
heller" - eine bewusste, dokumentierte Abweichung, erzwungen durch den oben
beschriebenen Bug.

**2. hassil wählt innerhalb *desselben* Intents den ersten strukturell
passenden Satz in Listen-Reihenfolge**, nicht nur über verschiedene
Intents/Grammatiken hinweg (wie bereits in `engine.py`s Modul-Docstring für
die Quantifier/Single-Target-Aufteilung dokumentiert), sondern auch
zwischen mehreren `sentences:`-Alternativen *eines* Intents. Selbst mit dem
korrekten "um"-Anker matchte der prozentlose Satz ("{name} heller") die
Eingabe "... um 20 Prozent heller" ebenfalls, weil `{name}` als
unverankertes Wildcard einfach "Dimmbare Lampe um 20 Prozent" komplett
verschluckt und "heller" als Rest übrig bleibt - stand dieser Satz zuerst
in der Liste, gewann er trotz falschem Ergebnis.

Fix: `sentences:`-Listen in `color_brightness.yaml` umsortiert -
prozentbehaftete (spezifischere) Sätze stehen jetzt vor den prozentlosen
(allgemeineren) für `HassLightBrighten` und `HassLightDim`.

Beide Fixes wurden per isoliertem Python-Skript direkt gegen
`hassil.recognize()` verifiziert, bevor sie in die YAML übernommen wurden.

## Was bewusst NICHT gemacht wurde

**Kein zweites Intent-zu-Capability-Dict** - `LightExtendedIntentSpec.capability`
ist die einzige Quelle, die `nlu/validator.py` liest (siehe oben) - eine
Verfeinerung gegenüber einer früher skizzierten, separaten Dict-Idee, die
dieselbe Information dupliziert hätte.

**Keine Änderung an `tests/conftest.py`s geteilter `ALL_ENTITIES`-Fixture** -
die neuen Tests in `test_engine_light_extended.py` nutzen vollständig
lokale, in sich geschlossene `EntitySnapshot`-Fixtures (dimmbare Lampe,
Vollfarblampe, einfache Lampe ohne Zusatz-Capabilities). Vermeidet das
Risiko, die geteilte Fixture erneut anzupassen (wie in Phase 13 nötig, als
fehlende `capabilities` dort mehrere Tests rot färbten).

**Keine RGB-Tripel oder HS-Werte** - `color_name` ist HA-nativ und lässt HA
selbst die Umrechnung/Validierung übernehmen; das Projekt erfindet keine
eigene Farbraum-Logik.

**Keine Kombination mit Quantifier/Area** ("mach alle Lichter im Büro rot")
- außerhalb des Phase-14-Scopes, wie schon bei "Prozent + alle/beide" in
einer früheren Phase bewusst zurückgestellt; ein solcher Satz scheitert
heute sauber mit NOT_FOUND (kein Crash), da `LightExtendedParser` immer
genau einen `{name}` auflöst.

## Tests

Neue Datei `tests/test_engine_light_extended.py` (11 Tests): Aufhellen/
Abdunkeln mit und ohne expliziten Prozentwert (Default 10), Farbe setzen
(beide Satzformen "mach ... rot" / "stelle ... auf blau"), Farbtemperatur
setzen (warm/kalt), plus 3 Capability-Ablehnungsfälle (Aufhellen ohne
`BRIGHTNESS`, Farbe ohne `COLOR`, Farbtemperatur ohne `COLOR_TEMPERATURE`).

**Ergebnis:** 378/378 Tests grün (367 aus Phase 13 + 11 neu), `pytest -q`
weiterhin < 1s. `pyflakes` clean.
