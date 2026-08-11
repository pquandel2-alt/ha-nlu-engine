# v2-Umbau, Phase 27: Pronomen und Referenzen

Referenz: Brain-Knoten "ha-nlu-engine v3 Plan: Rückfragen, Conversation
Context, Pronomen (Phasen 20-22)", Abschnitt "25. Phase 22 – Pronomen und
Referenzen". Vorstufe: `docs/architecture-v2-phase25.md` (Context/
Folgesatz-Merging).

## Ziel

Der Plan nennt sechs konkrete Beispielsätze: *"Mach es aus. Mach es
heller. Mach die auch an. Die Rollläden dort runter. Die andere. Die
daneben."* Regel: *"Referenzen dürfen nur auf den Conversation Context
zugreifen. Wenn keine eindeutige Referenz existiert: AMBIGUOUS_REFERENCE.
Keine zufällige Auswahl."* Anders als Phase 26 (ein Folgesatz ohne jedes
Ziel) enthalten diese Sätze ein Pronomen/eine Ortsangabe, das/die explizit
auf etwas im vorigen Turn zeigt - drei unterschiedliche Auflösungsstrategien
für sechs strukturell verschiedene Fälle.

## Architekturentscheidung: achte separate Grammatik, drei Strategien in einem Parser

Alle sechs Beispielsätze kollidieren strukturell mit nichts Bestehendem
(kein anderer Satz im Repo besteht nur aus "mach es an"/"die andere" ohne
{name}) - deshalb wie bei `ContextFollowupParser` **kein** Keyword-Router in
`engine.py` nötig: `NluEngine.match_reference()` wird von `conversation.py`
direkt versucht, mit "kein Kontext" oder "Text passt nicht" als sauberem
`None`. Gegen den echten hassil-Parser empirisch verifiziert (alle 12
Testsätze, inkl. Mischung aus slotlosen und `{domain}`-geslotteten Sätzen im
selben `Intents`-Objekt - hassil erlaubt das, solange `slot_lists` das
tatsächlich benutzte `{domain}` enthält, siehe Phase-Verifikation von
Phase 7).

`ReferenceParser` (`parsers.py`) bündelt alle drei Strategien in einer
Klasse statt drei separate Parser zu bauen, weil sie sich eine Grammatik und
einen `recognize()`-Aufruf teilen - die Verzweigung passiert danach, auf
Basis von Intent-Name und ob ein `{domain}`-Slot gefüllt wurde:

1. **Reines Pronomen** ("mach es an/aus", "schalte es an/ein/aus", "mach die
   auch an/aus", "mach es heller/dunkler") - aufgelöst direkt gegen
   `context.last_entities`, nicht gegen eine frische Entity-Liste. Für die 5
   Basis-`INTENTS` (turn_on/off) wird jede Anzahl >= 1 akzeptiert; für
   "es heller/dunkler" gilt dieselbe Scope-Entscheidung wie in Phase 26s
   `match_followup()` - genau ein Licht, sonst `None` (`LIGHT_EXTENDED_INTENTS`
   liest nur `entities[0]`).
2. **Ortsbezogene Domain-Referenz** ("Die Rollläden dort hoch/runter") -
   aufgelöst gegen eine **frische** `entities`-Liste, gefiltert auf
   `context.last_area.area_id` via `resolve_entities_by_domain()` - exakt
   dieselbe Funktion, die `QuantifierParser` schon nutzt. `last_area is
   None` liefert sauber `None` (kein Referenzpunkt für "dort" - nie raten).
3. **Unauflösbare relative Referenz** ("die andere", "die daneben") - von
   der Grammatik über einen eigenen, nicht-HA-Core-Intent-Namen
   (`HassReferenceOther`, dasselbe Präzedenzmuster wie `HassSetPercentage`
   aus der Prozent-Steuerung) erkannt, aber nie aufgelöst: liefert
   `AmbiguousReference` statt `ParseResult` - die Engine führt keine Liste
   "nicht gewählter Geschwister-Kandidaten" und kein Raummodell für
   Nachbarschaft, jeder Auflösungsversuch wäre Raten.

## `Quantifier(kind="all")`-Pflicht bei Mehrfachtreffern

`validate_command()`s Check #3 behandelt jeden Nicht-Quantifier-Befehl mit
2+ Entities als unaufgelöste Mehrdeutigkeit (`AMBIGUOUS_ENTITY`). Sowohl
Strategie 1 ("die auch an" mit 2+ `last_entities`) als auch Strategie 2
(mehrere Rollläden im gemerkten Raum) setzen deshalb `frame.quantifier =
Quantifier(kind="all")`, sobald `len(matched) > 1` - dasselbe Muster, das
`QuantifierParser` für "alle"/"beide" bereits etabliert hat. `kind="all"`
(nicht `"both"`) vermeidet außerdem Check #9 (`INVALID_QUANTIFIER`, das nur
bei `kind == "both"` eine exakte Zweierzahl erzwingt) - hier ist jede Anzahl
>= 2 gültig, es gibt keine "genau 2"-Regel wie bei "beide".

