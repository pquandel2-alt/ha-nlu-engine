# v4.2 / v4.2.1 – Semantic Query Engine

Referenz: zwei aufeinanderfolgende Pläne, beide innerhalb von v4 (Advanced
Natural Language) verortet, aber mit eigener Abschnittsnummerierung:

1. **"HomeIntent V4.2 – Semantic Query & State Resolution"** (Plandatei
   `greedy-wobbling-hearth.md`, Milestones 0-7) - führt die drei neuen
   Query-Intents und die `binary_sensor`-Domain überhaupt erst ein.
2. **"HomeIntent v4.2.1 – Semantic Query Engine: Stabilisierung und
   Architektur-Fertigstellung"** (49 Abschnitte, 10 Pflicht-Phasen) - baut
   auf V4.2 auf, schreibt **nichts** davon neu, sondern (a) validiert es
   vollständig, (b) trennt die interne Query-Architektur sauber von der
   Command-Pipeline, (c) macht die Query Engine für ein künftiges V5
   wiederverwendbar.

`docs/architecture-v4.md` dokumentiert V4.1-V4.9 (Sprachbausteine,
Zahlen, implizite Targets, Vergleiche, temporale Ausdrücke, Multi-Step,
Cross-Sentence References) - dieses Dokument ergänzt es um die
Query-Engine-spezifischen Abschnitte, die dort aus historischen Gründen
(andere Plan-Quelle, andere Nummerierung) nicht enthalten sind.

## V4.2 – Semantic Query & State Resolution (Grundlage)

