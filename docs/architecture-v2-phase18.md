# v2-Umbau, Phase 19: Antwortsystem

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Domain-Erweiterungen
Light/Cover/Fan/Climate/Query & Response (Phasen 14-19)", Abschnitt "Phase
19 - Antwortsystem". Vorstufe: `docs/architecture-v2-phase17.md` (Query
Engine).

## Ausgangslage: jeder Fehlschlag kollabiert zu `None`

`NluEngine.match()` liefert bisher entweder ein `MatchResult` (Treffer)
oder `None` - und `None` bedeutet strukturell mindestens fünf verschiedene
Dinge: kein hassil-Template passte, ein `{name}` löste sich nicht auf
(unbekannt oder mehrdeutig), die aufgelöste Entity gehört zur falschen
Domain, ein Raumname löste sich nicht auf, oder der Command Validator
(Phase 11/12) lehnte die Capability/den Parameter ab. `conversation.py`
braucht diese Unterscheidung heute nicht - sie zeigt für jeden dieser Fälle
denselben festen `NOT_UNDERSTOOD_TEXT`. Der Plan verlangt für Phase 19
trotzdem eine strukturierte `NluResponse` (`success`/`speech`/`command`/
`error`), damit spätere Phasen (Debug-Modus, Clarification) die Ursache
auseinanderhalten können, ohne selbst durch die gesamte Matching-Pipeline
zu greifen.

## Was neu ist

Neues Modul `nlu/response.py`: `NluError`-Enum (zehn Werte - die neun
`ValidationError`-Namen aus `nlu/validator.py` 1:1 gespiegelt, plus
`NO_MATCH` für alles, was schon vor einem `SemanticCommand` scheitert) und
die `NluResponse`-Dataclass exakt in der vom Plan vorgegebenen Form.

`NluError` spiegelt `ValidationError`s neun Namen bewusst als eigenes,
eigenständiges Enum statt es direkt wiederzuverwenden: ein Konsument von
`NluResponse.error` soll gegen **einen** Typ matchen können, der auch
`NO_MATCH` (den Fall, den der Validator nie sieht) mit abdeckt - zwei Enum-
Typen im selben Feld (`ValidationError | NoMatchMarker`) hätte das nur
verkompliziert. `engine.py` mappt einen `ValidationError`-Treffer per
`NluError[validation_error.name]` auf den passenden `NluError` - Namen
müssen daher synchron gehalten werden (kein Import-Zwang zwischen den
Modulen, gleiche bewusste Kopplung wie schon bei den Climate-Temperatur-
Konstanten in Phase 17 dokumentiert).

`NluEngine` bekommt eine neue Methode `respond(text, entities) ->
NluResponse`, additiv neben dem unverändert bestehenden `match()`:

```python
def respond(self, text, entities) -> NluResponse:
    normalized = normalize(text)
    parser = self._select_parser(normalized)
    result = parser.parse(normalized, ParseContext(entities=entities))
    if result is None:
        return NluResponse(success=False, speech=None, command=None, error=NluError.NO_MATCH)

    command = build_semantic_command(result)
    validation_error = validate_command(command)
    if validation_error is not None:
        return NluResponse(success=False, speech=None, command=None, error=NluError[validation_error.name])

    match_result = self._build_match_result(result)
    if match_result is None:
        return NluResponse(success=False, speech=None, command=None, error=NluError.NO_MATCH)
    return NluResponse(success=True, speech=match_result.response_text, command=match_result.command, error=None)
```

Die frühere `match()`-Methode wurde dafür nicht umgeschrieben, sondern nur
ihre Parser-Auswahl in eine neue private `_select_parser(text)`-Methode
ausgelagert (reine Extraktion, kein Verhaltensunterschied) - `respond()`
nutzt dieselbe Auswahl, dieselbe `_build_match_result`-Kernlogik, ruft aber
zusätzlich `build_semantic_command`/`validate_command` selbst auf, um den
konkreten `ValidationError` zu erhalten, statt ihn (wie `_build_match_result`
es intern schon tut) sofort zu verwerfen.

## Bewusst in Kauf genommene doppelte Berechnung

`respond()` ruft `build_semantic_command(result)` und `validate_command(command)`
auf - beide Funktionen laufen danach ein zweites Mal innerhalb von
`_build_match_result` (das seinerseits `validate_command` erneut aufruft).
Beide Funktionen sind rein (keine I/O, kein Zustand), die doppelte
Berechnung kostet bei einer Anfrage pro Sprachbefehl nichts Messbares -
der Alternativ-Weg (`_build_match_result` so umbauen, dass es den
`ValidationError` zusätzlich zum `MatchResult` zurückgibt) hätte die
bereits von 411 Tests abgesicherte Kernfunktion anfassen müssen, ohne
einen echten Vorteil zu bringen. Gleiche Abwägung wie bei den doppelt
geführten Climate-Temperatur-Grenzwerten in Phase 17: bewusste, dokumentierte
Nicht-DRY-Entscheidung an einer Modul-Grenze statt eines invasiven Umbaus.

