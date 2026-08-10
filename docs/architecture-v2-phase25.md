# v2-Umbau, Phase 26: Context (Folgesatz-Merging)

Referenz: Brain-Knoten "ha-nlu-engine v3 Plan: Rückfragen, Conversation
Context, Pronomen (Phasen 20-22)", Abschnitt "24. Phase 21 – Conversation
Context" (zweite Hälfte - die `ConversationContext`-Typdefinition selbst kam
schon in Phase 24). Vorstufe: `docs/architecture-v2-phase24.md`
(Clarification).

## Ziel

Der Plan nennt ein konkretes Beispiel: *"Mach das Wohnzimmerlicht an."* dann
*"Etwas heller."* - der zweite Satz hat kein eigenes `{name}`, muss sich also
auf das Ziel des vorigen Satzes beziehen. Phase 24 hatte
`ConversationContext.last_command`/`last_entities`/`last_area` bereits als
Datenstruktur gebaut, aber nie befüllt oder gelesen. Phase 26 schließt beide
Enden: `conversation.py` befüllt den Store nach jedem erfolgreichen Match,
und ein neuer Engine-Pfad liest ihn für genau diese Art von elliptischem
Folgesatz.

## Architekturentscheidung: siebte separate Grammatik statt Erweiterung einer bestehenden

`LightExtendedParser` hätte "heller"/"dunkler" schon als eigenständige Sätze
im Repertoire (`{name} ... heller` etc.) - aber genau das ist der Punkt:
diese Sätze haben *kein* `{name}`. Eine minimale, komplett neue Grammatik
(`intents/de/context_followup/brightness.yaml`, 4 Sätze: "etwas heller" /
"heller" / "etwas dunkler" / "dunkler") ist strukturell unmöglich mit jeder
bestehenden Grammatik zu verwechseln - keine von ihnen hat eine Satzform ohne
jeden Slot. Deshalb kollidiert sie mit nichts und braucht (anders als
Prozent/Quantifier/Light-Extended/Fan-Extended/Climate-Extended) **keinen**
Keyword-Router in `engine.py`: `NluEngine.match_followup()` wird von
`conversation.py` einfach *zuerst* versucht, bevor `match()` überhaupt
aufgerufen wird - "kein Kontext vorhanden" oder "Text passt nicht" liefern
beide sauber `None`.

`ContextFollowupParser` (`parsers.py`) ist deshalb strukturell einfacher als
alle sechs bisherigen Parser: kein `ParseContext`, keine
Entity-Auflösung, kein `ParseResult` - er nimmt nur Text entgegen und gibt
den erkannten Intent-Namen (`str | None`) zurück. Die eigentliche Ziel-Entity
liefert der Aufrufer aus dem Kontext.

## `NluEngine.match_followup()`: Wiederverwendung von `_build_match_result()`

```python
def match_followup(self, text, context):
    if context is None:
        return None
    matched = [e for e in context.last_entities if e.domain == "light"]
    if len(matched) != 1:
        return None
    intent = self._context_followup_parser.parse(normalize(text))
    if intent is None:
        return None
    frame = SemanticFrame(
        intent=intent,
        target=TargetReference(text=text, entity_id=matched[0].entity_id, domain=matched[0].domain),
        area=None,
        parameters={"step_percent": _DEFAULT_DIMMING_STEP_PERCENT},
        source_text=text,
    )
    return self._build_match_result(ParseResult(frame=frame, resolved_entities=matched))
```

Statt eigene Validierungs-/Formulierungs-Logik zu duplizieren, baut diese
Methode einen synthetischen `SemanticFrame`/`ParseResult` und übergibt ihn an
das bereits bestehende `_build_match_result()` - denselben Pfad, den jeder
andere erfolgreiche Match auch durchläuft. Das bringt drei Dinge gratis:

1. **Capability-Prüfung**: `validate_command()` prüft `BRIGHTNESS` für
   `HassLightBrighten`/`HassLightDim` genau wie bei jedem regulären
   Light-Extended-Match - ein Licht ohne Dimm-Fähigkeit liefert sauber
   `None` (`UNSUPPORTED_CAPABILITY`), kein Sonderfall nötig.
2. **Domain-Guard**: da `matched` schon auf `domain == "light"` gefiltert
   ist, greift der bestehende `INVALID_DOMAIN`-Check zwar nie aktiv, bleibt
   aber als Teil desselben Codepfads bestehen statt separat dupliziert zu
   werden.
3. **Antwortformulierung**: `LIGHT_EXTENDED_INTENTS["HassLightBrighten"/
   "HassLightDim"].response` liefert direkt "Bürolicht um 10 Prozent heller
   gestellt." - derselbe Text wie bei "Mach das Bürolicht heller."

