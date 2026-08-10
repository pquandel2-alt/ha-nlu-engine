# v2-Umbau, Phase 12: Service Mapper + Validator-Anbindung

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Quantifier, Capability,
Command, Validator, ServiceMapper (Phasen 8-13)", Abschnitte "Phase 12 –
ServiceCallPlan beibehalten, aber nach hinten verschieben" und "Phase 13 –
Service Mapper" (zusammengefasst in einer Projekt-Phase, da Phase 12 des
Plans keine eigene Code-Lieferung beschreibt, sondern die Reihenfolge, die
Phase 13 dann konkret umsetzt).
Vorstufe: `docs/architecture-v2-phase11.md` (Command Validator).

## Was neu ist

Neue Datei `nlu/service_mapper.py`:

```python
def map_to_service_call(command: SemanticCommand) -> ServiceCallPlan | None: ...
```

Übernimmt die eine Entscheidung, die bisher direkt in `engine.py`s
`_build_match_result()` inline stand: welcher Eintrag aus `INTENTS`
(Intent-Name-basiert) bzw. `PERCENT_INTENTS` (Domain-basiert, siehe Phase
9/`service_call.py`) auf ein gegebenes Command passt. Die eigentlichen
Domain-spezifischen `build`-Callables (welcher Service, welcher Data-Key)
bleiben unverändert in `service_call.py` - `ServiceMapper` dupliziert sie
nicht, sondern zentralisiert nur die Registry-Auswahl, die vorher lose in
`engine.py` verstreut war (passend zum Plan-Zitat "Die Domain-spezifische
Logik gehört hierher, nicht in den Parser" - hier verstanden als "nicht
verstreut im Router").

`engine.py`s `_build_match_result()` baut das `SemanticCommand` jetzt wie
bisher (Phase 10), ruft aber direkt danach `validate_command(command)`
(Phase 11) auf - bei einem Fehler wird `None` zurückgegeben, bevor
überhaupt ein `ServiceCallPlan` entsteht. Erst danach ersetzt
`map_to_service_call(command)` die bisherigen direkten `spec.build(...)`-
Aufrufe für den ServiceCallPlan (Response-Text-Erzeugung bleibt unverändert
über `spec.response(...)` - das ist kein Service-Call, fällt nicht in
`ServiceMapper`s Zuständigkeit).

```python
if validate_command(command) is not None:
    return None
...
plan=map_to_service_call(command)  # statt spec.build(matched, percent) / spec.build(matched)
```

## Warum das (noch) keine sichtbare Verhaltensänderung ist

Wie in Phase 11 dokumentiert, policen sich die drei bestehenden Parser
bereits selbst - kein heutiger Match kann eine `SemanticCommand` erzeugen,
die `validate_command()` ablehnt. Diese Phase ist der Moment, in dem der
Validator zum ersten Mal tatsächlich im Live-Pfad hängt (`engine.py` ruft
ihn jetzt auf), aber das ändert das beobachtbare Verhalten für keinen
heutigen Satz - alle 5 "reale Matches validieren sauber"-Tests aus
`test_validator.py` waren schon vor dieser Phase grün. Der Nutzen ist
strukturell: ein zukünftiger, nicht-selbstpolizierender Parser (LLM
Adapter) bekommt jetzt einen echten Torwächter statt eines toten Codepfads.

## Ein während dieser Phase gefundener und behobener Test-Fixture-Mangel

Das Wiring deckte auf, dass `tests/conftest.py`s geteilte `ALL_ENTITIES`-
Fixture (aus der Zeit vor Phase 9, Capability System) durchweg
`capabilities=frozenset()` trug - realistische Lichter/Rollläden hätten
`BRIGHTNESS`/`POSITION` (von `hass_entities.py`s `derive_capabilities()` aus
echten HA-Attributen abgeleitet). Solange nichts `capabilities` las, war das
folgenlos; sobald `validate_command()` live hing, schlugen alle
Prozent-Tests mit `UNSUPPORTED_CAPABILITY` fehl - nicht, weil der Validator
falsch lag, sondern weil die Testdaten eine reale Lampe/Rollladen falsch
darstellten. **Fix:** `_snapshots()` in `conftest.py` bekam einen
`capabilities`-Parameter; Lichter/Schalter/Ventilatoren tragen jetzt
`TURN_ON`/`TURN_OFF`, Lichter zusätzlich `BRIGHTNESS`, Rollläden `POSITION` -
dieselben Capabilities, die ein echtes Gerät über `derive_capabilities()`
bekäme.

## Was bewusst NICHT gemacht wurde

**Keine `ServiceMapper`-Klasse (im Plan als Klasse mit `.map()`-Methode
skizziert)** - eine freie Funktion `map_to_service_call()` reicht, da es
keinen Zustand gibt, der eine Instanz rechtfertigen würde (dasselbe Muster
wie `build_semantic_command()` in Phase 10 und `validate_command()` in
Phase 11 - beide ebenfalls freie Funktionen statt Klassen).

**Keine Migration der `build`-Callables selbst aus `service_call.py`** -
`ServiceMapper` entscheidet nur, welcher Callable zuständig ist; die
Callables (welcher HA-Service, welche Datenfelder) bleiben dort, wo sie seit
v1 stehen. Eine vollständige Verschiebung wäre eine zusätzliche, vom Plan
nicht geforderte Umstrukturierung ohne Verhaltensnutzen.

**Response-Text-Erzeugung bleibt unverändert in `engine.py`** - nur
`ServiceCallPlan`-Konstruktion läuft jetzt über `ServiceMapper`; das
Ansagen des Ergebnisses ist kein "Service Call" im Sinne des Plans.

## Tests

- Neue Datei `tests/test_service_mapper.py` (4 Tests): pinnt
  `map_to_service_call()` direkt - Schalter → `homeassistant.turn_on`,
  Prozent-Command auf Licht vs. Rollladen (Domain entscheidet, nicht der
  Intent-Name - Phase 9-Design), unbekannter Intent → `None`.
- Neue Datei `tests/test_engine_validator_gate.py` (1 Test): baut von Hand
  ein `ParseResult`, das `validate_command()` ablehnen würde
  (`UNSUPPORTED_CAPABILITY`), und ruft `NluEngine._build_match_result()`
  direkt auf - belegt, dass das Gate tatsächlich verdrahtet ist und nicht
  nur isoliert unit-getestet.
- `tests/conftest.py`: Capabilities-Fix wie oben beschrieben (kein neuer
  Test, aber 5 bestehende Prozent-Tests + 2 Semantic-Command/Frame-Tests
  wären sonst rot gewesen).

**Ergebnis:** 367/367 Tests grün (362 aus Phase 11 + 4 + 1 neu),
`pytest -q` Laufzeit weiterhin < 2s. `pyflakes` clean.
