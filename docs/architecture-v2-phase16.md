# v2-Umbau, Phase 17: Climate-NLU

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Domain-Erweiterungen
Light/Cover/Fan/Climate/Query & Response (Phasen 14-19)", Abschnitt "Phase
17 - Climate-NLU". Vorstufe: `docs/architecture-v2-phase15.md` (Fan-NLU
erweitern).

## Ausgangslage: an/aus fehlte noch komplett, Capability war schon vorbereitet

Der Plan nennt für Phase 17 drei Anforderungen:

1. **"Mach die Heizung an/aus"** - anders als bei Fan (Phase 16) war `climate`
   bisher in keinem der `INTENTS`-`allowed_domains`-Sets (`HassTurnOn`/
   `HassTurnOff`/`HassToggle`) enthalten - echte neue Arbeit dieser Phase, kein
   reiner Vorschau-Fund wie bei Fan.
2. **"Stelle die Heizung auf 21 Grad"** - neue Anforderung, absoluter
   Zieltemperatur-Wert.
3. **"Mach die Heizung wärmer/kälter"** - neue Anforderung, relative
   Anpassung ohne erfundenen Nutzer-Parameter.

`Capability.TEMPERATURE` existierte zwar schon (Phase 9/10, `domain ==
"sensor" and device_class == "temperature"`), aber ausschließlich für
Sensoren - climate-Entities lieferten dort noch keine Capability. Das musste
in `nlu/capabilities.py` ergänzt werden, bevor der Command Validator (Phase
11) etwas zum Prüfen hatte.

## Was neu ist

Die 6. separat kompilierte hassil-Grammatik (`intents/de/climate_extended/
temperature.yaml`, `ClimateExtendedParser` in `parsers.py`, geroutet über
`_CLIMATE_EXTENDED_RE = r"\b(grad|wärmer|kälter|temperatur)\b"` in
`engine.py`), mit drei neuen, erfundenen (aber `Hass`-präfigierten,
PascalCase) Intents - konsistent mit dem in Phase 14/16 etablierten Muster,
da es für Zieltemperatur/wärmer/kälter keinen exakten realen HA-Core-Intent
gibt:

- **`HassClimateSetTemperature`** ("stelle ... auf {temperature} Grad"):
  `{temperature}` ist ein `RangeSlotList(type=RangeType.NUMBER, start=5,
  stop=30)`-Slot, durch das Literal "auf ... Grad" von `{name}` getrennt -
  vermeidet den in Phase 14 dokumentierten Bug (unverankerter
  `WildcardSlotList` direkt vor einem `RangeSlotList`), gleiches
  Anker-Prinzip wie `{level}` bei `HassFanSetSpeed` (Phase 16). Vor dem
  Schreiben der YAML empirisch gegen `hassil==3.11.0` verifiziert.
