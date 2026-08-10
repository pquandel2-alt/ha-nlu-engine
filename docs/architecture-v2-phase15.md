# v2-Umbau, Phase 16: Fan-NLU erweitern

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Domain-Erweiterungen
Light/Cover/Fan/Climate/Query & Response (Phasen 14-19)", Abschnitt "Phase
16 - Fan-NLU". Vorstufe: `docs/architecture-v2-phase14.md` (Cover-NLU
erweitern).

## Ausgangslage: an/aus und die Capability waren bereits vorhanden

Der Plan nennt für Phase 16 vier Anforderungen:

1. "Mach den Ventilator an/aus" - bereits seit v1 über die domain-agnostische
   `HassTurnOn`/`HassTurnOff`/`HassToggle`-Grammatik (`light_switch.yaml`,
   `{name}`-Wildcard, keine domain-spezifische Formulierung) abgedeckt, `fan`
   ist bereits in `INTENTS`s `allowed_domains` enthalten.
2. `Capability.FAN_SPEED` - bereits seit Phase 10 (Capability System) in
   `nlu/capabilities.py` definiert und dort abgeleitet
   (`domain == "fan" and "percentage" in attributes`), vorausschauend für
   genau diese Phase gebaut.
3. **"Stell den Ventilator auf Stufe 1/3"** - neue Anforderung.
4. **"Mach ihn schneller/langsamer"** - neue Anforderung.

Nur 3+4 sind tatsächlich neuer Code dieser Phase.

## Was neu ist

Die 5. separat kompilierte hassil-Grammatik (`intents/de/fan_extended/
speed.yaml`, `FanExtendedParser` in `parsers.py`, geroutet über
`_FAN_EXTENDED_RE = r"\b(stufe|schneller|langsamer)\b"` in `engine.py`),
mit drei neuen, erfundenen (aber `Hass`-präfigierten, PascalCase) Intents -
konsistent mit dem in Phase 14 etablierten Muster (`HassLightBrighten` etc.),
da es für "Stufe N"/"schneller"/"langsamer" keinen exakten realen
HA-Core-Intent gibt:

- **`HassFanSetSpeed`** ("stelle/mach ... auf Stufe {level}"): `{level}` ist
  ein `RangeSlotList(type=RangeType.NUMBER)`-Slot (1-10) - die erste
  Verwendung von `RangeType.NUMBER` in diesem Projekt (vorherige Phasen
  nutzten ausschließlich `RangeType.PERCENTAGE`). `{level}` steht hinter dem
  Literal "auf Stufe", nicht direkt neben `{name}` - vermeidet damit den in
  Phase 14 dokumentierten Bug (unverankerter `WildcardSlotList` direkt vor
  einem `RangeSlotList` liefert 0 statt eines Fehlers oder des echten
  Werts). Vor dem Schreiben der YAML empirisch gegen `hassil==3.11.0`
  verifiziert.
- **`HassFanIncreaseSpeed`**/**`HassFanDecreaseSpeed`** ("schneller"/
  "langsamer machen"): rufen HAs native `fan.increase_speed`/
  `fan.decrease_speed` direkt auf, ohne zusätzliche `data`. Anders als bei
  Lichthelligkeit (Phase 14, wo `light` keinen generischen
  Erhöhen/Verringern-Service hat und deshalb ein erfundener Default-
  Schrittwert nötig war) übernimmt hier HA/das Gerät selbst die
  Schrittweite - architektonisch einfacher, keine Design-Entscheidung nötig.

## "Stufe N" -> Prozent: percentage_step-basierte Umrechnung

`HassFanSetSpeed`s `build`-Callable (`_fan_set_speed_plan` in
`service_call.py`) liest `es[0].attributes.get("percentage_step")` - das
rohe HA-Attribut, das jede `FanEntity` automatisch bereitstellt
(`percentage_step = 100 / speed_count`, Default `speed_count=100` also
`percentage_step=1.0` für einen stufenlosen Lüfter). Berechnung:
`percentage = min(round(level * percentage_step), 100)`. Das `min(..., 100)`
ist ein expliziter Schutz gegen einen Out-of-Range-Service-Call bei einer
zu hohen Stufe auf einem grobstufigen Lüfter (z.B. Stufe 10 auf einem
5-Stufen-Lüfter mit `percentage_step=20` würde sonst 200 statt 100 ergeben).
Fehlt das Attribut komplett (kein `percentage_step` in `attributes`), wird
`1.0` als Fallback angenommen (`or 1.0`), konsistent mit HAs eigenem
Default-Verhalten für stufenlose Lüfter.

## Kein neuer hassil-Bug in dieser Phase

Anders als Phase 14/15 trat hier keine Reihenfolge-/Verankerungs-Falle auf:
`{level}` ist durch das Literal "auf Stufe" von `{name}` getrennt (nicht
direkt benachbart), und "schneller"/"langsamer" enden auf ein eindeutiges
Wort ohne Overlap mit anderen Grammatiken. Ein isoliertes
Verifikationsskript gegen die echte `hassil`-Bibliothek (alle drei Intents
zusammen in einem `Intents`-Objekt) bestätigte vor dem Schreiben der YAML,
dass alle sieben getesteten Sätze korrekt matchen, inkl. eines Falls mit
Präposition ("... im Büro auf Stufe 1").

## Was bewusst NICHT gemacht wurde

**Keine Erweiterung der Quantifier-Grammatik** ("alle Ventilatoren auf
Stufe 2") - nicht Teil der Plan-Anforderung für diese Phase.

**Kein eigenes `IntentSpec`-Aufbohren** - analog zu `LightExtendedIntentSpec`
(siehe dessen Docstring) bekommt Fan eine eigene `FanExtendedIntentSpec`
statt eine bestehende Struktur wiederzuverwenden: andere Domain, andere
Parameterform (`level` statt `step_percent`/`color_name`), andere
`build`/`response`-Signatur.

## Tests

Neue `tests/test_engine_fan_extended.py`, drei lokale Fixtures (kein
Rückgriff auf die bestehende `FANS`-Fixture in `conftest.py`, die absichtlich
nur `TURN_ON`/`TURN_OFF` ohne `FAN_SPEED`/`percentage_step` trägt - für
Phase 16 sind eigene, zweckgebundene Fixtures nötig, analog zu
`test_engine_light_extended.py`s eigenen Licht-Fixtures):

- `STEPPED_FAN` (`percentage_step=20.0`, 5-Stufen-Lüfter) - pinnt die
  Umrechnung ("Stufe 3" -> 60%) und das Clamping ("Stufe 10" -> 100% statt
  200%).
- `CONTINUOUS_FAN` (kein `percentage_step`-Attribut) - pinnt den
  1.0-Fallback ("Stufe 7" -> 7%).
- `PLAIN_FAN` (keine `FAN_SPEED`-Capability) - drei Tests, die alle drei
  neuen Intents ohne die Capability ablehnen (`UNSUPPORTED_CAPABILITY` über
  den Command Validator, Phase 11).

Zusätzlich zwei dedizierte Tests für `HassFanIncreaseSpeed`/
`HassFanDecreaseSpeed`, die `plan.data == {}` pinnen - der eigentliche Punkt
dieser beiden Intents (kein erfundener Parameter, reiner Passthrough an HA).

**Ergebnis:** 399/399 Tests grün (391 aus Phase 15 + 8 neu), `pytest -q`
weiterhin < 1s. `pyflakes` clean.