Ausgangsproblem: zwei Sätze crashten mit "Unexpected error during intent
recognition" statt einer sauberen Antwort, und mehrere Zustandsabfragen
("Welche Fenster sind noch geöffnet?", "Ist das Fenster im Schlafzimmer
geöffnet?") konnten strukturell nicht funktionieren - der Engine fehlte
jedes Konzept von "lies den aktuellen Zustand mehrerer/eines Entities und
antworte boolesch/als Liste/als Anzahl", und Fenster-/Tür-Kontakte
(`binary_sensor`) erreichten die Pipeline überhaupt nicht.

Kernstücke (Commit `5135345`, Folge-Fixes `a9b078b`/`ec507ba`/`b188cab`):

- **`binary_sensor`** zur `SELECTABLE_DOMAINS`-Liste hinzugefügt.
- **`nlu/semantic_state.py`** (neu): die eine Stelle, die weiß, dass ein
  `cover`s `state=="open"` und ein Fenster-/Tür-`binary_sensor`s
  `state=="on"` dasselbe bedeuten - datengetriebene Mapping-Tabelle
  (`SemanticState.OPEN/CLOSED/ON/OFF/UNKNOWN`), nicht verstreute
  `if`-Ketten. `device_class` entscheidet die Semantik: ein
  `binary_sensor` mit `device_class in {window, door, opening,
  garage_door}` mappt `on/off` auf OPEN/CLOSED, jeder andere
  `binary_sensor` (motion, moisture, smoke, ...) auf ON/OFF - nie
  hartkodiert eine Bedeutung. `unavailable`/`unknown` -> UNKNOWN, matched
  nie einen angefragten Filter (Regel 4, nie raten).
- **Drei neue Intents**, eine 13. separat kompilierte hassil-Grammatik
  (`intents/de/state_query/`): `HassStateQuery` (Liste/Anzahl - "welche
  Fenster sind offen", "wie viele Fenster sind offen"), `HassCheckState`
  (einzelne Ja/Nein-Frage - "ist das Fenster im Schlafzimmer offen"),
  `HassExistsQuery` (Existenz - "gibt es offene Fenster").
- **`StateQueryParser`** (`parsers.py`) - wie `ComparisonQueryParser`
  Regel 6 folgend: nutzt `resolve_area_scored`/`resolve_entities_by_domain`/
  `resolve_entity_scored` verbatim, kein eigenes Suchsystem.
  `HassStateQuery`/`HassExistsQuery` sind die **eine bewusste Ausnahme**
  von der sonst codebase-weiten Regel "ein Mehrfach-Entity-Parser gibt nie
  eine leere `resolved_entities`-Liste zurück": 0 Treffer ist hier eine
  gültige, korrekte Antwort ("Keine Fenster sind offen."), kein Miss.
  `HassCheckState` bleibt bei "nie raten": mehrdeutiger/unauflösbarer Name
  -> `None`, kein Rückfrage-Turnaround.
- **Validator-Erweiterung**: `QueryIntentSpec.allows_empty` (Default
  `False`) lässt Check #2 (leere `command.entities`) für die drei neuen
  Intents gezielt passieren, ohne bestehende Intents zu berühren.
- **`AreaReference.area_name`** (neu, `nlu/frame.py`) schließt eine Lücke,
  bei der eine leere Ergebnismenge (0 offene Fenster im Keller) die Area
  selbst nicht mehr über die Entities ableiten konnte, obwohl sie korrekt
  aufgelöst war.
- **`response.response_type = QUERY_ANSWER`** in `conversation.py` für
  alle `QUERY_INTENTS`-Treffer (statt HA-Default `ACTION_DONE`).
- **27 golden Testfälle** (`tests/golden/state_query.json`), generiert über
  `scripts/generate_golden_tests.py`s bestehendes Muster.

## V4.2.1 – Stabilisierung und Architektur-Fertigstellung

Ziel laut Plan: **keine Neuimplementierung** der Query Engine, sondern (1)
v4.2.0 vollständig validieren, (2) den echten HA-Anwendungsfall zuverlässig
absichern, (3) Query-Architektur sauber von Commands trennen, (4)
bestehende Funktionalität erhalten, (5) die Query Engine für ein
künftiges V5 wiederverwendbar machen. Pflicht-Reihenfolge, 10 Phasen,
nach jeder Phase die volle Suite grün.

**Phase 1-2 (Audit + Regressionstests):** v4.2.0-Code vollständig gegen
den Plan geprüft; Kernsatz + 10 benannte Varianten regressionsgetestet.
Ein Grammatik-Fund dabei: "Mach das Licht noch heller." fiel komplett auf
NO_MATCH durch (`light_extended/color_brightness.yaml` hatte keinen
`[noch]`-Slot) - ergänzt, gleiche "`noch` nie global strippen, nur gezielt
als Grammatik-Füllwort"-Präzedenz wie `state_query.yaml`s eigenes
`[noch]`.

**Phase 3 (Conversation-Pipeline-Integrationstest):**
`tests/test_conversation_integration.py` (5 Tests) treibt
`NluConversationEntity._async_handle_message()`s echte Orchestrierung
end-to-end, ohne das schwere `homeassistant`-Paket zu installieren - über
ein `sys.modules`-Injection-Stub-Pattern (`tests/_ha_stub.py`), das nur
die tatsächlich importierten HA-Symbole nachbildet (`intent`,
`conversation`, `core`, `config_entries`, die relevanten `helpers.*`-
Registries). Deckt ab: Command-Turn ruft den Service auf und antwortet
`ACTION_DONE`; State-Query-Turn antwortet `QUERY_ANSWER` **ohne**
Service-Call (Regel 3); unverstandener Satz -> `NOT_UNDERSTOOD_TEXT`;
Service-Call-Exception -> sauberes `FAILED_TO_HANDLE` statt "Unexpected
error" (Milestone-0-Regression); Pronomen-Folgesatz nutzt den Kontext der
Vorrunde weiter.

**Phase 4-6 (neue Typen, read-only Executor, separierter
ResponseGenerator):** das eigentliche 3-Stufen-Modell aus Abschnitt 12 des
Plans, siehe eigener Abschnitt unten.

**Phase 7 (nicht-destruktive Migration):** `StateQueryParser`s drei
`_parse_*`-Methoden bauen jetzt einen `QueryCommand` und lassen ihre
Kandidatenliste durch den geteilten `QueryExecutor` laufen statt durch eine
private Ad-hoc-`matches_semantic_state`-Listcomprehension - dieselbe
Filterregel, nur an einer Stelle konsolidiert. Das Ergebnis landet
zusätzlich in `frame.parameters["query_command"]`, erreichbar über
`result.command.parameters["query_command"]` nach jedem `engine.match()`.
Die tatsächliche Antworttext-Erzeugung bleibt bewusst unverändert auf
`service_call.py`s `QUERY_INTENTS`-Response-Lambdas - Phase 6 hat bereits
byte-identische Ausgabe zwischen beiden Pfaden bewiesen, ein Umklemmen des
Call-Sites hätte `engine.py`s geteilten Dispatch für null Verhaltensgewinn
angefasst (Abschnitt 13, "keine unnötigen Änderungen"). `ResponseGenerator`
existiert also bewusst parallel zur produktiven Antwortlogik, nicht als
deren Ersatz.

**Phase 8 (Query-Follow-ups erweitert):**
`NluEngine.match_query_followup()` konnte bis dahin nur ein `HassGetState`
fortsetzen ("Wie warm ist es im Wohnzimmer?" -> "Und in der Küche?"). Jetzt
zusätzlich `HassStateQuery`/`HassCheckState`/`HassExistsQuery` ("Welche
Fenster sind offen?" -> "Und im Bad?", "Ist das Fenster Keller offen?" ->
"Und im Bad?"): `QueryFollowupParser` liest dafür den vorherigen
`QueryCommand` (statt wie bisher `last_entities[0]`) und übernimmt
Domain/`device_class`/Zustandsfilter/Scope unverändert, nur die
Area/Etage wird neu aufgelöst und erneut durch `_QUERY_EXECUTOR` gejagt.
LIST/COUNT/EXISTS behalten dabei die "leer ist eine normale Antwort"-Regel
(0 Treffer im Bad -> "Keine Fenster sind offen.", kein Miss);
`HassCheckState` (SINGLE) verweigert weiterhin bei 0 oder 2+ Treffern in
der neuen Area (nie raten). Kleiner additiver Fix dafür in
`_parse_check_state`: `QueryTarget.device_class` wird jetzt mitgeführt
(vorher nur `domain`) - für den ursprünglichen Einzel-Turn wirkungslos
(nur `entity_id` entscheidet Mitgliedschaft), gibt dem Follow-up aber
etwas zum Neu-Scopen ("Fenster", nicht nur "irgendein binary_sensor") in
die Hand. 7 neue Tests in `tests/test_engine_query_followup.py`.

**Phase 9 (Performance-Pass):** verifiziert, kein Code geändert -
`hass`-Zugriff bleibt auf genau einen Aufruf pro Konversationsturn
begrenzt (`build_entity_snapshots()` in `conversation.py`, ein einziger
Call-Site). Die komplette Query-Pipeline (`parsers.py`, `engine.py`,
`nlu/query_executor.py`, `nlu/response_generator.py`) berührt `hass`
nirgends direkt - geprüft per Grep über alle vier Module. Jede
Area-/Entity-Auflösung arbeitet ausschließlich auf der einmal pro Turn
gebauten `EntitySnapshot`-Liste im Speicher (Regel 5: Zustand immer live,
nie gecacht - für ein typisches HA-Setup mit einigen hundert Entities ist
ein erneuter linearer Scan pro Parse-Aufruf akzeptabel, kein Cache nötig).

**Phase 10 (Dokumentation):** dieses Dokument; README-Korrekturen ("12" ->
"13 separat kompilierte Intent-Gruppen", "800+" -> "950+ Tests", neuer
State-Query-Abschnitt in der v4-Roadmap).

## Die 3-Stufen-Pipeline (Abschnitt 12 des v4.2.1-Plans)

```
Parser              QueryExecutor           ResponseGenerator
(parsers.py)    ->   (nlu/query_executor.py) -> (nlu/response_generator.py)
Text                 QueryCommand             QueryResult
  -> QueryCommand      -> QueryResult           -> Text (deutsch)
```

- **`QueryCommand`** (`nlu/query_command.py`): `intent`, `scope`
  (`QueryScope.SINGLE/LIST/COUNT/EXISTS`), `target` (`QueryTarget`:
  `domain`, `device_class`, `area`, `entity_id`), `filter`
  (`QueryFilter.state: SemanticState | None`). Alle Dataclasses `frozen`.
- **`QueryExecutor`** (`nlu/query_executor.py`): `execute(command,
  candidates) -> QueryResult`. Rein lesend by construction - dieses Modul
  importiert nichts aus Home Assistant und kann `hass.services.async_call()`
  gar nicht erreichen (Regel 3). SINGLE unterstützt zwei Aufrufformen: mit
  vorab aufgelöster `entity_id` (heutiger `StateQueryParser`-Gebrauch -
  `resolve_entity_scored` hat die Mehrdeutigkeitsprüfung schon gemacht) oder
  ohne (der Executor entscheidet die Kardinalität selbst: 0 ->
  `TARGET_NOT_FOUND`, 2+ -> `AMBIGUOUS`, 1 -> `MATCHED`) - letzteres gibt
  `AMBIGUOUS`/`TARGET_NOT_FOUND` eigene, unabhängig testbare Codepfade, auch
  wenn die heutige Live-Pipeline sie über `StateQueryParser` nie auf diesem
  Weg erreicht (dort fängt `resolve_entity_scored` Mehrdeutigkeit schon
  vorher ab).
- **`QueryResult`** (`nlu/query_command.py`): `status`
  (`QueryResultStatus.MATCHED/EMPTY/TARGET_NOT_FOUND/AMBIGUOUS`),
  `entities`, `command`. `EMPTY` ist eine normale Antwort (0 Fenster
  offen), kein Fehler - `TARGET_NOT_FOUND`/`AMBIGUOUS` haben in der
  heutigen Live-Pipeline noch kein Äquivalent (siehe oben), sind aber
  bereits vollständig getestet für einen künftigen Aufrufer.
- **`ResponseGenerator`** (`nlu/response_generator.py`): `respond(result)
  -> str`. Sieht nie ein `hass`-Objekt, nur einen `QueryResult`. Wortlaut
  bewusst dupliziert (nicht importiert) aus `service_call.py`s
  `_speak_state_query`/`_speak_check_state`/`_speak_exists` - per Test
  byte-identisch verifiziert, konsolidiert erst, wenn/falls der Call-Site
  tatsächlich umgeklemmt wird.

**Warum `ResponseGenerator` existiert, aber nicht "live" ist:** Phase 7
hat bewusst nur die interne Filterlogik migriert, nicht den
Antworttext-Call-Site - siehe Phase-7-Absatz oben. Ein künftiger Schritt
kann `engine.py::_build_match_result()` auf `ResponseGenerator` umstellen,
sobald das für mehr als die drei Query-Intents relevant wird (z. B. wenn
V5 denselben `QueryExecutor`/`ResponseGenerator` für Automation-Bedingungen
wiederverwendet und die Vokabulare ohnehin konsolidiert werden müssen).

## Wiederverwendbarkeit für V5

Der explizite Zweck der Trennung (Ziel 5 des v4.2.1-Plans): `QueryCommand`/
`QueryExecutor` kennen weder `hass` noch irgendetwas Conversation-
spezifisches - der Automation-Trigger-/Bedingungs-Parser (V5, inzwischen
gebaut und seit der Integration Wave live über `engine.py::match_automation()`
verdrahtet, siehe "Explizit außerhalb des Scopes" unten) könnte
dieselben Typen für "wenn Zustand X erfüllt ist" wiederverwenden, ohne die
Query-Engine noch einmal zu schreiben - bislang aber nicht genutzt: V5s
eigene Condition-Auflösung läuft weiterhin direkt über `resolve_entity_scored`/
`constraint_resolver.resolve_candidates`, nicht über `QueryCommand`/
`QueryExecutor`. `frame.parameters["query_command"]`
(Phase 7) ist bereits der konkrete, additive Kanal, über den ein solcher
künftiger Aufrufer den zuletzt ausgeführten `QueryCommand` einer
Konversation lesen kann, ohne ihn aus rohem Text neu abzuleiten - Phase 8
ist der erste tatsächliche Konsument dieses Kanals.

## Explizit außerhalb des Scopes

Kein Automation-/Trigger-Parser, kein Automation-Generator/-UI/-Storage
(alles V5) - dieser Plan formt die Query Engine nur so, dass V5 sie *später*
wiederverwenden könnte, nichts V5-Spezifisches wurde gebaut. Kein LLM/
Cloud/externe API/GPU/ML irgendwo (Regel 1). Queries rufen nie
`hass.services.async_call()` (Regel 3).

## Tests

`tests/test_query_command.py` (10), `tests/test_query_executor.py` (11),
`tests/test_response_generator.py` (12), `tests/test_conversation_integration.py`
(5), `tests/test_engine_state_query.py` (44, inkl. 5 Phase-7-Pinning-Tests
für `frame.parameters["query_command"]`), `tests/test_engine_query_followup.py`
(20, inkl. 7 neue Phase-8-Tests), `tests/test_semantic_state.py` (12) - plus
27 golden Testfälle (`tests/golden/state_query.json`). Volle Suite: 975
Tests grün.

## WorldModelQuery – generische Semantic-Query-Integration (2026-08-17)

Ausgangsbefund: `StateQueryParser` + die drei v4.2-Query-Intents bauten
zwar bei jedem Turn einen vollen `QueryCommand`/`QueryResult`
(`_QUERY_EXECUTOR.execute(...)`), warfen davon aber sofort alles außer
`.entities` weg, und die Antwort kam weiterhin aus `service_call.py`s
`_speak_state_query`/`_speak_check_state`/`_speak_exists`-Lambdas statt
aus dem bereits fertigen, aber noch nie live aufgerufenen
`ResponseGenerator`. `ParseContext` trug außerdem nie ein `WorldModel`,
obwohl `conversation.py` es längst jeden Turn baute - Geräte-Ebene
("Welche Geräte sind im Büro?") war dadurch strukturell unerreichbar
(keine Grammatik, kein `DeviceSnapshot`-Pfad in `QueryTarget`/
`QueryExecutor`), und zustandslose Auflistung ("Welche Lampen sind im
Wohnzimmer?") scheiterte am zwingenden `{state}`-Slot in
`_parse_state_query`. Plandatei: `validated-shimmying-star.md`.

**Phase A** - `WorldModel` in `ParseContext` verdrahtet: `NluEngine.match()`
bekommt einen optionalen `world_model`-Parameter, `conversation.py` reicht
sein pro-Turn gebautes `self._world_model` durch. Nur der frische
Erstsatz-Pfad (`match()`); `match_followup()`/`match_reference()`/
`match_query_followup()` bleiben unverändert.

**Phase B** - `QueryTarget`/`QueryExecutor` um Device-Scope erweitert:
neuer `QueryTargetKind`-Enum (`ENTITY`/`DEVICE`), `QueryTarget.domain`
optional, `QueryResult.devices`-Feld. `QueryExecutor._execute_device()`
liest `world_model.devices_in_area(...)` (Methode existierte bereits) -
kein `world_model`/keine `area` → `EMPTY`, nie ein Crash.

**Phase C** - neue Grammatik: `HassDeviceQuery`-Intent ("welche Geräte
sind im Büro", "welche Geräte befinden sich im Büro", "was für Geräte
sind im Büro") sowie eine zustandslose `HassStateQuery`-Satzvariante
("welche {device_class} sind im {area}", ohne `{state}`-Slot). Neue
`StateQueryParser._parse_device_query`-Methode; bestehende
`_resolve_area()` wiederverwendet (Regel 6), kein auflösbares Gebiet →
`None` (kein "alle Geräte im Haus"-Fallback - "niemals raten").

**Phase D** - `ResponseGenerator` live geschaltet: alle vier
`_parse_*`-Methoden stashen jetzt den vollen `QueryResult` (nicht nur
`.entities`) in `frame.parameters["query_result"]`;
`engine.py::_build_match_result()` fängt das vor dem alten
`QUERY_INTENTS`-Lambda-Pfad ab und ruft `ResponseGenerator.respond()`.
`_SEMANTIC_STATE_SPOKEN_DE[OPEN]` von `"offen"` auf `"geöffnet"`
umgestellt (reines Eingabe-Synonym wird jetzt auch Ausgabewort), neue
`_join_names()`-Hilfsfunktion für natürliche deutsche Aufzählungen ("A und
B" / "A, B und C" statt Komma-Join), `TARGET_NOT_FOUND`/`AMBIGUOUS` jetzt
noun-bewusst. Die drei alten `service_call.py`-Lambdas
(`_speak_state_query`/`_speak_check_state`/`_speak_exists`) und ihre
Helfer (`_SEMANTIC_STATE_SPOKEN_DE`/`_DEVICE_CLASS_PLURAL_DE`/
`_state_query_noun`) werden dadurch nie mehr erreicht, bleiben aber
bewusst stehen (dead, aber harmlos) - `QueryIntentSpec.response` ist ein
Pflichtfeld ohne Default, `allows_empty`/`QUERY_INTENTS`-Mitgliedschaft
selbst werden weiterhin von `validate_command()` und
`conversation.py::QUERY_INTENT_NAMES` gelesen. Separates, risikoarmes
Aufräumen, nicht Teil dieser Welle.

**Phase E** - keine neue Struktur nötig: `QueryTarget`/`QueryFilter`/
`QueryCommand` (Phase B) waren bereits die generische, kombinierbare
Struktur, die der Plan verlangte. `state=ANY` entspricht
`QueryFilter.state=None` (bereits vorhanden), kein neues `quantifier`-Feld
(kollidiert sonst mit `SemanticFrame.quantifier`). "unten"/"oben" als
Rollladen-Zustand und "aktiv" als Sensor-Zustand blieben bewusst
draußen - kein Vokabular-Beleg in `_STATE_SLOT_LIST`.

**Phase F** - Live-Validierung gegen die echte HA-Instanz (per
`mcp__home-assistant__*`, kontrollierte Reproduktion statt Sensor-Toggle,
siehe unten): alle 5 DoD-Sätze liefern mit echten Entity-/Geräte-/
Area-Daten korrekte, zustandsabhängige Antworten.

### DoD-Abgleich (Live, echte Daten dieses Hauses)

| Satz | Antwort |
|---|---|
| Welche Fenster sind geöffnet? | "Badezimmer Fenster klein und Schlafzimmer Fenster sind geöffnet." |
| Welche Lichter sind an? | "Abstellraum Lampe, Spiegel Licht, Segment 3, WLED-Ess-Wandpaneel Segment 1, WLED-Ess-Wandpaneel Segment 2 und WLED-Ess-Wandpaneel Segment 3 sind eingeschaltet." |
| Welche Geräte sind im Büro? | "Dachgeschoss Licht, Treppe/Büro, Treppe/Büro, Rauchwarnmelder Büro, Rolllade Büro und Büro sind im Büro." |
| Wie viele Fenster sind geöffnet? | "2 Fenster sind geöffnet." |
| Welche Lampen sind im Wohnzimmer? | "Wohnzimmer Regal ist im Wohnzimmer." |

Vorher/Nachher-Beweis (kontrollierte Reproduktion - reine Python-
Objektkopie der beiden zuvor offenen Fenster-Entities auf
`state="off"`, **keine Schreiboperation gegen HA**, siehe
`feedback_no_invasive_verification`): dieselbe Frage "Welche Fenster sind
geöffnet?" liefert danach "Es sind keine Fenster geöffnet." - die Antwort
hängt nachweislich vom `state`-Feld ab, nicht von einer gecachten
Formulierung. Kein Teil der committeten pytest-Suite (CI hat keinen
Zugriff auf die echte HA-Instanz) - einmaliger, manueller Nachweis dieser
Welle.

### Bewusst nicht Teil dieser Welle

- Zustands-gefilterte Geräte-Queries ("Welche Geräte sind gerade
  eingeschaltet?") - ein Gerät hat keinen einzelnen Zustand, nur seine
  Entities; bräuchte eine unbelegte Aggregationsregel.
- "unten"/"oben"/"aktiv" als neue Zustands-Vokabeln (siehe Phase E).
- `floor`/`capability`/`attributes` als `QueryTarget`-Felder - kein
  treibender Satz in dieser Welle.
- Geräte-/WorldModel-Queries als Folgefrage/Referenz
  (`match_followup`/`match_reference`/`match_query_followup`) - nur der
  frische Erstsatz-Pfad ist verdrahtet (Phase A).
- Löschen der drei toten `service_call.py`-Lambdas + ihrer Helfer (siehe
  Phase D) - separates, risikoarmes Aufräumen.
- `AMBIGUOUS`/`TARGET_NOT_FOUND` sind in dieser Welle nur über direkte
  `QueryExecutor`/`ResponseGenerator`-Unit-Tests real erreichbar, nicht
  über einen gesprochenen `engine.match()`-Satz (siehe Phase D).
- `ReasoningEngine`/`Constraints`-Vollintegration in `engine.py` bleibt
  weiterhin unverdrahtet (bereits vor dieser Welle bewusst zurückgestellt).

### Tests (dieser Welle)

`tests/test_response_generator.py` (+6: `_respond_device_list` 0/1/N,
`_respond_list_no_state` 0/1/N), `tests/test_engine_state_query.py` (+3
Wording-Regressionen, +3 neue Device-/zustandslose End-to-End-Tests, diverse
Wording-Updates offen→geöffnet), `tests/golden/state_query.json` (13
Wording-Updates). Volle Suite: 1084 Tests grün (vorher 1072).