## `AmbiguousReference`/`AMBIGUOUS_REFERENCE`: definiert, bewusst noch nicht verdrahtet

`AmbiguousReference` (neu, `nlu/parser.py`, neben `ClarificationRequest`) und
`NluError.AMBIGUOUS_REFERENCE` (neu, `nlu/response.py`) folgen demselben
"Enum-Mitglied vor dem Verdrahtungs-Konsumenten bauen"-Muster wie
`AMBIGUOUS_ENTITY` (definiert seit Phase 19, erst in Phase 25 in
`respond()`/`debug()` verdrahtet). `respond()`/`debug()` rufen weiterhin nur
`self._select_parser()` auf und kennen `ReferenceParser` (wie schon
`ContextFollowupParser` seit Phase 26) gar nicht - `match_reference()`
kollabiert sowohl "Text passt zu keiner Referenz" als auch "Text passt zu
einer *unauflösbaren* Referenz" (`AmbiguousReference`) einheitlich zu `None`,
genau wie `match_followup()` das für seinen eigenen Scope schon tut. Ein
späterer Konsument (Debug-Modus, feinere Fehlertexte) kann beide Fälle bei
Bedarf unterscheiden, ohne dass diese Phase das vorwegnehmen muss.

## `engine.py`: `match_reference()` - Wiederverwendung von `_build_match_result()`

```python
def match_reference(self, text, entities, context):
    if context is None:
        return None
    normalized = normalize(text)
    result = self._reference_parser.parse(
        normalized, entities, context.last_entities, context.last_area
    )
    if result is None or isinstance(result, AmbiguousReference):
        return None
    return self._build_match_result(result)
```

Wie schon `match_followup()` in Phase 26 baut `ReferenceParser` einen
vollständigen `SemanticFrame`/`ParseResult`, der durch denselben
`_build_match_result()`-Pfad läuft wie jeder andere erfolgreiche Match -
Capability-Prüfung, Domain-Guard und Antwortformulierung (inkl.
`_plural_response()` für Mehrfachtreffer, z.B. "2 Rollläden geöffnet.")
kommen dadurch gratis, ohne eigene Logik zu duplizieren.

## `conversation.py`: Reihenfolge

```python
result = self._engine.match_followup(user_input.text, pending)
if result is None:
    result = self._engine.match_reference(user_input.text, entities, pending)
if result is None:
    result = self._engine.match(user_input.text, entities)
```

`match_followup()` zuerst (bestehende Reihenfolge aus Phase 26 unverändert),
dann `match_reference()`, zuletzt `match()`. Keine Kollisionsgefahr
zwischen den drei Pfaden: `match_followup()`s Sätze sind nackt ("etwas
heller"/"heller"), `match_reference()`s Pronomen-Sätze haben immer ein
Verb+Pronomen ("mach es heller") - empirisch gegen hassil verifiziert, dass
keine der drei Grammatiken denselben Satz strukturell matcht.

## Tests

Neue `tests/test_reference.py` (16 Fälle): kein Kontext -> `None`; Pronomen
an/aus mit einer `last_entity` -> korrekter Service-Call/Antworttext;
Pronomen "die auch an" mit 2 `last_entities` -> `Quantifier(kind="all")`,
Liste beider `entity_id`s, "2 Schalter eingeschaltet."; Pronomen ohne
`last_entities` -> `None`; "es heller/dunkler" mit genau einem dimmbaren
Licht -> korrekt; mit 2 Lichtern oder ohne Dimm-Fähigkeit -> `None`;
ortsbezogene Referenz mit einem bzw. zwei Rollläden im gemerkten Raum ->
korrekt (inkl. Pluralantwort "2 Rollläden geöffnet."); ohne `last_area` ->
`None`; falsche Domain im gemerkten Raum (Ventilator statt Rollladen) ->
`None`; "die andere"/"die daneben" -> `None` (via `AmbiguousReference`);
unpassender Satz -> `None`; Ende-zu-Ende `match()` -> Kontext bauen ->
`match_reference()`, dem Plan-Beispiel "Mach das Garagentor an." -> "Mach es
aus." folgend.

**Ergebnis:** 628/628 Tests grün (612 aus Phase 26 + 16 neue
Referenz-Fälle), `pytest -q` weiterhin < 2s. `pyflakes` clean (inkl.
`scripts/`).
