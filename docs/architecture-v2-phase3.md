# v2-Umbau, Phase 3: Normalisierung (nlu/normalize.py)

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Baseline bis Area Resolver
2.0 (Phasen 0-7)", Abschnitt "Phase 3 – Normalisierung". Vorstufe:
`docs/architecture-v2-phase2.md` (Intent-Parser-Registry).

## Was neu ist

Neue, pure Datei `nlu/normalize.py`: eine Funktion `normalize(text) ->
str`, aufgerufen als erster Schritt in `NluEngine.match()`, vor jeglichem
Parser-Aufruf.

## Empirisch geprüft, bevor etwas gebaut wurde

Gegen `hassil==3.11.0` verifiziert, dass `recognize()` bereits von sich aus
tolerant ist gegenüber: Groß-/Kleinschreibung ("MACH TREPPENLICHT AN"
matcht), überflüssigen/mehrfachen Leerzeichen ("mach   treppenlicht
   an" matcht), führenden/nachgestellten Leerzeichen, Satzzeichen am Ende
("mach Treppenlicht an." / "...an!" / "wie hoch ist ... ?" matchen alle),
und sogar ausgeschriebenen deutschen Zahlwörtern in `RangeSlotList`
("fünfzig Prozent" wird zu `percent=50`). Diese Punkte, die der Plan als
Beispiele für Normalisierung nennt, brauchten deshalb **keine** eigene
Implementierung — sie wären reine Doppelarbeit.

Der einzige Punkt, den hassil nachweislich **nicht** selbst abdeckt: das
"%"-Symbol. `RangeType.PERCENTAGE` ist nur ein Label für `RangeSlotList`,
keine Symbol-Erkennung — "50%"/"50 %" matcht ohne Normalisierung nicht.

## Was `normalize()` tut

```python
def normalize(text: str) -> str:
    text = _PERCENT_SYMBOL_RE.sub(r"\1 Prozent", text)   # "50%"/"50 %" -> "50 Prozent"
    text = _WHITESPACE_RE.sub(" ", text)                  # mehrfache -> ein Leerzeichen
    return text.strip()
```
Whitespace-Kollabierung ist bei hassil selbst redundant (s.o.), wird aber
bewusst als eigener, testbarer Normalisierungsschritt behalten - relevant
für künftige, nicht-hassil-basierte Parser (z.B. den optionalen
LLM-Adapter aus Phase 9/v3), die diese Toleranz nicht automatisch mitbringen.

Die vormals in `engine.py` ad-hoc lebende `_normalize_percent_symbol`/
`_PERCENT_SYMBOL_RE` ist nach `nlu/normalize.py` verschoben und wird jetzt
über `normalize()` aufgerufen statt direkt.

## Was bewusst NICHT gemacht wurde

Keine Lowercase-Normalisierung: `SemanticFrame.target.text` behält die
Original-Großschreibung, damit spätere Auflösungsschritte (Entity
Resolution) weiterhin auf dem tatsächlich gesprochenen Text arbeiten -
`resolve_entity()` lowercased bereits selbst zum Vergleich, eine zusätzliche
Lowercase-Stufe hier wäre eine semantische Vorentscheidung, die der Plan
explizit ausschließt ("nicht 'wohnzimmerlampe' → light.wohnzimmer, das
gehört in Resolution").

Keine ausgeschriebenen Zahlwörter für andere Fälle als `{percent}`
implementiert (z.B. Mengenangaben) - hassils eingebaute Unterstützung
deckt aktuell nur `RangeSlotList` ab, ein allgemeineres Zahlwort-Parsing
ist kein aktueller Bedarf.

## Tests

Neue Datei `tests/test_normalize.py` (6 Tests): reine Unit-Tests der
Funktion (Whitespace, beide "%"-Schreibweisen, Idempotenz, unverändert bei
Gerätenamen) plus ein End-to-End-Regressionstest gegen die echte Engine.

**Ergebnis:** 299/299 Tests grün (293 aus Phase 2 + 6 neu),
`pytest -q` Laufzeit weiterhin < 1s.
