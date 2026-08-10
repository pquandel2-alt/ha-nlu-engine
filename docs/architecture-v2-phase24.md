# v2-Umbau, Phase 25: Clarification

Referenz: Brain-Knoten "ha-nlu-engine v3 Plan: Rückfragen, Conversation
Context, Pronomen (Phasen 20-22)", Abschnitt "23. Phase 20 – Rückfragen".
Vorstufe: `docs/architecture-v2-phase23.md` (Conversation State - Fundament,
noch unverdrahtet).

## Ziel

Phase 24 hatte `ClarificationRequest`/`ConversationContext`/
`ConversationContextStore` als reine, unbenutzte Infrastruktur gebaut. Phase
25 verdrahtet den ersten der drei Nutzungspfade: ein Name, der auf mehr als
eine gleich gut bewertete Entity trifft ("Bürolicht" in zwei Räumen),
antwortet jetzt mit einer echten Rückfrage ("Welches Licht meinst du?")
statt mit der bisherigen festen "nicht verstanden"-Antwort - und der nächste
Nutzer-Turn kann diese Rückfrage auflösen.

Das ist exakt die Restrukturierung, die Phase 22s `debug()`-Docstring schon
als zukünftig nötig markiert hatte ("CANDIDATES/RESOLUTION only ever show
the parser's *final* resolved entity/entities ... without restructuring
every IntentParser's return type") - Phase 7 (Entity Resolver 2.0) hatte
`ResolveStatus.AMBIGUOUS`/`candidates` schon lange geliefert, aber jeder
Parser hat das bis jetzt zu `None` kollabiert.

## `ClarificationRequest` zieht nach `nlu/parser.py` um (Circular-Import-Fix)

Der naheliegende Ort für `ClarificationRequest` wäre `nlu/context.py`
gewesen (dort war die Dataclass in Phase 24 auch definiert). Sobald
`parsers.py`/`engine.py` sie aber als Rückgabetyp von `IntentParser.parse()`
brauchen, entsteht ein Zyklus: `nlu/parser.py` → `nlu/context.py` (für
`ClarificationRequest`) → `nlu/command.py` (für `SemanticCommand`) →
`nlu/parser.py` (für `ParseResult`). `pytest` schlug entsprechend mit einem
`ImportError: cannot import name 'SemanticCommand' from partially
initialized module 'ha_nlu.nlu.command'` fehl.

Fix: `ClarificationRequest` lebt jetzt in `nlu/parser.py` selbst (arguably
ihr natürlicherer Ort ohnehin - der alternative Parser-Ausgang neben
`ParseResult`/`None`), `nlu/context.py` importiert sie von dort und
re-exportiert sie über `__all__`, damit `ConversationContext` sie weiter
ohne Bruch referenzieren kann.

## `IntentParser`-Protocol und `SingleTargetParser`

`IntentParser.parse()`s Signatur wurde auf
`ParseResult | ClarificationRequest | None` erweitert - einheitlich auf dem
Protocol, nicht nur bei `SingleTargetParser`, damit `engine.py` den Fall
unabhängig vom erzeugenden Parser gleich behandeln kann.

Implementiert ist der neue Ausgang aber **nur** in `SingleTargetParser`
(die 5 Basis-Intents `HassTurnOn/Off/Toggle/OpenCover/CloseCover`):

```python
resolved = resolve_entity(name, context.entities)
if resolved.status is ResolveStatus.AMBIGUOUS:
    if INTENTS.get(result.intent.name) is not None:
        return ClarificationRequest(
            pending_intent=result.intent.name, pending_target=name, candidates=resolved.candidates,
        )
    return None
```

`QUERY_INTENTS` (Sensor-Abfragen) bleibt bewusst außen vor: eine Abfrage
braucht keine weiteren Parameter, und eine mehrdeutige Sensor-Benennung ist
selten genug, dass der zusätzliche Rückfrage-Umweg den Mehrwert nicht
rechtfertigt. Die vier "Extended"-Parser (Percentage, Light/Fan/Climate-
Extended) sind ebenfalls ausgeklammert - ihre Intents brauchen zusätzliche
Parameter (Prozent, Farbe, Stufe, Temperatur), die `ClarificationRequest`
strukturell nicht mitführt; eine Rückfrage müsste diese Parameter über den
Dialog-Turn hinweg zwischenspeichern, was `ConversationContext` heute noch
nicht vorsieht (Kandidat für einen späteren Ausbau, falls in der Praxis
gebraucht).

## `engine.py`: Rückfrage stellen, Rückfrage auflösen

`MatchResult` bekommt ein neues Feld `clarification: ClarificationRequest |
None = None`. Es hat Vorrang vor der bisherigen `plan is None`-Unterscheidung
(erfolgreiche Abfrage vs. Aktion, seit Phase 18/19) - beide haben
`plan=None`, bedeuten aber Unterschiedliches ("hier ist die Antwort" vs.
"frag nach, bevor du etwas tust"). Aufrufer müssen deshalb zuerst
`clarification` prüfen.

`match()` erkennt `isinstance(result, ClarificationRequest)` und baut die
Frage über `_clarification_question()`:

```python
_DOMAIN_QUESTION_WORD_DE = {
    "light": "Welches Licht", "switch": "Welchen Schalter", "cover": "Welche Rollläden",
    "fan": "Welchen Ventilator", "climate": "Welche Heizung",
}
```

Grund für die Lookup-Tabelle statt eines generischen Musters: Deutsch hat
grammatisches Geschlecht ("Welches Licht" vs. "Welchen Schalter"), das sich
nicht aus dem Domain-String ableiten lässt, ohne zu raten - dieselbe
Begründung wie `service_call.py`s bereits bestehendes
`_DOMAIN_PLURAL_DE`. Bei gemischten Domains oder unbekannter Domain greift
ein neutraler Fallback: "Das war nicht eindeutig. Welches meinst du?".

`resolve_clarification(reply_text, clarification, entities)` ist der neue
zweite Turn. "Nie raten" gilt auch hier: sie liefert nur dann ein Ergebnis,
wenn die Antwort die Kandidaten auf **genau einen** eindeutig einschränkt -
sonst `None`, genau wie jeder andere Non-Match in dieser Engine. Zwei
Auflösungswege, in dieser Reihenfolge:

1. **Name innerhalb der Kandidaten**: `resolve_entity(reply, candidates)` -
   bewusst nur gegen `clarification.candidates`, nicht die volle
   `entities`-Liste, damit eine kurze Antwort wie "Küche" nicht versehentlich
   eine völlig unbeteiligte Entity außerhalb der ursprünglichen Kandidaten
   trifft.
2. **Raum innerhalb der Kandidaten**: `resolve_area_name(reply, entities)` -
   hier gegen die volle Entity-Liste (Raumauflösung braucht den vollen
   Kontext, um Eindeutigkeit zu beurteilen), das Ergebnis wird danach auf
   die Kandidaten gefiltert; nur akzeptiert, wenn genau eine Kandidatin in
   diesem Raum liegt.

Beide Wege scheitern → `None`. Bei Erfolg wird `INTENTS[pending_intent]`
nachgeschlagen und direkt `spec.build([entity])`/`spec.response([entity])`
aufgerufen (kein `map_to_service_call`-Umweg wie bei einem frischen Match,
weil hier keine erneute `SemanticCommand`/Validator-Runde nötig ist - der
Intent war beim ersten Turn bereits validiert).

`respond()` gibt bei `isinstance(result, ClarificationRequest)`
`NluResponse(success=False, speech=None, command=None,
error=NluError.AMBIGUOUS_ENTITY)` zurück - `AMBIGUOUS_ENTITY` existierte im
`NluError`-Enum bereits seit Phase 19, aber ungenutzt.

`debug()` bekommt einen neuen Zweig direkt nach dem `result is None`-Fall:
`intent`/`target` aus der `ClarificationRequest`, `candidates` aus ihren
Kandidaten-`entity_id`s, `validation="AMBIGUOUS_ENTITY"`, alles andere
`None`/leer - die einzige Ausnahme von der in Phase 22 dokumentierten
Einschränkung, dass `debug()` nur den *finalen* Match zeigen kann, nicht
verworfene Alternativen.

## `conversation.py`: Store an- und auslesen

`NluConversationEntity` bekommt einen eigenen
`ConversationContextStore()`. `_async_handle_message()` prüft zuerst, ob
für die aktuelle `conversation_id` eine offene `pending_clarification`
existiert:

- Ja → die Antwort geht an `resolve_clarification()`, nicht an `match()`
  (eine Antwort wie "Das im Wohnzimmer" ist für sich genommen kein
  vollständiger Befehl). Der Store-Eintrag wird danach in jedem Fall
  gelöscht (`clear()`) - eine gescheiterte Auflösung führt zur normalen
  "nicht verstanden"-Antwort, nicht zu einer erneuten Rückfrage-Schleife.
- Nein → normaler `match()`-Aufruf wie bisher.

Liefert das Ergebnis eine neue `clarification`, wird sie im Store abgelegt
(`last_command`/`last_entities`/`last_area` bleiben `None`/leer - die
gehören erst Phase 26/27) und die Frage gesprochen, ohne einen Service-Call
auszulösen.

Wie der Rest von `conversation.py` bleibt dieser Pfad ohne automatisierten
Test (kein `hass`-Mocking-Setup im Repo, dokumentierte Alt-Einschränkung
seit v1).

## Tests

Neue `tests/test_clarification.py` (8 Fälle), mit zwei lokal definierten
`EntitySnapshot`s, die absichtlich denselben `friendly_name` ("Bürolicht")
in zwei verschiedenen Räumen tragen (`Büro 1`/`Büro 2`) - keine bestehende
Fixture in `conftest.py` hatte einen echten Namens-Gleichstand:

- `SingleTargetParser.parse()` liefert `ClarificationRequest` bei
  Namens-Gleichstand.
- `NluEngine.match()` liefert `MatchResult(clarification=..., plan=None,
  response_text="Welches Licht meinst du?")`.
- `resolve_clarification()` löst per Name auf (über einen Alias, der nur
  einer der beiden Kandidatinnen zugeordnet ist - der bloße Name
  "Bürolicht" bleibt auch innerhalb der zwei Kandidaten mehrdeutig, das ist
  gerade der Punkt).
- `resolve_clarification()` löst per Raum auf.
- `resolve_clarification()` liefert `None` bei unauflösbarer bzw. weiterhin
  mehrdeutiger Antwort.
- `respond()` liefert `NluError.AMBIGUOUS_ENTITY`.
- `debug()` liefert einen Trace mit `validation="AMBIGUOUS_ENTITY"` und
  befüllten `candidates`.

**Ergebnis:** 602/602 Tests grün (594 aus Phase 24 + 8 neue
Clarification-Fälle), `pytest -q` weiterhin < 2s. `pyflakes` clean (inkl.
`scripts/`).