Der `step_percent`-Defaultwert (10) ist derselbe `_DEFAULT_DIMMING_STEP_PERCENT`
aus Phase 14, wiederverwendet statt neu erfunden - ein Folgesatz ohne
Prozentangabe soll sich identisch verhalten wie ein Erstsatz ohne
Prozentangabe.

## Scope-Entscheidung: genau ein Licht, sonst `None`

`LIGHT_EXTENDED_INTENTS`s Antwort-Lambdas lesen nur `es[0].friendly_name`
(nicht domain-plural-fähig wie `service_call.py`s `_plural_response()`, die
die 5 Basis-Intents nutzen). Würde `match_followup()` mehrere Lichter aus dem
Kontext durchreichen, würde die Antwort nur den Namen eines einzigen Lichts
nennen, obwohl mehrere geändert würden - ein latenter, stiller Bug. Statt
diesen Pfad nachträglich multi-entity-fähig zu machen (Scope-Erweiterung, die
der Plan nicht verlangt), filtert `match_followup()` `context.last_entities`
auf `domain == "light"` und bricht bei 0 oder 2+ Treffern sauber mit `None`
ab - "nie raten" gilt auch hier: ein mehrdeutiger Kontext ist kein Grund zu
raten, welches der Lichter gemeint ist, sondern ein Grund für die normale
"nicht verstanden"-Antwort. Deckt exakt das Plan-Beispiel ab (ein Licht,
ein Folgesatz).

## Bekannte, dokumentierte Lücke: Rückfrage-dann-Folgesatz

`resolve_clarification()` (Phase 25) befüllt `MatchResult.command` nie - sie
ruft `spec.build()`/`spec.response()` direkt auf, ohne den
`build_semantic_command()`-Umweg. Eine Kette wie *"Mach das Bürolicht
an."* → *"Welches?"* → *"Büro 2"* → *"Etwas heller."* würde deshalb nach dem
dritten Turn **keinen** Kontext zum Anknüpfen finden (`conversation.py`s
neue `result.command is not None`-Prüfung greift dort nicht, der Store wird
stattdessen geleert). Bewusst nicht rückwirkend in Phase 25 nachgebessert -
das hätte bereits committeten, getesteten Code angefasst, nur um einen Fall
abzudecken, den weder der Plan noch ein gemeldeter Bug verlangt. Kandidat für
einen späteren Ausbau, falls in der Praxis gebraucht.

## `conversation.py`: Store befüllen und lesen

Der `else`-Zweig (keine offene Rückfrage) versucht jetzt zuerst
`match_followup(text, pending)`, bei `None` wie bisher `match(text,
entities)`. Nach jedem NICHT-Rückfrage-Ergebnis wird der Store aktualisiert:
`result.command is not None` → frischer `ConversationContext` mit
`last_command`/`last_entities`/`last_area` aus dem Command,
`pending_clarification=None`; sonst (Miss oder ein Ergebnis ohne `command`,
was mit dem heutigen `_build_match_result()` praktisch nie vorkommt, da es
`command` in jedem Erfolgsfall setzt) wird der Store geleert - ein Folgesatz
soll sich nie an einem gescheiterten oder sehr alten Turn orientieren.

Wie der Rest von `conversation.py` bleibt dieser Pfad ohne automatisierten
Test (kein `hass`-Mocking-Setup im Repo).

## Tests

Neue `tests/test_context_followup.py` (10 Fälle):

- `match_followup()` ohne Kontext (`None`) → `None`.
- Leerer/rein-nicht-Licht-Kontext → `None`.
- 2+ Lichter im Kontext → `None` (Scope-Entscheidung).
- "Etwas heller."/"Heller." → `HassLightBrighten`, `brightness_step_pct: 10`.
- "Etwas dunkler." → `HassLightDim`, `brightness_step_pct: -10`.
- Licht ohne `BRIGHTNESS`-Capability → `None`.
- Satz, der nicht zur Folgesatz-Grammatik passt (z.B. ein vollständiger
  Befehl) → `None` (fällt in `conversation.py` auf `match()` zurück).
- Ende-zu-Ende: `match()` für "Mach das Bürolicht an" → `command.entities`
  als Kontext gebaut → `match_followup("Etwas heller.", context)` - exakt
  der Plan-Beispielfall als Kette zweier Engine-Aufrufe.

**Ergebnis:** 612/612 Tests grün (602 aus Phase 25 + 10 neue
Context-Followup-Fälle), `pytest -q` weiterhin < 2s. `pyflakes` clean (inkl.
`scripts/`).
