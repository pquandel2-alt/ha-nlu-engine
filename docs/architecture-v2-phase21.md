# v2-Umbau, Phase 22: Debug-Modus

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Golden/Negative Tests,
Debug-Modus, Performance (Phasen 23-27, 29-30)", Abschnitt "29. Logging /
Debug-Modus". Vorstufe: `docs/architecture-v2-phase20.md` (Negative Tests).

## Ausgangslage

Der Plan verlangt einen optionalen Trace-Modus, der jede Pipeline-Stufe für
eine Äußerung sichtbar macht - Parser-Auswahl, Intent, Ziel-/Raumtext,
aufgelöste Entities, Capabilities, das gebaute Command, Validierungsergebnis,
Service-Call. Ausdrücklich kein Pflichtfeature für normale Nutzer ("Kein
Debugging von normalen Nutzern verlangen").

## `nlu/debug.py`: `DebugTrace` + `format_command()`

`DebugTrace` ist ein `frozen`-Dataclass mit genau den vom Plan genannten
Feldern (`input`, `normalized`, `parser`, `intent`, `target`, `area`,
`candidates`, `resolution`, `capabilities`, `command`, `validation`,
`service`, `data`) plus einer `.format()`-Methode, die die Plan-Beispielform
zeilenweise nachbildet (`INPUT:`/`NORMALIZED:`/.../`DATA:`, `-` als
Platzhalter für leere Felder). `parser` ist ein zusätzliches, vom Plan nicht
genanntes Feld - sinnvoll, weil die Engine intern zwischen sechs Parsern
wählt (`_select_parser()`) und genau das eine der interessantesten
Debug-Fragen ist ("welcher der sechs Parser hat gegriffen?").

`format_command()` rendert `SemanticCommand` kompakt als `intent(k=v, ...)`
(Plan-Beispiel: `adjust_brightness(+small)`) statt eines vollen
Dataclass-`repr()`, der jede aufgelöste `EntitySnapshot` mit ausgeben würde.

## `NluEngine.debug()`: gleiche Struktur wie `respond()`, aber jede Stufe sichtbar

Dupliziert bewusst dieselben kleinen, günstigen, reinen Aufrufe
(`_select_parser` → `parser.parse` → `build_semantic_command` →
`validate_command` → bei Erfolg `_build_match_result`), statt
Trace-Sammlung durch die bestehende `_build_match_result` zu fädeln -
derselbe dokumentierte Trade-off wie bei `respond()` selbst (siehe dessen
Docstring, Phase 19).

Vier Zweige, je ein Testfall in `tests/test_engine_debug.py`:

1. **Erfolgreicher Aktionsbefehl** - alle Felder befüllt, `service`/`data`
   aus dem `ServiceCallPlan`.
2. **Erfolgreiche Abfrage** - `validation == "OK"`, aber `service`/`data`
   bleiben `None` (Abfragen haben `plan is None`, siehe Phase 18).
3. **Kein Template-Treffer** - nur `input`/`normalized`/`parser` gesetzt,
   alles andere `None`/leer, `validation == "NO_MATCH"`.
4. **Validierungs-Ablehnung** - Parser matcht, `SemanticCommand` wird
   gebaut, aber `validate_command()` liefert einen Fehler (Beispiel:
   `UNSUPPORTED_CAPABILITY` bei einer Heizung ohne `TEMPERATURE`) -
   `service`/`data` bleiben `None`.

## Bewusste Einschränkung: CANDIDATES/RESOLUTION nur der finale Treffer

Der Plan zeigt in seinem Beispiel `CANDIDATES: light.wohnzimmer = 132,
light.kueche = 12` - also alle erwogenen Kandidaten samt Score, nicht nur
den Gewinner. Das würde eine Restrukturierung aller sechs
`IntentParser.parse()`-Implementierungen erfordern: sie geben heute
`ParseResult | None` zurück und verwerfen damit die intern von
`resolve_entity()`/`resolve_entity_scored()`/`resolve_area_name()`
berechneten, reicheren `ResolveResult`/`AreaResolveResult`-Objekte auf dem
Fehlerpfad (ein Non-Match und ein mehrdeutiger/nicht aufgelöster `{name}`
kollabieren beide zu `None`, siehe `nlu/response.py`s Docstring).

Da der Plan das Feature selbst als optional bezeichnet und ausdrücklich
nicht für normale Nutzer verlangt, wurde diese Restrukturierung als
außerhalb des Scopes dieser Phase eingestuft. `CANDIDATES`/`RESOLUTION`
zeigen deshalb nur die final aufgelöste(n) Entity/Entities - dieselbe
Granularität, die `respond()`/`NluResponse` bereits nach außen gibt, nicht
mehr. Dokumentiert in `nlu/debug.py`s Moduldocstring und
`NluEngine.debug()`s Docstring; kann bei tatsächlichem Bedarf als eigener
Folgeschritt nachgezogen werden.

## Nicht verdrahtet

Wie im Plan gefordert kein Anschluss an `conversation.py` oder einen HA
Service - `debug()` ist eine reine Engine-Methode, aufrufbar direkt (analog
zu `match()`/`respond()` vor ihrer jeweiligen Anbindung).

## Tests

**Ergebnis:** 584/584 Tests grün (579 aus Phase 21 + 5 neue Fälle in
`tests/test_engine_debug.py`), `pytest -q` weiterhin < 2s. `pyflakes` clean
(inkl. `scripts/`).
