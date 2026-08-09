# v2-Umbau, Phase 2: Intent-Parser-Registry (Intent-System vereinheitlichen)

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Baseline bis Area Resolver
2.0 (Phasen 0-7)", Abschnitt "Phase 2 – Intent-System vereinheitlichen".
Vorstufe: `docs/architecture-v2-phase1.md` (SemanticFrame eingeführt).

## Was neu ist

`nlu/parser.py` (pure, HA-/hassil-frei): `ParseContext`, `ParseResult`,
das `IntentParser`-Protocol (`parse(text, context) -> ParseResult | None`).

Neue Datei `parsers.py` (außerhalb von `nlu/`, da hassil-abhängig): drei
konkrete `IntentParser`-Implementierungen, die die bisherige Sprachlogik
aus `engine.py`s `_match_single`/`_match_quantifier`/`_match_percentage`
1:1 übernehmen — `SingleTargetParser`, `QuantifierParser`,
`PercentageParser`. Jede kapselt eine der drei separat kompilierten
hassil-Grammatiken vollständig, inkl. Slot-Listen
(`_DOMAIN_SLOT_LIST`/`_QUANTIFIER_SLOT_LIST`) und
`_strip_locative_prepositions` (aus `engine.py` hierher verschoben, da nur
noch hier gebraucht). Jeder Parser gibt bei Erfolg ein `ParseResult`
(`frame` + `resolved_entities`) zurück, sonst `None` - inklusive der
Domain-Allowed-Prüfung (die bestimmt, ob ein Match überhaupt gültig ist,
gehört fachlich zur Auflösung, nicht zur ServiceCall-Erzeugung).

Der Plan erlaubt explizit "eine gemeinsame hassil-basierte Parser-Schicht,
wenn sich dadurch die vorhandene Grammatik besser nutzen lässt" statt
eines Parsers pro einzelnem Intent (TurnOnParser/TurnOffParser/...) - hier
gewählt: ein Parser pro Grammatik-Grenze (dieselbe Grenze, die bereits die
drei-Wege-Kollisionsvermeidung erzwingt), da die drei Intents pro Grammatik
(z.B. HassTurnOn/Off/Toggle im `{name}`-Wildcard) ohnehin identisch
verarbeitet werden.

`engine.py` ist jetzt ein reiner Orchestrator:
```python
def match(self, text, entities):
    text = _normalize_percent_symbol(text)
    parser = self._percentage_parser if _PERCENT_RE.search(text) \
        else self._quantifier_parser if _QUANTIFIER_RE.search(text) \
        else self._single_parser
    result = parser.parse(text, ParseContext(entities=entities))
    if result is None:
        return None
    return self._build_match_result(result)
```
`_build_match_result` ersetzt die drei vormals dupliziert an jeder
Match-Stelle stehenden `MatchResult(...)`-Konstruktionen durch eine
einzige, die anhand von `frame.intent`/`frame.parameters["percent"]`
zwischen `QUERY_INTENTS`, `PERCENT_INTENTS` (Domain-Lookup) und `INTENTS`
unterscheidet.

## Was bewusst NICHT geändert wurde

Die drei separat kompilierten hassil-`Intents`-Objekte und die
Regex-Vorauswahl (`_PERCENT_RE`/`_QUANTIFIER_RE`) bleiben - das ist eine
strukturelle Kollisionsvermeidung (siehe `docs/architecture-v1.md`), keine
"Sprachlogik", die der Plan aus `engine.py` verbannen wollte, und keine
Grammatik-Änderung. Kein Verhalten wurde geändert: dieselben Sätze matchen
identisch wie vorher (Regressionsschutz: alle 282 v1-Tests unverändert
grün, plus die in Phase 1 hinzugekommenen Frame-Tests).

## Tests

Neue Datei `tests/test_parsers.py` (5 Tests): prüft, dass alle drei
konkreten Parser das `IntentParser`-Protocol erfüllen (`runtime_checkable`)
und ruft sie direkt (unabhängig von `NluEngine.match()`s Routing) auf, um
`ParseResult`/`None`-Rückgabe zu pinnen.

**Ergebnis:** 293/293 Tests grün (288 aus Phase 1 + 5 neu),
`pytest -q` Laufzeit weiterhin < 1s.