- **`HassClimateIncreaseTemperature`**/**`HassClimateDecreaseTemperature`**
  ("wärmer"/"kälter machen", "erhöhe/senke die Temperatur"): anders als bei
  Fan-Geschwindigkeit (Phase 16, `fan.increase_speed`/`decrease_speed`
  direkt) hat `climate` keinen nativen Erhöhen/Verringern-Service - hier war
  wie bei Licht-Helligkeit (Phase 14) ein erfundener fester Schrittwert
  nötig. Der Plan nennt selbst nur ein Beispiel (`{"operation": "increase",
  "amount": 1}`), keinen nutzerseitig sprechbaren Betrag - deshalb bewusst
  **kein** `{amount}`-Slot, nur ein fester Default-Schritt von 1 Grad
  (`_CLIMATE_TEMPERATURE_STEP` in `service_call.py`).

## "wärmer"/"kälter" -> absoluter Zielwert: aktuelles Setpoint + fester Schritt

`HassClimateIncreaseTemperature`/`-DecreaseTemperature`s `build`-Callable
(`_climate_step_plan` in `service_call.py`) liest `es[0].attributes
["temperature"]` - dasselbe rohe HA-Attribut, das `nlu/capabilities.py`
bereits zur Ableitung von `Capability.TEMPERATURE` liest (`domain ==
"climate" and "temperature" in attributes`). Direkter Dict-Zugriff statt
`.get(...)` mit Fallback (anders als `_fan_set_speed_plan`s
`percentage_step`-Fallback in Phase 16): der Command Validator garantiert
bereits vor dem Aufruf, dass die Entity die `TEMPERATURE`-Capability trägt,
und diese Capability existiert strukturell nur, wenn das Attribut vorhanden
ist - ein fehlendes Attribut an dieser Stelle wäre ein Invariantenbruch, kein
normaler Fall, den man abfangen müsste. `climate.set_temperature` wird mit
dem neuen absoluten Zielwert (`current ± 1`) aufgerufen, nicht mit einem
relativen Delta - HAs `climate.set_temperature`-Service kennt ohnehin nur
einen absoluten `temperature`-Parameter, kein Increment.

## Kein neuer hassil-Bug in dieser Phase

Wie schon bei Fan (Phase 16) trat hier keine neue Reihenfolge-/
Verankerungs-Falle auf - mit einer Ausnahme, die vor dem Schreiben der YAML
empirisch gefunden und gefixt wurde: die deutsche Dativ-Form brauchte alle
vier Artikel. "erhöhe die Temperatur von der Heizung"/"senke die Temperatur
bei der Heizung" verwenden den Dativ "der" (nicht Nominativ/Akkusativ
"den|die|das", die in den übrigen Grammatiken dieses Projekts bislang
genügten). Ohne "der" in der optionalen Artikel-Gruppe scheitert die Gruppe
am Match, und der unverankerte `{name}`-Wildcard absorbiert "der" mit
(`name="der Heizung"` statt `name="Heizung"`) - `[den|die|dem|der|das]`
deckt jetzt alle vier deutschen Artikel ab, empirisch gegen den echten
hassil-Parser verifiziert.

## Domain-weite an/aus: `climate` zu den 3 bestehenden `INTENTS`-Einträgen hinzugefügt

`HassTurnOn`/`HassTurnOff`/`HassToggle`s `allowed_domains` in
`service_call.py` enthalten jetzt `climate` zusätzlich zu `light`/`switch`/
`fan` - keine neue Grammatik nötig, die bestehende domain-agnostische
`{name}`-Wildcard-Grammatik (`light_switch.yaml`) deckt "mach die Heizung
an/aus" bereits strukturell ab, sobald die Domain erlaubt ist. Gleicher
Mechanismus wie bei Fan in Phase 16 (Punkt 1 dort), nur diesmal tatsächlich
neuer Code statt eines reinen Vorschau-Funds.

## Was bewusst NICHT gemacht wurde

**Keine Erweiterung der Quantifier-Grammatik** ("alle Heizungen wärmer") -
nicht Teil der Plan-Anforderung für diese Phase, gleiche Abgrenzung wie bei
Fan (Phase 16).

**Kein eigenes `IntentSpec`-Aufbohren** - analog zu `FanExtendedIntentSpec`
(siehe dessen Docstring) bekommt Climate eine eigene
`ClimateExtendedIntentSpec` statt eine bestehende Struktur wiederzuverwenden:
andere Domain, andere Parameterform (absolutes `temperature`-Ziel statt
`level`/step_percent), andere `build`/`response`-Signatur.

**Kein `{amount}`-Slot für "wärmer"/"kälter"** - siehe oben, der Plan
verlangt nur einen festen Default-Schritt, kein sprechbares Delta.

## Tests

Neue `tests/test_engine_climate_extended.py`, zwei lokale Fixtures (kein
Rückgriff auf eine bestehende Climate-Fixture - es gab bisher keine in
`conftest.py`, analog zu `test_engine_fan_extended.py`s eigenen
Ventilator-Fixtures):

- `HEATER` (`temperature=20`, `TEMPERATURE`-Capability) - pinnt die
  Zieltemperatur ("21 Grad" -> `{"temperature": 21}`) und die
  Schritt-Berechnung ("wärmer" -> 21, "kälter" -> 19, ausgehend vom
  aktuellen Setpoint 20).
- `PLAIN_CLIMATE` (keine `TEMPERATURE`-Capability) - drei Tests, die alle
  drei neuen Intents ohne die Capability ablehnen (`UNSUPPORTED_CAPABILITY`
  über den Command Validator, Phase 11).

Zusätzlich ein Test für die Dativ-Form ("erhöhe die Temperatur von der
Heizung Büro") und zwei Tests, die climate über die bereits bestehende
generische `HassTurnOn`/`HassTurnOff`-Grammatik ein-/ausschalten - pinnt die
`allowed_domains`-Erweiterung in `service_call.py`, ohne eine eigene
Grammatik dafür zu benötigen.

**Ergebnis:** 408/408 Tests grün (399 aus Phase 16 + 9 neu), `pytest -q`
weiterhin < 2s. `pyflakes` clean.
