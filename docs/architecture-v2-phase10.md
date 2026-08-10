# v2-Umbau, Phase 10: Semantic Commands

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Quantifier, Capability,
Command, Validator, ServiceMapper (Phasen 8-13)", Abschnitt "Phase 10 –
Semantic Commands".
Vorstufe: `docs/architecture-v2-phase9.md` (Capability System).

## Was neu ist

Neue Datei `nlu/command.py`:

```python
@dataclass(frozen=True)
class SemanticCommand:
    intent: str
    entities: tuple[EntitySnapshot, ...]
    area: AreaSnapshot | None
    parameters: Mapping[str, Any]
    source_frame: SemanticFrame

def build_semantic_command(result: ParseResult) -> SemanticCommand: ...
```

`SemanticFrame` (Phase 1/2) beschreibt *was gesagt wurde* (Text-Referenzen:
`TargetReference.text`, `AreaReference.text`) - `SemanticCommand` ist das
vollständig aufgelöste Gegenstück (echte `EntitySnapshot`/`AreaSnapshot`-
Objekte). Das Bauen ist rein mechanisch: ein `IntentParser` hat zum
Zeitpunkt, an dem sein `ParseResult` existiert, Resolution bereits
vollständig durchgeführt - `build_semantic_command()` fügt nur zusammen, was
schon da ist, ohne eigene Matching-/Resolution-Logik.

Die `area`-Auflösung baut ein `AreaSnapshot` (id + kanonischer Name) aus den
bereits aufgelösten Entities' eigenen `area_id`/`area_name`-Feldern -
dieselbe Quelle, die `areas.py`s `_area_snapshots()` selbst nutzt (Phase 7) -
statt aus `frame.area.text` (das ist die gesprochene Formulierung, nicht
notwendigerweise der kanonische Registry-Name).

`engine.py`s `MatchResult` bekommt ein neues, rein additives Feld
`command: SemanticCommand | None = None`, gebaut in `_build_match_result()`
für alle drei Zweige (Single-Target, Quantifier, Percentage/Query) -
identisches Muster zu Phase 1/2s `frame`-Feld: `plan`/`response_text`
bleiben unverändert die Quelle des tatsächlichen Verhaltens.

## Was bewusst NICHT gemacht wurde

**Kein Verbraucher von `MatchResult.command`** - der Command Validator, der
diese Struktur tatsächlich prüft (Fehlerklassen wie `UNSUPPORTED_CAPABILITY`,
Phase 11 des Plans, nächste Phase), existiert noch nicht. Bis dahin wird
`command` korrekt gebaut, aber nirgends gelesen - dieselbe Zwischenstufe wie
schon bei Phase 5s Alias-Feld vor Phase 6s Resolver oder Phase 9s
Capability-Feld vor diesem Validator.

**Keine Umbenennung von `intent`** - der Plan zeigt Beispiel-Intents wie
`"set_brightness"`/`"adjust_brightness"` (semantische Verben), aber
`SemanticCommand.intent` übernimmt weiterhin die rohen hassil-Intent-Namen
(`"HassTurnOn"`, `"HassSetPercentage"`, ...) - eine Verb-Übersetzungsschicht
ist an keiner Stelle des bisherigen Plans (Phasen 0-10) explizit gefordert
und würde eine neue, ungeplante Abstraktion einführen.

**Keine Parameter-Umbenennung** - `parameters` wird 1:1 von `frame.parameters`
übernommen (z.B. `{"percent": 40}`), nicht in domain-spezifische Namen wie
`brightness_pct` übersetzt. Diese Übersetzung ist explizit Aufgabe des
`ServiceMapper` (Phase 13 des Plans) - sie hier vorwegzunehmen würde zwei
Migrationsschritte vermischen (dasselbe Prinzip wie in Phase 6/7 schon
angewendet).

## Tests

Neue Datei `tests/test_semantic_command.py` (5 Tests), im selben Stil wie
`test_semantic_frame.py`: Single-Target (aufgelöste Entity, kein Area),
Percentage (Parameter durchgereicht), Quantifier mit Area (`AreaSnapshot`
korrekt aus den Entities gebaut), Quantifier ohne Area (`area is None`),
kein Treffer → `None` (kein Command).

**Ergebnis:** 345/345 Tests grün (340 aus Phase 9 + 5 neu),
`pytest -q` Laufzeit weiterhin < 1s. `pyflakes` clean.