## Bewusste Entwurfsentscheidung: `respond()` ist noch NICHT in `conversation.py` verdrahtet

Der Plan sagt nur "Die Engine soll strukturierte Antwortdaten liefern" -
nicht, dass der bestehende Assist-Agent sein Verhalten in dieser Phase
ändern muss. `conversation.py` zeigt heute für jeden Fehlschlag denselben
festen Text; es gibt aktuell keinen Konsumenten, der `NluResponse.error`
tatsächlich unterschiedlich behandeln würde. `respond()` bleibt daher rein
additiv - genau das Muster, das dieses Projekt schon bei `SemanticFrame`
(Phase 2, viele Phasen lang ohne Konsumenten) und `SemanticCommand`/dem
Command Validator (Phase 11/12, verdrahtet aber bis heute nie tatsächlich
ablehnend) etabliert hat. Eine spätere Phase (Debug-Modus oder
Clarification, die laut Plan `error=AMBIGUOUS_ENTITY` für Rückfragen
braucht) ist der natürliche Zeitpunkt, `conversation.py` auf `respond()`
umzustellen - dann müsste sie zusätzlich `map_to_service_call(response.
command)` selbst aufrufen, da `NluResponse` bewusst kein `plan`-Feld trägt
(nur `command`; die Domain-spezifische Service-Call-Ableitung bleibt
`nlu/service_mapper.py`s alleinige Aufgabe, `NluResponse` dupliziert das
nicht).

## Was bewusst NICHT gemacht wurde

**Keine Änderung an `match()`s Signatur/Verhalten** - alle 411 bestehenden
Tests und `conversation.py` bleiben unverändert, das war das
Regressions-Sicherheitsnetz für diese Phase (siehe `git diff`: der einzige
Unterschied an `match()` selbst ist die reine Extraktion von
`_select_parser`).

**Kein `plan`-Feld in `NluResponse`** - exakt die vom Plan vorgegebene Form
(`success`/`speech`/`command`/`error`) übernommen, keine eigene Erweiterung.
Ein Konsument, der den Service-Call braucht, ruft `map_to_service_call
(response.command)` (Phase 12/13) selbst auf.

**Kein `ClarificationRequest`** - der Plan nennt das explizit als "später"
für Phase 19, nicht als Teil davon; das ist Gegenstand einer eigenen
späteren Phase (25, "Clarification").

## Tests

Neue `tests/test_engine_response.py`, fünf Fälle gegen die reale Engine
(kein handgebautes `SemanticCommand` wie in `test_validator.py` - hier
geht es um die Integration über `respond()`, nicht um den Validator
isoliert):

- Erfolgreicher Aktions-Befehl ("Mach Treppenlicht an") → `success=True`,
  `speech`/`command` gesetzt, `error=None`.
- Erfolgreiche Abfrage ("wie hoch ist die Außentemperatur?") → `success=True`,
  `speech == "18.4 Grad."`, `command` trotz `plan=None` im alten
  `MatchResult` gesetzt (Query-Commands sind vollwertige `SemanticCommand`s,
  nur ohne Service-Call).
- Kein Template-Treffer ("blubb schnarch wuppdi") → `NluError.NO_MATCH`.
- Unbekannter Gerätename → `NluError.NO_MATCH` (nicht `ENTITY_NOT_FOUND` -
  die Namensauflösung scheitert bereits im Parser, bevor ein
  `SemanticCommand` existiert, siehe `nlu/response.py`s Docstring).
- Abgelehnte Capability (Climate-Zieltemperatur auf eine Heizung ohne
  `TEMPERATURE`-Capability, gleiche Fixtures wie
  `test_engine_climate_extended.py`) → `NluError.UNSUPPORTED_CAPABILITY`,
  der einzige der neun `ValidationError`-Fälle, den ein echter Satz über
  die Engine heute tatsächlich auslösen kann (siehe `nlu/validator.py`s
  Modul-Docstring: alle anderen acht werden von den Parsern bereits vorher
  abgefangen).

**Ergebnis:** 416/416 Tests grün (411 aus Phase 18 + 5 neu), `pytest -q`
weiterhin < 1s. `pyflakes` clean.
