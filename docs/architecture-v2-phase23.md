# v2-Umbau, Phase 24: Conversation State

Referenz: Brain-Knoten "ha-nlu-engine v3 Plan: Rückfragen, Conversation
Context, Pronomen (Phasen 20-22)", Abschnitte "23. Phase 20 – Rückfragen"
und "24. Phase 21 – Conversation Context". Vorstufe:
`docs/architecture-v2-phase22.md` (Performance/Indexing).

## Ausgangslage und Nummerierung

Der 31-Punkte-Plan listet vier aufeinanderfolgende Dialog-Phasen: 24
"Conversation State", 25 "Clarification", 26 "Context", 27
"Pronomen/Referenzen". Ihr Inhalt steht in einem eigenen Themen-Knoten mit
nur drei Abschnitten (Rückfragen, Conversation Context, Pronomen) - diese
Phase (24) baut das gemeinsame Fundament für alle drei Themen-Abschnitte:
die Zustands-Datentypen selbst, noch ohne Verdrahtung. Die drei folgenden
Plan-Phasen bauen jeweils einen Nutzungspfad darauf auf:

- Phase 25 (Clarification) verdrahtet Abschnitt 23 (Rückfragen-Dialog:
  "Welches Licht meinst du?").
- Phase 26 (Context) verdrahtet die Folgesatz-Logik aus Abschnitt 24
  ("Mach das Wohnzimmerlicht an." → "Etwas heller.").
- Phase 27 (Pronomen/Referenzen) verdrahtet Abschnitt 25 ("Mach es aus.",
  "Die andere.", ...).

## `nlu/context.py`: `ClarificationRequest` + `ConversationContext` + Store

Zwei `frozen`-Dataclasses, Feldnamen exakt aus dem Plan übernommen:

- `ClarificationRequest(pending_intent, pending_target, candidates)` - deckt
  sich mit dem Plan-Beispiel `ConversationState(pending_intent="turn_on",
  pending_target="Licht", candidates=(light.kueche, light.wohnzimmer))`.
  Umbenannt von `ConversationState` zu `ClarificationRequest`, weil der Plan
  selbst diesen Namen im `ConversationContext`-Feld `pending_clarification`
  verwendet - ein Typ, zwei Namen im Plantext wären nur verwirrend.
- `ConversationContext(last_command, last_entities, last_area,
  pending_clarification)` - identisch zum Plan-Snippet in Abschnitt 24.
  `last_command: SemanticCommand | None` und `last_area: AreaSnapshot | None`
  greifen auf bereits existierende Typen zurück (`nlu/command.py`,
  `areas.py`, seit Phase 11 bzw. 08).

`ConversationContextStore`: In-Memory-Speicher, `conversation_id` → Context,
mit TTL-basierter Ablauflogik. Der Plan nennt in seiner Testmatrix (Knoten
`9ced4390`, Abschnitt 26) nur den Testfall-Namen "context expiration", ohne
konkreten TTL-Wert - `DEFAULT_CONTEXT_TTL_SECONDS = 30.0` ist eine bewusste,
im Modul dokumentierte Annahme (deckt eine natürliche gesprochene
Folgeäußerung ab, ohne alten Zustand über viele spätere, unabhängige Befehle
in derselben HA-`conversation_id` hinweg zu behalten) - kann in Phase 26/27
bei Bedarf angepasst werden, sobald die echte Wiring-Erfahrung vorliegt.
`clock` ist injizierbar (Default `time.monotonic`) - macht TTL-Ablauf in
Tests ohne echtes Warten testbar.

## Bewusst nicht verdrahtet

Wie in den Vorphasen (`EntityIndex` in Phase 23, `debug()` in Phase 22) ist
dies reine, noch unbenutzte Infrastruktur: `conversation.py` erzeugt aktuell
weder einen `ConversationContextStore` noch liest/schreibt es
`ConversationContext`. `user_input.conversation_id` existiert im Aufrufer
bereits (siehe `conversation.py:88-98`) und ist der vorgesehene Schlüssel -
die tatsächliche Verdrahtung (Store pro `NluConversationEntity`, Context vor
`match()` lesen, danach schreiben) ist Aufgabe von Phase 25/26, sobald klar
ist, welcher Aufrufer-seitige Ablauf (Rückfrage-Antwort erkennen, Pronomen
auflösen) tatsächlich gebraucht wird - vorzeitige Verdrahtung würde hier nur
Annahmen einfrieren, die noch nicht validiert sind.

## Tests

Neue `tests/test_conversation_context.py` (5 Fälle): unbekannte
`conversation_id` → `None`, Roundtrip (set/get liefert denselben Context
inkl. `ClarificationRequest`), `clear()` entfernt einen Eintrag, TTL-Ablauf
(injizierter Fake-Clock: kurz vor/nach der Grenze), zwei `conversation_id`s
bleiben unabhängig voneinander.

**Ergebnis:** 594/594 Tests grün (589 aus Phase 23 + 5 neue
`ConversationContext`/Store-Fälle), `pytest -q` weiterhin < 2s. `pyflakes`
clean (inkl. `scripts/`).
