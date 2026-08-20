# v6 – Semantic Intelligence Architecture

Referenz: Brain-Knoten `247360ab-8493-42e4-8aef-bd4d0b95b1db` bis
`c2cfa095-9a1b-46c0-a9b9-fd542fffe3f4` (Teil 1/7 – 7/7 des HomeIntent-Plans
V6) sowie `15884008-4107-4f8b-8227-e0de518c745c` (Wave-0-Bestandsaufnahme,
2026-08-13). Dieses Dokument ist die **Kurzfassung/Landkarte** für den
V6-Umbau im Repo – die vollständigen Begründungen, Beispiele und
Detail-Spezifikationen pro Phase liegen im Brain-Knowledge-Graph (siehe
Abschnitt 8). Stand: V6.6 (Home World Model, Parser-Migration), HEAD
`932444d`.

Vorstufe: `docs/architecture-v4.md` (v4 – Advanced Natural Language,
abgeschlossen). v5 (Automation Engine, V5.1-V5.53) wurde inzwischen
vollständig gebaut (Waves 1-5, Release 4.10.0) und über eine eigene
Integration Wave (2026-08-18/19) in `engine.py::match_automation()`/
`conversation.py` eingehängt: Sprache → `AutomationModel` → Validation →
Response/Debug. Die V6.28/V6.29-Zeilen in Abschnitt 6 unten spiegeln noch
den Stand *vor* dieser Integration Wave und sind insofern historisch zu
lesen, nicht als aktueller Status.

**V5 Teil 7/10 ("Dry Run", 2026-08-20)** hat den bis dahin bewusst
ausgesparten letzten Schritt nachgereicht: ein valides `AutomationModel`
löst jetzt keinen HA-Service-Aufruf *auf demselben Turn* mehr aus, sondern
wird als gesprochene Vorschau
(`nlu/automation_preview.py::render_automation_preview()`, "Automation
erkannt: Wenn …, dann … Soll diese Automation erstellt werden?") ausgegeben
und als `PendingAutomationConfirmation` (`nlu/context.py`) auf dem
`ConversationContext` gehalten – mit derselben Priorität wie
`pending_clarification`. Die Antwort des nächsten Turns durchläuft
`nlu/automation_confirmation.py::classify_confirmation_reply()` (geschlossenes
Ja/Nein-Vokabular, `UNCLEAR` fragt erneut, rät nie). Erst ein klares "Ja"
übersetzt das Modell über `nlu/ha_automation_generator.py::
generate_ha_automation_config()` (reine Übersetzung, kein Hass-Import) in
ein HA-natives Automation-Dict und übergibt es an `automation_executor.py::
AutomationExecutor` – die einzige Stelle im gesamten Automation-Track, die
tatsächlich `automations.yaml` beschreibt (Read-Modify-Write hinter einem
`asyncio.Lock()`, danach `automation.reload`). `AutomationExecutor` liegt
bewusst *außerhalb* von `nlu/` (Top-Level von `custom_components/ha_nlu/`,
wie `hass_entities.py`) – `nlu/` bleibt vollständig Hass-frei, echte HA-I/O
gehört eine Ebene höher.

⸻

## 1. Vision & Grundregel

HomeIntent soll **keine** regelbasierte NLU mit tausenden Einzelsatzregeln
werden (z.B. "mach das Licht an" / "schalte das Licht an" / "mach bitte das
Licht an" als drei getrennte Regeln), sondern eine **kompositionelle,
deterministische semantische Engine**. Bedeutung entsteht aus
wiederverwendbaren Bausteinen – sprachlich, strukturell, semantisch,
Kontext, Weltmodell, Capabilities, Zustände, Constraints – statt aus
vollständigen Satzlisten.

Beispiel-Prinzip: "mach...an" / "schalte...ein" / "lass...an" → gemeinsam
`TURN_ON`; "Licht" / "Lampe" / "Beleuchtung" → gemeinsam `TARGET=LIGHT`.

Explizit ausgeschlossen bleiben: LLM, Cloud, externe API, GPU, ML-Modell,
Embeddings, Vector Database. Ziel-Gefühl für den Nutzer: normal mit HA
sprechen können, ohne HomeIntent-spezifische Formulierungen lernen zu
müssen.

**Zentrales Leitprinzip:** Ist ein Sprachproblem durch eine allgemeine
semantische Regel lösbar, wird die allgemeine Regel verwendet – nicht eine
Regel für einen einzelnen Satz. Bei der Wahl zwischen (A) schneller
spezieller Satzregel und (B) allgemeiner wiederverwendbarer semantischer
Lösung gilt grundsätzlich B, außer B verkompliziert die Architektur unnötig
oder gefährdet Raspberry-Pi-Performance.

⸻

## 2. Die 7 nicht verhandelbaren Architekturregeln (R1–R7)

Wer an V6 arbeitet, liest **diesen Abschnitt zuerst**.

| # | Regel |
|---|---|
| R1 | **Kein LLM im Core.** Die Engine ist vollständig lokal und deterministisch. |
| R2 | **Der Parser führt niemals direkt HA-Services aus.** Pipeline zwingend: Natural Language → Semantic Analysis → Semantic Frame → Resolution → Reasoning → Semantic Command → Validation → ServiceMapper → Execution. |
| R3 | **Queries und Commands sind strikt getrennt.** Query liest nur Zustand (Query Semantic Model → Query Executor → Query Result → Response), Command verändert (Command Semantic Model → Validator → ServiceMapper → Execution). Ein Query darf **niemals** einen ServiceCall auslösen. |
| R4 | **Niemals bei echter Ambiguität raten.** Bei mehreren gleichwertigen Entities: `AMBIGUOUS` + Rückfrage statt zufälliger Auswahl (Beispiel: "Mach die Lampe aus" bei 3 passenden Lampen). |
| R5 | **Scoring ist nur Ranking, kein Ausführungs-Freibrief.** Ein hoher Score darf echte Ambiguität nicht verstecken. |
| R6 | **HA bleibt Quelle der Wahrheit.** HomeIntent darf ein semantisches World Model besitzen, aber keine zweite HA-Datenbank werden; aktuelle States kommen aus HA. |
| R7 | **Bestehende Funktionalität (v1–v5) bleibt erhalten.** Bestehende Parser laufen zunächst als Fallback weiter, die neue Semantic Engine wird schrittweise eingeführt – nicht ersetzen-und-brechen. |

⸻

## 3. Zielarchitektur / Pipeline

```
Natural German
      │
      ▼
Language Layer
      │
      ▼
Semantic Composer
      │
      ▼
Semantic Frame  ── (bewusst unvollständig sein dürfend, z.B. TARGET=UNKNOWN)
      │
      ▼
┌─────────────────────────────┐
│ Context Resolver             │
│ World Model Resolver         │──▶ Constraint Engine ──▶ Capability Reasoning
│ Modifiers                    │
└─────────────────────────────┘
      │
      ▼
Reasoning Engine  (produziert NUR semantische Ergebnisse, keine Service-Calls)
      │
      ├── Query  ──▶ Query Executor ──▶ Query Result   ──▶ Response
      │
      └── Command ──▶ Validator ──▶ Service Plan ──▶ Execution
```

Kernpunkte:

- `ConversationContext` ist eine eigene, **begrenzte** Schicht und darf
  nicht global mutable sein.
- Query- und Command-Pfad nutzen bis zur Reasoning Engine **dieselben**
  semantischen Bausteine – der Unterschied liegt nur in der Operation
  (lesen vs. verändern), siehe R3.
- `ResolvedSemanticIntent` ist das vereinheitlichende Ergebnis der
  Reasoning Engine, aus dem sich sowohl Query Result als auch Service Plan
  ableiten.

⸻

## 4. Ist-Zustand (Wave 0, Stand `b188cab`)

Vollständige Analyse: Brain-Knoten `15884008-4107-4f8b-8227-e0de518c745c`.
Datenfluss heute: `conversation.py` → `normalize()` → `NluEngine._select_parser()`
(Regex-Routing, ~15 Regexe, 13 hassil-Intents-Instanzen) → `parsers.py`
`Parser.parse()` (1689 Zeilen, 16 Parser-Klassen) → `ParseResult |
ClarificationRequest | AmbiguousReference | None` → `command.py
build_semantic_command()` → `validator.py validate_command()` (9 fest
kodierte Checks) → `service_mapper.py map_to_service_call()` →
`ServiceCallPlan` → `hass.services.async_call()`. Die hass-freie Grenze im
`nlu/`-Package ist konsequent eingehalten (nur `hass_entities.py` hat
HA-Kopplung).

| Zielkonzept | Status | Fundstelle |
|---|---|---|
| Target | existiert | `nlu/frame.py` `TargetReference` |
| Location/Area | existiert | `nlu/frame.py` `AreaReference` + `areas.py` `AreaSnapshot` |
| Quantifier | existiert | `nlu/frame.py` `Quantifier` |
| TemporalExpression | existiert (nur protokolliert, keine Ausführung) | `nlu/frame.py` `TemporalExpression` |
| Capability | existiert | `nlu/capabilities.py` `Capability` (Enum, 11 Werte) |
| Ambiguity Reasoning | existiert, am weitesten entwickelt | Scoring + Margin=5 in `entities.py`/`areas.py`/`floors.py` + `ClarificationRequest` |
| CommandPlan | existiert, aber nur für Commands | `engine.py:306`, naives "und"-Split |
| QueryResult / NluResponse / NluError | existiert, stabil | `nlu/query.py`, `nlu/response.py` |
| Action | teilweise | nur String-Intent, keine typisierte Klasse |
| State | teilweise | nur 5 Werte OPEN/CLOSED/ON/OFF/UNKNOWN, kein z.B. MOTION_DETECTED |
| Floor | teilweise | `floors.py` `FloorSnapshot` existiert, aber keine `FloorReference` in `SemanticFrame` – nur "oben"/"unten"-Keywords |
| Comparison | teilweise | `nlu/frame.py` `Comparison`, an Prozent/Temperatur gekoppelt, nicht generisch |
| Reference/Pronomen | teilweise | fest verdrahtet gegen Context, kein generisches Modell |
| ConversationContext | teilweise | `nlu/context.py`, nur 4 Felder (`last_command`, `last_entities`, `last_area`, `pending_clarification`) – 12+ Felder im Zielbild fehlen |
| World Model Indexes | teilweise | `entities.py:291` `EntityIndex` vorgebaut, aber in keinem Consumer verdrahtet |
| Capability Reasoning | teilweise | funktioniert, aber fester 11-Werte-Katalog |
| Constraint Resolver | teilweise | `validator.py` hat 9 fest kodierte Checks, kein generischer Solver |
| Query Semantics | teilweise | `QueryCommand`/`SemanticCommand` bleiben getrennte Typhierarchien |
| Property-Primitive | fehlt komplett | – |
| Direction / Degree / Condition | fehlt komplett | – |
| Semantic Lexicon | fehlt komplett | Wort→Kandidat-Mapping steckt hart in hassil-Slot-Listen (z.B. `_STATE_SLOT_LIST`) |
| Semantic Composer | fehlt komplett | Frame-Bau passiert inline in 16 Parser-Klassen (`parsers.py`) |
| World Model (vereinheitlicht) | fehlt komplett | – |
| Reasoning Engine | fehlt komplett | Logik verteilt über `NluEngine._select_parser` → Parser → `build_semantic_command` → `validate_command` → `map_to_service_call` |
| ResolvedSemanticIntent | fehlt komplett | Analoga `SemanticCommand` + `QueryResult` sind getrennte Typen |

Hinweis zum WIP-Fund der Wave-0-Analyse: Im Haupt-Worktree lag zum
Analysezeitpunkt unkommitteter WIP (`query_command.py`, `query_executor.py`,
`response_generator.py`) vor, der einem Vorläufer von "Query Semantics"
(V6.18) entspricht. `response_generator.py` war komplett unverdrahtet.
Dieser saubere Worktree bei `b188cab` enthält diesen WIP nicht. Details:
Brain-Knoten `15884008-4107-4f8b-8227-e0de518c745c`.

⸻

## 5. Bestätigte Architekturentscheidungen (Wave 0, 2026-08-13)

Vom Nutzer bestätigt, alle vier empfohlenen Optionen:

1. **ResponseGenerator** wird reaktiviert und mit den
   `service_call.py`-QUERY_INTENTS-Lambdas konsolidiert (eine Funktion =
   eine Implementierung).
2. **hassil** wird schrittweise durch den Semantic Composer abgelöst
   (passt zur Grundregel "kompositionell statt Satzlisten"), über die
   Fallback-Kaskade aus Abschnitt 7.
3. **CommandPlan** (bestehendes Konstrukt, `engine.py:306`) wird erweitert
   – auf Queries ausgeweitet, naives "und"-Split durch echte
   Plan-Validierung ersetzt. Kein Neubau.
4. **FloorReference** wird vollwertig analog `AreaReference` eingeführt;
   "oben"/"unten" wird ein generischer Location-Fall statt Sonderkeyword.

⸻

## 6. Phasenübersicht V6.1–V6.29

Alle Phasen initial **nicht begonnen** (Wave 1 arbeitet an unabhängigen
Grundlagen, siehe Empfehlungen in Brain-Knoten
`15884008-4107-4f8b-8227-e0de518c745c`; Fortschritt paralleler Agenten ist
zum Zeitpunkt dieses Dokuments nicht einsehbar). Diese Tabelle bei
Phasenabschluss aktualisieren.

| Phase | Titel | Kurzbeschreibung | Status |
|---|---|---|---|
| V6.1 | Semantic Primitives | Gemeinsames semantisches Vokabular (Entity, Target, Action, Property, State, Location, Area, Floor, Quantity, Comparison, Direction, Degree, Reference, Condition, TemporalExpression, Capability, Query, Command), klein/immutable/typsicher | **abgeschlossen** (`nlu/primitives.py`) |
| V6.2 | Semantic Frame erweitern | Bestehendes `SemanticFrame` für komplexere Bedeutungen, beschreibt ausschließlich Bedeutung, noch kein HA-Service | **abgeschlossen** (`nlu/frame.py`, additiv: action/property/direction/degree/quantity) |
| V6.3 | Semantic Lexicon | Neue Komponente: Wort/Ausdruck → semantische Kandidaten (liefert Kandidaten, entscheidet nicht allein) | **abgeschlossen** (`nlu/lexicon.py`) |
| V6.4 | Semantic Composer | Neue Komponente: setzt sprachliche Bausteine zu semantischer Struktur zusammen statt Satzlisten | **abgeschlossen** (`nlu/composer.py`, bislang nur property+quantity; action/direction/degree fehlt Lexicon-Kandidatentabelle) |
| V6.5 | Semantische Unvollständigkeit | `SemanticFrame` darf unvollständig sein; Auflösung über Context → explizites Target → Area → World Model → Capability → Default Scope, sonst AMBIGUOUS/MISSING_TARGET | nicht begonnen |
| V6.6 | Home World Model | Entity-Modell zu semantischer HA-Sicht erweitern (Entities, Devices, Areas, Floors, Domains, Device Classes, Capabilities, States, Attributes, Aliases, Relationships); HA bleibt Quelle der Wahrheit | **abgeschlossen** (strukturelle Filterung: 6c; echtes `WorldModel`-Objekt inkl. `DeviceSnapshot`: 6d) – nicht in `conversation.py` verdrahtet, siehe 6d |
| V6.7 | World Model Indexes | Performance-Indizes (domain, device_class, area, floor, capability, alias); States nicht unkontrolliert dauerhaft cachen | nicht begonnen |
| V6.8 | Capability Reasoning | Benötigte Capability aus Semantik ableiten, inkompatible Entities ausschließen | **abgeschlossen** (`nlu/capabilities.py::required_capability_for_property`) |
| V6.9 | Constraint Resolver | Neue Komponente: sucht Entities, die ALLE Constraints erfüllen, bevor Quantity angewendet wird | **abgeschlossen** (`nlu/constraint_resolver.py`, domain/area/floor/device_class/property) |
| V6.10 | Ambiguity Reasoning | Bei mehreren gleichwertigen Kandidaten: `AMBIGUOUS_ENTITY` + konkrete Rückfrage statt zufälliger Auswahl | bereits vorhanden vor V6 (`entities.py::resolve_entity_scored` Margin=5 + `ClarificationRequest`), von Constraint Resolver bewusst wiederverwendet statt dupliziert |
| V6.11 | Reference Resolution | Pronomen/Referenzen ("es/sie/das/dort/hier/wieder/die anderen/das gleiche") semantisch über Context auflösen | größtenteils bereits vorhanden (V3.4/V3.5: Pronomen, Komplement-Referenz, area-anchored dort/im selben Raum/hier) – nur "nebenan/drüben" (räumliche Adjazenz) fehlt, siehe V6.13 |
| V6.12 | Semantic Context | `ConversationContext` über Text-History hinaus erweitern (last_intent, last_action, last_target, last_property, last_value, pending_reference, ...); nicht global mutable | Teil abgeschlossen: last_floor/last_property/last_value/last_state/pending_reference additiv ergänzt (`nlu/context.py`). last_intent/last_action/last_target/last_query bewusst NICHT dupliziert (Regel 6) – bereits über last_command abrufbar |
| V6.13 | Relative Locations | "hier/dort/oben/unten/nebenan/drüben/im selben Raum"; ohne eindeutige Interpretation Rückfrage statt erfundener Position | oben/unten/dort/im selben Raum bereits vorhanden; "hier" jetzt als Synonym ergänzt (pronoun.yaml, gleiche `_resolve_area_anchored()`-Auflösung). "nebenan/drüben" bewusst zurückgestellt – erfordert Area-Adjazenzmodell, das im World Model nicht existiert (niemals raten) |
| V6.14 | Quantity Semantics | Internes `QuantityConstraint`-Modell (alle/beide/drei/ein paar/alle außer...) statt Satzregeln | ALL/EXACTLY(n) bereits vollständig (Quantifier + SemanticQuantity, Wave 2a). SOME/EXCLUDE bewusst zurückgestellt – kein Lexikon-Beleg für "einige"/"ein paar"/"außer" in der Grammatik, würde Vokabular erfinden statt extrahieren |
| V6.15 | Degree Semantics | "etwas/leicht/deutlich/viel/komplett" → SLIGHT/MODERATE/STRONG/MAXIMUM/MINIMUM | zurückgestellt – "etwas"/"ein bisschen" werden in `normalize.py` global als Filler gestrichen, bevor irgendein Parser sie sieht; Degree wiring erfordert Änderung an dieser zentralen, von allen 8 Grammatikgruppen genutzten Funktion (hohes Blast-Radius-Risiko), separate Folgearbeit |
| V6.16 | Number Normalization | "50/50%/fünfzig Prozent" etc. → einheitliches `NumericValue` | `NumericValue`/`NumericUnit` (PERCENT/CELSIUS/LEVEL) ergänzt (`nlu/primitives.py`), gegründet auf den 3 realen RangeType-Unit-Kontexten. Symbolnormalisierung + Zahlwort-Matching liefen bereits vorher über normalize.py + hassil RangeSlotList. Noch nicht in frame.py/parsers.py verdrahtet (vorbereitend, wie SemanticDegree) |
| V6.17 | Comparison Semantics | "mehr als/mindestens/höchstens" → `Comparison(operator, value)`, generisch statt an Prozent/Temperatur gekoppelt | bereits vollständig vorhanden (`nlu/frame.py::Comparison`, `ComparisonQueryParser`, `_COMPARATOR_SLOT_LIST`) – deckt alle Plan-Beispiele (mindestens/höchstens/über/unter/mehr als/weniger als) über gte/lte/gt/lt ab |
| V6.18 | Query Semantics | Queries und Commands nutzen dieselben Bausteine, Unterschied nur in der Operation | zurückgestellt – berührt aktives, unkommittiertes Nutzer-WIP (`query_command.py`, `query_executor.py`, `response_generator.py`, `docs/architecture-v4-query.md`), das bewusst nicht angefasst wird ohne Rücksprache |
| V6.19 | State Reasoning | HA-Zustände semantisch normalisieren UNTER Berücksichtigung der device_class (nicht pauschal on=OPEN) | bereits vollständig vorhanden (`nlu/semantic_state.py`) – `SemanticState`-Enum (OPEN/CLOSED/ON/OFF/UNKNOWN) mit `derive_semantic_state()`; `cover.state` wird direkt gemappt, `binary_sensor` nur bei device_class ∈ `_BINARY_SENSOR_OPEN_CLOSE_DEVICE_CLASSES` (`{"window","door","opening","garage_door"}`) als OPEN/CLOSED interpretiert, jede andere device_class (z.B. `motion`) bleibt bei generischem ON/OFF – genau die im Plan geforderte Unterscheidung, keine pauschale on=OPEN-Regel. Unbekannte Rohzustände ("unavailable") mappen bewusst auf `UNKNOWN`, das `matches_semantic_state()` nie matcht (Regel 4, niemals raten) |
| V6.20 | Natural Query Language | Verschiedene Frageformen ("sind offen?"/"noch offen?"/"gibt es offene...?") auf dieselbe Semantik abbilden | bereits vollständig vorhanden (`intents/de/state_query/state_query.yaml`, V4.2 "Semantic Query & State Resolution") – drei Intents auf derselben Grammatik: `HassStateQuery` ("welche {device_class} sind [denn] [noch] {state}", "wie viele {device_class} sind ... {state}", "sind [denn] {device_class} [noch] {state}"), `HassExistsQuery` ("gibt es [denn] [noch] {state_adj} {device_class}", "ist [im {area}] ein {device_class} [noch] {state}") und `HassCheckState` ("ist [die|der|das] {name} ... {state}"); alle drei laufen durch `StateQueryParser` (parsers.py) auf dieselbe `SemanticState`-Filterung. "[noch]"/"[denn]" sind semantisch leere optionale Füllwörter, decken genau die im Plan genannten Varianten ab |
| V6.21 | Natural Command Language | Analog für Commands: viele Formulierungen → dieselbe Action/Target/Property-Kombination | bereits vollständig vorhanden (`intents/de/light_switch.yaml`) – `HassTurnOn`/`HassTurnOff` je 7 Satzvarianten ("mach [den|die|das] {name} an", "schalte [den|die|das] {name} ein", "kannst du [den|die|das] {name} anmachen", "bitte [den|die|das] {name} an", plus "dreh [den|die|das] {name} an"/"lass [den|die|das] {name} an" – die beiden Verben aus HomeIntent-Plan V4.1 "Advanced German Language", die sonst nirgends abgedeckt waren), `HassToggle` mit 3 Varianten; alle münden in dieselbe Action/Target-Kombination. Die komplexere Grad/Richtung-Kombination aus dem Plan-Beispiel ("etwas dunkler") läuft bereits separat über die Degree/Quantity-Bausteine (V6.14/V6.15) |
| V6.22 | Multi-Command Semantics | `CommandPlan` mit mehreren Commands, gesamter Plan wird vor Ausführung validiert (nicht Ad-hoc-Split) | bereits vollständig vorhanden (`engine.py`) – `_AND_SPLIT_RE` (Zeile 247) splittet auf " und ", `NluEngine.match()` (Zeile 457) delegiert bei mehr als einem Segment an `_match_multi()` (Zeile 473). Deren Docstring macht den Vertrag explizit: "See `CommandPlan`'s docstring for the 'validate everything first, execute nothing on any failure' contract this enforces by only ever returning a fully-populated `CommandPlan` or `None`, never something in between." Jedes Segment wird rekursiv über denselben `match()`-Einstiegspunkt einzeln validiert; schlägt auch nur eines fehl (kein `MatchResult`, eine `clarification`, oder `plan is None`), liefert `_match_multi()` `None` für den gesamten Plan – kein Teilausführungspfad. Baut, wie im Plan gefordert, auf dem bestehenden V4.8-„und"-Split auf, läuft aber bereits über `CommandPlan` statt Ad-hoc-Split |
| V6.23 | Natural Context | Folgeäußerungen ohne neue vollständige Satzregeln, Reference auf `previous_target` | `engine.py::match_followup()` leitet die Zieldomäne jetzt aus dem geparsten Intent ab (statt vorher fest auf `domain=="light"`): "heller"/"dunkler" bleiben bei `LIGHT_EXTENDED_INTENTS`, neu dazu "wärmer"/"kälter" (`intents/de/context_followup/temperature.yaml`) für `CLIMATE_EXTENDED_INTENTS` – reine Grammatik-Erweiterung, die das bereits bestehende `HassClimateIncreaseTemperature`/`HassClimateDecreaseTemperature`-Vokabular aus `climate_extended/temperature.yaml` wiederverwendet statt ein Farbtemperatur-Äquivalent zu erfinden, für das keine Grammatik-/Lexikon-Evidenz existiert (niemals raten) |
| V6.24 | Explainability | Debug-Modus: INPUT→LINGUISTIC→SEMANTIC FRAME→WORLD MODEL candidates→CAPABILITY FILTER→CONSTRAINT RESOLUTION→FINAL TARGET/COMMAND | bereits vollständig vorhanden (`nlu/debug.py`, v2-Plan Phase 22 "Debug-Modus") – `DebugTrace`-Dataclass (Zeile 41) mit 15 Feldern deckt exakt die im Plan geforderte Pipeline-Sichtbarkeit ab: input, normalized, parser, intent, target, area, candidates, resolution, capabilities, command, validation, service, data, result_kind, response_text. `NluEngine.debug()` (engine.py, Zeile 709) ist der Einstiegspunkt, rein lesend neben `respond()`. Das Feld `result_kind` trägt einen eigenen Kommentar, der genau die V6.27-relevante Designentscheidung vorwegnimmt: es unterscheidet ein bewusstes „0 matches is a valid answer" (VALIDATION: OK, CANDIDATES: -) von einem echten NO_MATCH – "without requiring the per-parser return-type restructuring this module's own docstring above says not to do speculatively" |
| V6.25 | Reasoning Engine | Neue zentrale Komponente: Frame+Context+WorldModel+Capabilities+Constraints → `ResolvedSemanticIntent`, keine Service-Calls | `nlu/reasoning.py` – `ReasoningEngine.resolve()` baut aus `SemanticFrame.target`/`.area`/`.property` (mit `ConversationContext.last_area`/`.last_floor` als Fallback für Folgeäußerungen ohne eigenes Ziel) `Constraints` und delegiert die Kandidatenfilterung vollständig an `constraint_resolver.resolve_candidates()` (Regel 6, keine Parallel-Suche). Kein Import aus `service_call.py`/`service_mapper.py`. **Seit der Integration Wave (2026-08-19) live in `engine.py::_build_match_result()` (Zeile 1039) verdrahtet** – wird bei jedem Match aufgerufen, das Ergebnis landet in `MatchResult.resolved_intent`, bleibt aber rein additiv/beobachtend: kein Konsument liest das Feld, es steuert weder `plan` noch `response_text`. Volles Behavior-Driving-Verdrahten (Ambiguitäts-Gate im Command-Pfad) bleibt bewusst zurückgestellt (siehe 6a) |
| V6.26 | Resolved Semantic Intent | Neues Modell mit vollständig aufgelöster Bedeutung, danach Command Validator → ServiceMapper | neu (`nlu/reasoning.py::ResolvedSemanticIntent`, `@dataclass(frozen=True)`) – exakt die Plan-Felder: `action`, `entities` (bereits Constraints-gefiltert, noch nicht durch `quantity`/`quantifier` reduziert – das bleibt Aufgabe des Callers), `property`, `direction`, `degree`, `area` (wiederverwendet `nlu/frame.py::AreaReference`, kein zweiter Area-Typ) |
| V6.27 | Query Result | Strukturierte Query-Ergebnisse (operation, status, entities, count); 0 Treffer = SUCCESS+EMPTY, nicht NO_INTENT_MATCH | bereits vollständig vorhanden (V4.2 "Semantic Query & State Resolution") – `StateQueryParser` (parsers.py, Zeile 1238) ist laut eigenem Docstring "the one deliberate exception to the codebase-wide 'a multi-entity parser never returns an empty resolved_entities list' rule": `HassStateQuery`/`HassExistsQuery` liefern bei 0 Treffern bewusst ein volles `ParseResult` statt `None`. Durchgesetzt über `QueryIntentSpec.allows_empty` (service_call.py, Zeile 138), das für `HassStateQuery`/`HassExistsQuery` `True` ist (umgeht `nlu/validator.py`-Check #2 ENTITY_NOT_FOUND) und für `HassCheckState` `False` bleibt (dort ist ein leeres Ergebnis ein echter Nicht-Treffer, kein leeres Query-Resultat). Die Response-Lambdas `_speak_state_query`/`_speak_exists` (service_call.py) produzieren für 0 Treffer explizit einen SUCCESS-Satz ("Keine Fenster sind offen."/"Nein, es gibt keine Fenster."), keinen Fehler. Durch Tests belegt: `tests/test_engine_state_query.py::test_state_query_list_empty_is_success_not_error` und `::test_state_query_area_scoped_no_matches_still_empty_success` assertieren genau `result is not None` mit `entities == ()` |
| V6.28 | Automation Foundation | V5-Automationen nutzen dieselben Semantic Frames/Resolver, keine eigene parallele Sprachlogik | zurückgestellt (Nutzerentscheidung 2026-08-13) – setzt eine bereits laufende V5 Automation Engine voraus, auf die die Semantic Engine nur aufgesetzt wird. Recherche ergab: V5 (V5.1-V5.53) existiert nirgends im Code (kein Commit, keine Datei, keine Tests unter diesem Namen) – nur als Brain-Planungsnotizen. V6.28 ist damit ohne vorherigen vollständigen V5-Build nicht sinnvoll umsetzbar; ein Vollbau von V5 jetzt wäre eine eigene Multi-Wave-Anstrengung außerhalb dieser Wave. Weiter mit Wave 7-8 |
| V6.29 | Natural-Language Automation | Automation Engine arbeitet vollständig auf semantischer Ebene (Trigger + Action + Property + Value aus natürlicher Sprache) | zurückgestellt – hängt direkt von V6.28 ab, siehe dort |

⸻

## 6a. Wave 7 – Integration (Ergebnis, 2026-08-13)

**Regressionen behoben:** keine – 1051 bestehende Tests liefen vor Wave 7
bereits grün (Wave 5 letzter Stand), unverändert.

**Interfaces/Datenfluss geprüft:** `engine.py::match()`/`_build_match_result()`
im Detail gelesen (nicht nur der Wave-5-Docstrings vertraut). Ergebnis:
Entity-Resolution passiert bereits **innerhalb der einzelnen Parser**
(`parsers.py`, über `resolve_entity_scored()`/`resolve_entities_by_domain()`),
bevor ein `SemanticFrame` überhaupt existiert – nicht danach, wie die
Zielarchitektur (Abschnitt 3, `Constraint Resolver → Capability Resolver →
Reasoning Engine`) es vorsieht. `ReasoningEngine.resolve()` (V6.25) an der im
Plan vorgesehenen Stelle (nach dem Command Validator, vor dem
Intent→Service-Dispatch in `_build_match_result()`) einzuhängen, würde daher
keine bestehende Stufe *ersetzen*, sondern eine **zweite, parallele
Entity-Resolution** neben der schon vorhandenen in `parsers.py` einführen –
Regel 6 ("no parallel search system") verletzt genau das. Eine echte
Integration bräuchte eine Umstellung der Entity-Resolution in **jedem**
Parser auf `constraint_resolver.resolve_candidates()` statt
`resolve_entity_scored()`/`resolve_entities_by_domain()` – ein eigener,
mehrschichtiger Migrationsschritt (deckungsgleich mit dem in Wave 3 bereits
bewusst zurückgestellten V6.6 "Home World Model vereinheitlichen"), keine
Wave-7-„Integration" im engeren Sinn. `SemanticComposer` (V6.4) liegt genauso:
er würde nur `frame.property`/`frame.quantity` befüllen, die aktuell von
keinem Konsumenten gelesen werden – reines Verdrahten ohne Verhaltensänderung
wäre Integrations-Theater.

**Entscheidung (Architect):** volles Verdrahten von `ReasoningEngine`/
`SemanticComposer` in die Produktionspipeline bleibt zurückgestellt, bis die
Parser-für-Parser-Migration der Entity-Resolution auf
`constraint_resolver.resolve_candidates()` als eigener Effort ansteht (deckt
sich mit Wave 0's Entscheidung "hassil schrittweise ablösen" – ein
Multi-Wave-Vorhaben, kein Einzelschritt). Legacy-Pfad vollständig intakt und
weiter alleiniger Produktionspfad; kein Fallback-Kaskaden-Code nötig, da
nichts umgeschaltet wurde. Kein HA-Integrationsrisiko: `conversation.py`s
Aufruf von `engine.match()`/`match_followup()`/etc. ist unverändert.

**Bestätigt in der Integration Wave (2026-08-19):** ein analog benannter
Migrationsschritt ("ReasoningEngine-Ambiguitäts-Gate", Command-Pfad) wurde
in der Automation-Integration-Wave erneut vorgeschlagen und aus genau
diesem Regel-6-Grund wieder gestrichen (Details: Brain-Knoten
`9d6519a8-4e76-4357-91c0-ad5d9e7c72a8`). Nutzer-Klarstellung dazu: das ist
**keine generelle Absage** an `ReasoningEngine`/`SemanticComposer` – das
Ziel bleibt ein gemeinsamer Semantic Core. Verbindlich bleibt nur:

- keine zweite Entity-Resolution im bestehenden Command-Pfad
- kein zweites Ambiguitäts-Gate neben `resolve_entity_scored()`
- keine parallele Resolver-Implementierung
- `ClarificationRequest`/die bestehende Ambiguitätslogik bleibt für den
  Command-Pfad autoritativ

Jeder künftige Integrationsschritt (Command, Query oder Automation) ist vor
der Umsetzung gegen diese vier Fragen zu prüfen:

1. Kann Reasoning bereits benötigte Informationen aus dem bestehenden
   Parser-Ergebnis übernehmen, statt sie neu aufzulösen?
2. Kann der Composer auf bereits aufgelösten semantischen Ergebnissen
   arbeiten, statt selbst neu zu resolven?
3. Können Follow-ups über den vorhandenen `ConversationContext` komponiert
   werden, statt einen neuen Context-Mechanismus zu bauen?
4. Können Automation, Query und Command gemeinsame semantische Strukturen
   nutzen, ohne dass dafür ein zweiter Resolver eingeführt wird?

Die oben skizzierte Parser-für-Parser-Migration auf
`constraint_resolver.resolve_candidates()` (V6.6-Nachfolgeaufwand) bleibt
der wahrscheinlichste erste Schritt, der Frage 1/2 bejaht, ohne einen
zweiten Resolver einzuführen (er *ersetzt* den bestehenden statt einen
neuen daneben zu stellen).

## 6b. Wave 8 – Validation (Ergebnis, 2026-08-13)

- **Regression:** 1059 Tests grün (`pytest -q`, venv
  `ha-nlu-engine-venv`), keine Fehlschläge.
- **Golden-Benchmark (§35-39/46):** 221 Fälle über 12 Kategorien (vorher
  213 über 11) – neu `multi_step.json` (8 reale "und"-Sätze), die einzige
  im Plan benannte Kategorie ohne bisherige Golden-Abdeckung
  (`engine.match()` liefert für diese Sätze ein `CommandPlan`, nicht ein
  einzelnes `MatchResult` – Generator (`scripts/generate_golden_tests.py`)
  und Replay (`tests/test_golden.py`) dafür erweitert). "Kontext"/
  "Pronomen"/"Vergleiche" bleiben ohne eigene Golden-JSON-Fälle – der
  JSON-Replay-Harness ist bewusst auf Einzelsatz-`match()` zugeschnitten,
  mehrstufige Szenarien (Context/Reference brauchen einen vorherigen Turn)
  hätten eine Harness-Erweiterung eigenen Umfangs gebraucht; diese drei
  Features haben stattdessen bereits dedizierte, grüne Unit-Testdateien
  (`test_context_followup.py`, `test_reference.py`,
  `test_engine_comparisons.py`) – bewusste Abgrenzung, keine Lücke ohne
  Netz. "Automation" entfällt (Wave 6 zurückgestellt).
- **Performance-Benchmark (§46, 100/500/1000/5000 Entities):** bereits
  vollständig von Wave 1 geliefert (`docs/perf/v6-baseline.md`,
  `scripts/benchmark_v6_baseline.py`) – da Wave 7 keine neue Pipeline-Stufe
  produktiv verdrahtet hat, bleibt diese Baseline weiterhin der aktuelle
  Stand; keine neue Messung nötig. Offene Empfehlung aus Wave 1 bleibt
  bestehen: `EntityIndex`/`build_entity_index()` ist gebaut, aber von
  keinem Parser genutzt – größter Hebel für eine künftige
  Entity-Resolution-Vereinheitlichung (s. Wave 7 oben).
- **Doku:** dieses Dokument aktualisiert (Abschnitte 6a/6b, Kopfzeile,
  V5-Korrektur). Keine neuen `docs/semantic-model.md`/`world-model.md`/
  `reasoning.md` angelegt – §44 nennt sie als mögliche Ziele, aber
  `architecture-v6.md` deckt denselben Inhalt bereits konsolidiert ab;
  zusätzliche separate Dateien wären Doku-Duplikation ohne neuen Inhalt.
  `README.md` bewusst nicht angefasst (aktives, unkommittiertes
  Nutzer-WIP).

⸻

## 6c. V6.6 – Home World Model vereinheitlichen (Ergebnis, 2026-08-13)

In Wave 3 zurückgestellt, in Wave 7 als der eigentliche Integrationsschritt
für ReasoningEngine/SemanticComposer identifiziert (siehe 6a) – hier als
eigenständiger, klar abgegrenzter Migrationsschritt umgesetzt (Commit
`932444d`).

**Konkreter Befund:** `constraint_resolver.resolve_candidates()` (V6.9) war
bereits ein Superset von `entities.resolve_entities_by_domain()` – identische
Domain/Area/Floor-Filterung, zusätzlich `device_class`/Capability-Filter.
`parsers.py` rief `resolve_entities_by_domain()` trotzdem an 8 Stellen direkt
auf, 4 davon mit einer zusätzlichen manuellen `device_class`-Listcomprehension
danach – dieselbe Filterlogik existierte damit an zwei Stellen parallel
(Regel-6-Verstoß im Kleinen).

**Umsetzung:** alle 8 Call-Sites (`QuantifierParser`, `ComparisonQueryParser`,
`AreaQueryParser`, `QueryFollowupParser` ×2, `ReferenceParser` ×2,
`StateQueryParser._device_class_candidates`) auf
`constraint_resolver.resolve_candidates()` umgestellt; die 4 Stellen mit
manuellem `device_class`-Filter nutzen jetzt `Constraints.device_class` statt
der eigenen Listcomprehension. Reiner Verhaltens-Erhalt (kein neuer Filter,
keine neue Semantik) – 1059 Tests unverändert grün, keine neuen Tests nötig
(Refactor, keine mockbaren Call-Sites in der Testsuite gefunden, die die
Änderung hätten maskieren können).

**Bewusst NICHT Teil dieser Migration:** Namensbasierte Auflösung
(`resolve_entity`/`resolve_entity_scored`) – laut `constraint_resolver.py`'s
eigenem Docstring explizit nicht dessen Aufgabe ("Deliberately out of scope
here ... name-based candidate scoring/ambiguity detection stays
`resolve_entity_scored()`'s job"). Das ist der Grund, warum Wave 7s
Regel-6-Befund weiterhin gilt: Entity-Resolution für den Regelfall ("mach die
Lampe an") läuft nach wie vor über `resolve_entity`/`resolve_entity_scored`
*innerhalb* des jeweiligen Parsers, bevor ein `SemanticFrame` existiert –
`ReasoningEngine.resolve()` an der geplanten Stelle in `engine.py` einzuhängen
würde also weiterhin eine zweite, parallele Resolution einführen. Diese
Migration schließt nur die Domain/Area/Floor/device_class-Lücke (strukturelle
Filterung), nicht die Namensauflösung – eine Migration von
`resolve_entity_scored()` auf einen konsistenten World-Model-Pfad wäre ein
eigener, deutlich größerer und riskanterer Schritt (ändert das Verhalten bei
mehrdeutigen/unscharfen Namen, nicht nur die interne Implementierung), der
hier nicht mitgemacht wurde.

**DoD-Update:** "World Model semantisch nutzbar" ist damit für die
strukturelle Filterung (domain/area/floor/device_class/capability) erfüllt –
`constraint_resolver.resolve_candidates()` ist jetzt der tatsächlich von den
Parsern genutzte Resolutionsweg dafür, nicht mehr nur eine ungenutzte
Parallel-Implementierung. "Queries und Commands nutzen dieselben Bausteine"
bleibt weiterhin nur teilweise erfüllt (Namensauflösung ist weiterhin pro
Parser dupliziert, wenn auch selbst schon Regel-6-konform über
`resolve_entity_scored()` zentralisiert). Volle ReasoningEngine-Verdrahtung
bleibt zurückgestellt, bis (falls gewünscht) auch die Namensauflösung
vereinheitlicht ist.

⸻

## 6d. World Model Wave – echtes `WorldModel`-Objekt (Ergebnis, 2026-08-14)

**Befund:** 6c hat nur die *strukturelle Filterung* (domain/area/floor/
device_class) vereinheitlicht, wie dort explizit vermerkt. Der Nutzer hat
zurecht eingeordnet, dass das kein "World Model" im Sinne der Vision war –
es gab kein Datenmodell, das Entities/Devices/Areas/Floors als *ein*
Objekt mit Beziehungen bündelt. Insbesondere fehlte **Devices** komplett
als eigenständiges Konzept: `hass_entities.py` griff auf den Device
Registry nur transient für den Area-Fallback einer einzelnen Entity zu
(`_area_info()`), es gab keine `DeviceSnapshot`, keine
Geräte-zu-Entities-Beziehung.

**Umsetzung:**
- `areas.py::_area_snapshots`/`floors.py::_floor_snapshots` → öffentlich
  (`area_snapshots`/`floor_snapshots`, identischer Body) – nötig, damit
  `world_model.py` sie wiederverwendet statt "Areas/Floors dieser
  Entities" ein drittes Mal abzuleiten (Regel 6).
- Neu: `devices.py::DeviceSnapshot` – hass-freies Dataclass, Peer von
  `EntitySnapshot`/`AreaSnapshot`/`FloorSnapshot` (device_id, name,
  manufacturer, model, area/floor-Felder, `entity_ids`). Bewusst kein
  `resolve_*` für gesprochene Gerätenamen – dafür existiert nirgends im
  Lexikon/in der Grammatik ein Beleg (niemals raten).
- Neu: `world_model.py::WorldModel` – bündelt `entities`/`devices`/
  `areas`/`floors` + `entity_index` + drei `Mapping`-Felder
  (`entities_by_id`, `devices_by_id`, `devices_by_area_id`,
  `device_id_by_entity_id`) sowie drei Beziehungs-Methoden
  (`device_for_entity`, `entities_for_device`, `devices_in_area`).
  `entities_for_device()` filtert `device.entity_ids` gegen die
  tatsächlich übergebene `entities`-Liste – ein Gerät kann Entities
  besitzen, die diesen Turn nicht ausgewählt/exponiert sind; die werden
  nie stillschweigend mit ausgeliefert. `build_world_model()` ruft nur
  `build_entity_index()`/`area_snapshots()`/`floor_snapshots()` auf, keine
  Neuimplementierung.
- `hass_entities.py`: zwei neue Bridge-Funktionen,
  `build_device_snapshots()` (Geräte mit ≥1 ausgewählter Entity, gleiche
  "nur was diesen Turn erreichbar ist"-Begrenzung wie
  `build_entity_snapshots()`; Namensvorrang `name_by_user or name or
  device_id`, dieselbe Präzedenz wie HA selbst) und `build_world_model()`
  (Entities + Devices holen, über `world_model.build_world_model()`
  bündeln).

**Nachtrag (2026-08-14, gleicher Tag):** Erste Fassung dieser Wave hatte
`WorldModel` bewusst nicht in `conversation.py` verdrahtet (Begründung
unten, ursprünglich identisch zu `ReasoningEngine`s Status). Nutzer hat das
zurecht zurückgewiesen: "es soll für HA fertig verdrahtet werden". Nachgezogen
in `conversation.py::_async_handle_message()` – `build_device_snapshots()`
wird jetzt bei jedem echten Conversation-Turn zusätzlich zu
`build_entity_snapshots()` aufgerufen und über `world_model.build_world_model()`
zu `self._world_model` gebündelt. `entities` (die tatsächlich an
`match()`/`match_followup()`/etc. übergebene Liste) bleibt exakt der
vorherige Aufruf, unverändert – `tests/test_conversation_integration.py`s
`monkeypatch.setattr(ha_conversation, "build_entity_snapshots", ...)` greift
weiterhin unverändert, keine Anpassung an dieser WIP-Datei nötig
(`build_device_snapshots()` liefert dort mangels ausgewählter Entities
einfach `[]`, kein Crash). `WorldModel` läuft damit ab sofort real in jedem
HA-Turn, nicht mehr nur in Tests – **aber** noch immer ohne Konsumenten:
kein Parser liest `self._world_model`, weil keine deutsche Grammatik heute
nach Geräte-Ebene fragt. Das ist kein technisches Defizit, sondern die
Grenze von "niemals raten" – eine neue Sprachfähigkeit dafür zu erfinden
wäre Scope, den niemand beauftragt hat. 1072 Tests weiterhin grün
(inkl. `test_conversation_integration.py`, unverändert).

**Weiterhin bewusst NICHT Teil dieser Wave:**
- `parsers.py`/`engine.py` auf Device-Daten migrieren – keine
  Satzvorlage fragt heute nach Geräte-Ebene; würde jeden Parser-Call-Site
  anfassen, ohne dass etwas Testbares dabei gewonnen wird.
- `AreaIndex`/`FloorIndex` (separates, bereits verzeichnetes V6.7-Item).
- Gesprochene Geräte-Namensauflösung ("welches Gerät") – keine
  Lexikon-Evidenz vorhanden.

**Tests:** `tests/test_devices.py` (3, hass-frei),
`tests/test_world_model.py` (5, hass-frei, handgebaute
Entity/Device-Fixtures), `tests/test_hass_entities_devices.py` (5,
Hass-Bridge-Ebene – nutzt `tests/_ha_stub.py::install()` read-only wieder,
da dessen Registry-Fakes fest auf `None` stehen; per-Test-Registry-Daten
über `monkeypatch` auf `hass_entities.er/dr/ar/fr` statt den geteilten
WIP-Stub selbst anzufassen). Gesamtsuite: 1059 → **1072 grün**
(`pytest -q`, venv `ha-nlu-engine-venv`), keine bestehende Testdatei
verändert.

**DoD-Update:** "World Model semantisch nutzbar" gilt jetzt sowohl für
die strukturelle Filterung (6c) als auch für ein echtes, bündelndes
Datenmodell mit Devices und Beziehungen (6d) – die Vision "500 Konzepte,
nicht 50.000 Sätze" hat damit erstmals ein reales Objekt, nicht nur einen
vereinheitlichten Filterpfad. Volle Pipeline-Verdrahtung (`conversation.py`,
Parser-Migration) bleibt offen für eine künftige Wave, sobald eine
Grammatik/ein Feature tatsächlich Device-Daten braucht.

⸻

## 6e. Conditions Wave – Trigger+Condition+Action (Ergebnis, 2026-08-19)

**Ziel:** `AutomationModel.conditions` (bis dahin strukturell vorhanden, aber
von `match_automation()` nie befüllt) für Sätze der Form "Wenn Trigger und
Condition, Action" nutzbar machen – ohne einen zweiten Parser, Resolver oder
Ambiguitäts-Mechanismus einzuführen (Regel 6).

**Bestandsanalyse-Ergebnis:** der Condition-Layer selbst war bereits fast
vollständig gebaut und getestet – `nlu/condition_model.py` (AST, 9
`ConditionType`-Werte über 10 Grammatik-Dateien), `automation_condition_parser.py`
(voller AND/OR/NOT-Ausdrucksparser, Tiefe 3, alle Leaf-Parser über dieselben
Resolver wie Trigger/Action) und `nlu/automation_validator.py`
(`_validate_condition_node()`) validierten Conditions bereits rekursiv, ohne
je aufgerufen zu werden. Die einzige echte Lücke war das Fehlen eines
Trigger/Condition-Splits im kombinierten Satz.

**Umsetzung:**

- `automation_condition_parser.py::split_on_top_level_and()` (neu, öffentlich):
  findet jeden echten Top-Level-"und"-Split-Punkt in einem Text, unter
  Wiederverwendung der bereits vorhandenen Zeitfenster-Maskierung
  (`_mask_time_window_and`/`_unmask_time_window_and`) – "zwischen 18 und 22
  Uhr" wird nie fälschlich als Split-Punkt erkannt.
- `engine.py::NluEngine._split_trigger_condition()` (neu, privat): Fallback
  in `match_automation()`, der nur läuft, wenn der volle Trigger-Text
  **nicht** als einzelner Trigger parst. Probiert jeden Split-Kandidaten
  gegen `AutomationTriggerParser`/`AutomationConditionParser` (beide bereits
  konstruierte Instanzen, keine neuen). Genau ein erfolgreicher Kandidat wird
  akzeptiert; null oder mehrere führen zu `None` – "niemals raten" auf
  Satzstruktur angewendet, nicht nur auf Entity-Auflösung.
- Reiner Trigger+Action-Satz (kein "und" im Trigger-Teil, oder der volle
  Text parst direkt) nimmt exakt denselben Pfad wie vor dieser Wave – der
  Fallback ist strikt nachrangig, keine Verhaltensänderung im Normalfall.

**Ausdrücklich nicht Teil dieser Wave** (siehe Wave-Plan, dem Nutzer vor
Umsetzung vorgelegt): OR-Verknüpfung auf Trigger-Ebene, `kein`/`keine` als
struktureller NOT-Marker bzw. ein `EXISTS`/`NOT_EXISTS`-`ConditionType`
(bestätigte Lücke, `_STRUCTURAL_TOKEN_RE` kennt nur `nicht`), Persistenz nach
Home Assistant, SemanticComposer-/ReasoningEngine-Erweiterung für Conditions
(kein erkennbarer Nutzen ohne Duplizierung bestehender Resolver-Logik),
ANY/ALL-Ausführungssemantik für Device-Class+Area-Targets mit mehreren
Kandidaten (Ausführungssemantik, kein Validierungsthema – diese Wave baut
keinen Executor).

**Tests:** 16 neue Tests (6 isoliert für `split_on_top_level_and()` in
`tests/test_automation_condition_parser.py`, 10 End-to-End über
`match_automation()` in `tests/test_engine_match_automation.py`, u. a.
Numeric/Time/Presence/Weekday-Condition, Ambiguität, unauflösbares Ziel,
Regressions-Fall ohne Condition). Vollständige Regression: 1376 passed, 14
skipped (vorher 1360 passed) – kein bestehender Test verändert.

⸻

## 6f. V5 Teil 7/10 – "Dry Run" Automation-Erstellung (Ergebnis, 2026-08-20)

**Ziel:** ein valides `AutomationModel` nicht länger nur beschreiben,
sondern – nach expliziter Bestätigung durch den Nutzer – tatsächlich als
HA-Automation persistieren. Vier neue/erweiterte Bausteine, strikt entlang
bestehender Grenzen (Regel 6: kein zweites Resolution-/Rendering-System),
Regel 4 ("niemals raten") auf jeder Stufe neu angewendet.

**Bausteine:**

- `nlu/automation_preview.py::render_automation_preview()` (V5.24): erste
  gesprochene Zusammenfassung ("Automation erkannt: Wenn …, dann … Soll
  diese Automation erstellt werden?") – getrennt von den bereits
  bestehenden `render_automation_tree()`/`render_condition_tree()`/
  `render_action_step()` Debug-Renderern. Erfindet nichts, was das Modell
  nicht hergibt (z. B. bleibt `PRESENCE` absichtlich richtungsneutral, da
  der Parser Ankunft/Verlassen nie unterscheidet).
- `nlu/context.py::PendingAutomationConfirmation` (V5.23): auf
  `ConversationContext` gehalten, mit höherer Priorität als
  `pending_clarification` in `conversation.py::_async_handle_message()`.
  Trägt nur das bereits validierte `AutomationModel` – Entities werden am
  Bestätigungs-Turn frisch aufgelöst, nichts vom Preview-Turn wird
  gecacht.
- `nlu/automation_confirmation.py::classify_confirmation_reply()`:
  geschlossenes Ja/Nein-Vokabular (`ConfirmationReply.YES/NO/UNCLEAR`) –
  kein Substring-Matching, keine Heuristik. `UNCLEAR` fragt erneut und
  behält die pending Confirmation; nur `NO` und jeder Generierungs-/
  Persistenzfehler löschen sie.
- `nlu/ha_automation_generator.py::generate_ha_automation_config()`
  (V5.25): reiner Übersetzer `AutomationModel` → HA-natives Config-Dict
  (moderne Plural-Schema-Keys `triggers`/`conditions`/`actions`, gegen den
  echten HA-Upstream-Quellcode verifiziert, nicht geraten). Löst jedes
  `TriggerTarget` frisch gegen die aktuelle Entity-Liste auf
  (`constraint_resolver.py`, dieselbe Logik wie
  `automation_action_parser.py`, dupliziert statt importiert – Grenze
  `nlu/` bleibt Hass-frei). Verweigert explizit (`GenerationError`) statt
  zu raten bei `TriggerType.DEVICE`/bare `WEEKDAY`, `ConditionType.DEVICE`/
  `DATE` und `ActionType.WAIT` – für diese gibt es keine verlustfreie
  native HA-Übersetzung.
- `automation_executor.py::AutomationExecutor` (V5.26): der **einzige**
  Ort im gesamten Automation-Track, der `automations.yaml` tatsächlich
  beschreibt. Bewusst **außerhalb** von `nlu/` (Top-Level von
  `custom_components/ha_nlu/`, wie `hass_entities.py`) – jedes `nlu/`-Modul
  bleibt Hass-frei. Read-Modify-Write hinter einem instanzweiten
  `asyncio.Lock()` (eine Instanz pro Config-Entry, lazy gebaut, da
  `self.hass` beim `__init__` noch nicht gesetzt ist), Datei-I/O über
  `hass.async_add_executor_job()`, danach `automation.reload` mit leeren
  Service-Daten (bewusst die immer-korrekte, vollständig belegbare
  Variante gewählt – ein `id`-scoped Reload-Argument ließ sich weder im
  Repo noch im Brain verifizieren).

**Turn-Ablauf:** Turn 1 (Automationssatz) → Preview + `PendingAutomation-
Confirmation` gesetzt, **kein** `hass.services.async_call()`. Turn 2
("Ja"/"Nein"/unklar) → `classify_confirmation_reply()` entscheidet; nur ein
klares "Ja" durchläuft `generate_ha_automation_config()` →
`AutomationExecutor.async_create_automation()` → `automation.reload`.

**Tests:** 91 neue Tests über 5 Dateien (`test_automation_confirmation.py`,
`test_automation_preview.py`, `test_ha_automation_generator.py` – jeder
Trigger-/Condition-/Action-Typ inkl. jedes `GenerationError`-Falls,
`test_automation_executor.py` – vollständig gemockte `hass`-I/O, keine
echten Datei-/HA-Schreibzugriffe, inkl. Lock-Serialisierungstest mit
erzwungenem Suspension Point, `test_conversation_automation_confirmation.py`
– volles Ja/Nein/Unklar-Roundtrip über die echte
`_async_handle_message()`-Orchestrierung inkl. echtem YAML-Roundtrip gegen
`tmp_path`). Vollständige Regression: 1467 passed, 14 skipped (vorher 1376
passed) – kein bestehender Test verändert außer der einen erwarteten
Anpassung in `test_case_6_automation_sentence_never_calls_a_service`
(prüft jetzt die gesprochene Preview statt des alten Debug-Baums, da genau
das der beabsichtigte Verhaltenswechsel dieser Wave ist).

⸻

## 6g. V5 Teil 8/10 (Wave 8a) – Identity, Metadata, Transaktionen, Rollback (Ergebnis, 2026-08-20)

**Ziel:** V5 Teil 8/10 umfasst zehn Punkte (V5.27–V5.36: Modification,
Deletion, Query, Identity, Metadata, Versioning, Conflict Detection, Safety
Classes, Transactions, Rollback). Modification/Deletion/Query brauchen
jeweils einen eigenen vollständigen Parser-/Grammatik-/Resolver-Stack,
vergleichbar mit einer ganzen früheren Wave – Conflict Detection und Safety
Classes setzen auf ihnen auf. Bewusste Scope-Einschränkung (Wave 8a): nur
das aktuell tragfähige Fundament umgesetzt – **V5.30 (Identity), V5.31
(Metadata), V5.32 (Versioning-Grundlage), V5.35 (Transactions), V5.36
(Rollback)**. V5.27–V5.29 (Modification/Deletion/Query) und V5.33/V5.34
(Conflict Detection/Safety Classes) bleiben ausdrücklich zukünftigen Waves
vorbehalten – sie brauchen ohnehin erst eine Möglichkeit, existierende
Automationen wiederzufinden (V5.29), bevor sie modifiziert/gelöscht werden
können.

**Kernfrage vorab (Regel 4, gegen den echten HA-Upstream-Quellcode
verifiziert, nicht geraten):** kann Metadata als zusätzliche Top-Level-Keys
direkt im Automation-Dict in `automations.yaml` mitgeführt werden? Nein –
`homeassistant/components/automation/config.py`'s `PLATFORM_SCHEMA` wird
über `script.make_script_schema({...}, script.SCRIPT_MODE_SINGLE)`
aufgebaut (`homeassistant/helpers/script.py`), und dieser Aufruf übergibt
kein `extra=vol.ALLOW_EXTRA` – der Default ist `vol.PREVENT_EXTRA`. Ein
unbekannter Top-Level-Key lässt `PLATFORM_SCHEMA(config)` mit `vol.Invalid`
fehlschlagen, und HA deaktiviert die Automation mit
`ValidationStatus.FAILED_SCHEMA` statt sie zu laden – genau das
"unbemerkt falsch" Ergebnis, das Regel 4 verhindern soll. Deshalb eine
physisch getrennte Sidecar-Datei statt Extra-Keys.

**Bausteine:**

- `automation_metadata_store.py::AutomationMetadataStore` (V5.30/V5.31/
  V5.32, NEU, Top-Level von `custom_components/ha_nlu/` wie
  `automation_executor.py` – bleibt aus demselben Grund außerhalb von
  `nlu/`): sidecar-JSON-Datei `ha_nlu_automation_metadata.json` im
  HA-Config-Verzeichnis, keyed nach der `automation_id` (dieselbe id, die
  `AutomationExecutor` auch als `id`-Feld in `automations.yaml` vergibt –
  Regel 6, kein zweites paralleles Id-Schema). Pro Eintrag: `created_by`
  (immer `"homeintent"` – v1 kennt keine andere Quelle), `version` (startet
  bei 1 – ohne V5.27/Modification gibt es noch nichts, was ihn je erhöht),
  `source_language` (immer `"de"` – v1 ist Deutsch-only), `source_text`,
  `created_at` (ISO-8601-UTC-String über `homeassistant.util.dt.utcnow()`).
- `automation_executor.py::AutomationExecutor.async_create_automation()`
  (V5.35/V5.36, erweitert): der komplette Ablauf
  Read → Append → Write → Reload → Metadata speichern läuft jetzt als eine
  Transaktion unter demselben `asyncio.Lock()`. Schlägt der Reload fehl,
  wird `automations.yaml` sofort auf den Stand vor dem Aufruf
  zurückgeschrieben. Schlägt stattdessen erst das Metadata-Speichern fehl,
  wird zusätzlich zum YAML-Rollback ein zweiter (best-effort,
  Exception-geschluckter) `automation.reload`-Aufruf ausgelöst, damit HAs
  Live-Zustand wieder zur zurückgerollten Datei passt. Der ursprünglich
  auslösende Fehler propagiert in beiden Fällen unverändert – ein
  Folgefehler beim Rollback-Reload maskiert ihn nie. Vor dieser Änderung
  konnte ein Reload-Fehler einen verwaisten Eintrag in `automations.yaml`
  hinterlassen, obwohl dem Nutzer ein Fehlschlag gemeldet wurde ("no
  half-created automations", V5.36s eigene Formulierung im Plan).

**Tests:** 5 neue Tests (`test_automation_executor.py`: erfolgreiche
Metadata-Aufzeichnung, Rollback bei Reload-Fehler, Rollback + zweiter
Reload bei Metadata-Fehler, Original-Fehler übersteht einen zweiten
Rollback-Reload-Fehler – alles mit vollständig gemocktem `hass`-I/O;
`test_conversation_automation_confirmation.py`: ein Metadata-Eintrag mit
der richtigen `automation_id` existiert nach einer echten "Ja"-Bestätigung
über die reale `_async_handle_message()`-Orchestrierung, mit echtem
JSON-Roundtrip gegen `tmp_path`). Vollständige Regression: 1472 passed, 14
skipped (vorher 1467/14) – kein bestehender Test verändert.

⸻

## 6h. V5 Teil 9/10 (Wave 9) – V5.29 "Automation Query" (Ergebnis, 2026-08-20)

**Ziel:** V5.29 aus dem in 6g zurückgestellten Rest von V5 Teil 8–10 –
existierende Automationen wiederfinden, als Voraussetzung für die dort
ebenfalls zurückgestellten V5.27/V5.28 (Modification/Deletion). Bewusst
enger Scope als der Name suggeriert – drei Query-Formen abgedeckt: "Welche
Automationen gibt es?" (Bare Listing), "Was schaltet/steuert X?"
(entity-gefiltert), "Warum ist/geht X …?" (dieselbe Filterung, nur
kausal-vorsichtiger formulierte Antwort). Ausdrücklich **nicht** in Scope:
Area-Filterung von Automationen, vollständige Trigger-/Condition-/
Action-Semantik-Rückableitung (nur flaches "entity_id irgendwo erwähnt"),
sowie COUNT/EXISTS-Scopes (nur LIST). Diese Grenzen waren eine autonome
Scope-Entscheidung zu Beginn der Wave, nicht vorab mit dem Nutzer
abgestimmt.

**Bausteine:**

- `automation_summary.py::AutomationSummary` (NEU, hass-frei): `automation_id`,
  `alias`, `source_text` (optional), `created_by` (optional),
  `referenced_entity_ids` (`frozenset[str]`) – bewusst nur "kommt diese
  entity_id irgendwo im Automation-Dict vor", keine Re-Interpretation von
  Trigger/Condition/Action-Semantik (siehe Scope-Grenze oben).
- `nlu/query_command.py::QueryTargetKind.AUTOMATION` (NEU, zweiter
  Extension-Point nach `DEVICE`): `QueryExecutor.execute()` nimmt einen
  zusätzlichen optionalen `automations`-Parameter, spiegelt das bestehende
  `world_model`-Muster für `DEVICE`.
- `nlu/query_executor.py::QueryExecutor._execute_automation()`: ohne
  `entity_id` werden alle übergebenen Automationen gelistet, mit
  `entity_id` gefiltert auf `entity_id in referenced_entity_ids`. 0 Treffer
  ist `EMPTY`, kein Fehler – dasselbe "0 ist eine normale Antwort"-Prinzip
  wie bei `_execute_plural`.
- `nlu/response_generator.py::ResponseGenerator._respond_automation()`:
  spricht `source_text` wenn vorhanden, sonst `alias` als Fallback. Kausale
  Formulierung (`HassAutomationWhyQuery`) hedged mit "könnte" statt
  Tatsachenbehauptung – die flache Entity-Referenz-Erkennung beweist keine
  echte Kausalität.
- `automation_executor.py::AutomationExecutor.async_list_automations()`
  (NEU): liest `automations.yaml` + Metadata-Sidecar, baut daraus die
  `AutomationSummary`-Liste. Rein lesend, kein Lock nötig (siehe Docstring
  dort zur Nebenläufigkeits-Begründung).
- `parsers.py::AutomationQueryParser` + zwei neue Intents
  (`HassAutomationQuery`/`HassAutomationWhyQuery`, 16. separat kompilierte
  Grammatik): unaufgelöster oder mehrdeutiger `{name}` wird abgelehnt
  (`None`, kein Klarstellungs-Roundtrip) – dasselbe "niemals raten"-Prinzip,
  das `StateQueryParser._parse_check_state` bereits für seine eigene
  `{name}`-Auflösung setzt.
- `engine.py`/`conversation.py`: `_AUTOMATION_QUERY_RE` als billiges
  Regex-Gate vor dem echten, blockierenden `automations.yaml`-Read –
  spiegelt `_AUTOMATION_TRIGGER_RE`s bereits bestehende Rolle für
  `match_automation()`. `automations` wird als expliziter Parameter an
  `match_automation_query()`/`AutomationQueryParser.parse()` durchgereicht,
  bewusst **nicht** in `ParseContext` aufgenommen (das würde einen
  Async-I/O-Read auf jedem Turn erzwingen, im Gegensatz zum billigen/
  synchronen `WorldModel`). `conversation.py` nutzt für den Read dieselbe
  lazily-konstruierte `AutomationExecutor`-Instanz, die die
  Automation-Erstellung bereits verwendet.
- `service_call.py::QUERY_INTENTS`: beide neuen Intents brauchten dort
  einen Eintrag – ein während der Implementierung übersehener Schritt
  (`nlu/validator.py`s Schritt 1 lehnt jeden nicht registrierten Intent mit
  `UNKNOWN_INTENT` ab), durch die Tests in dieser Wave selbst gefunden und
  gefixt. `allowed_domains` ist dabei bewusst **nicht** leer wie bei
  `HassDeviceQuery` – anders als DEVICE-Queries befüllt die
  entity-gefilterte AUTOMATION-Form `command.entities` mit der aufgelösten
  Ziel-Entity (damit die Antwort sie benennen kann), eine leere Menge hätte
  Schritt 5 (Domain-Check) jeden echten Treffer verwerfen lassen. Verwendet
  stattdessen `_AUTOMATION_QUERY_ALLOWED_DOMAINS` – die Vereinigung aller
  Domains, die diese Datei an anderer Stelle bereits als gültig behandelt
  (`light`, `switch`, `fan`, `climate`, `cover`, `sensor`, `binary_sensor`),
  statt einer neu erfundenen Liste (Regel 4).

**Tests:** 30 neue Tests über 5 Dateien (`test_automation_summary.py`: 3;
`test_query_executor.py`: +4 AUTOMATION-Fälle; `test_response_generator.py`:
+9 für jeden Antwort-Zweig von `_respond_automation()`;
`test_engine_automation_query.py`, NEU: 8 direkte
`match_automation_query()`-Tests inkl. Regex-Gate und "niemals
raten"-Ablehnung bei unaufgelöstem/mehrdeutigem Namen;
`test_conversation_automation_query.py`, NEU: 6 E2E-Tests über die echte
`_async_handle_message()`-Orchestrierung, inkl. eines Tests, der beweist,
dass `async_list_automations()` für eine gewöhnliche Steuerungs-Anweisung
gar nicht erst aufgerufen wird). Vollständige Regression: 1502 passed, 14
skipped (vorher 1472/14) – kein bestehender Test verändert.

⸻

## 6i. V5 Teil 8/10 (Wave 10) – V5.28 "Automation Deletion" (Ergebnis, 2026-08-20)

**Ziel:** V5.28 aus dem in 6g/6h zurückgestellten Rest von V5 Teil 8–10 –
eine per Entity-Referenz eindeutig identifizierte Automation nach
Sprachbestätigung löschen. Bewusst eng geschnitten: nur DELETE, nicht
DISABLE/ENABLE (verifiziert gegen echten Upstream-Code – `automation.
turn_on`/`turn_off` sind reine Runtime-Service-Calls ohne jede
`automations.yaml`-Schreiboperation, ein grundlegend anderer Mechanismus als
dieser Wave YAML-mutierender Delete-Pfad, siehe `automation_executor.py`s
`async_delete_automation()`-Docstring). Ebenfalls **nicht** in Scope:
Area-basiertes Löschziel, mehrdeutige Namen werden abgelehnt statt
geraten – dieselbe Single-Entity-Referenzauflösung, die V5.29s
`AutomationQueryParser` bereits etabliert hat, nicht ein zweiter,
eigenständig erfundener Targeting-Mechanismus. Diese Grenzen waren eine
autonome Scope-Entscheidung zu Beginn der Wave, nicht vorab mit dem Nutzer
abgestimmt.

**Bausteine:**

- `automation_executor.py::AutomationExecutor.async_delete_automation()`
  (NEU): entfernt die Automation mit passender `id` aus
  `automations.yaml`, ruft `automation.reload`, löscht den
  Metadata-Sidecar-Eintrag (`AutomationMetadataStore.async_delete()`, war
  aus Wave 8a bereits vorhanden und wurde direkt wiederverwendet). Läuft
  unter demselben Instanz-Lock wie `async_create_automation()`, mit
  identischem Rollback-bei-Reload-Fehler-Verhalten (V5.35/36-Prinzip "keine
  YAML-Datei, die von dem abweicht, was dem Nutzer gesagt wurde", jetzt auch
  für den Lösch-Pfad). Bewusste, dokumentierte Abweichung von Upstreams
  eigenem HTTP-Delete-Endpunkt (`EditIdBasedConfigView`/`post_write_hook`),
  der nach dem Löschen *nicht* neu lädt und nur die Entity-Registry bereinigt
  – verifiziert gegen `homeassistant/components/automation/__init__.py`,
  dass das die laufenden Trigger einer gelöschten Automation nicht stoppt.
  `ValueError` bei unbekannter `id` (nur bei echter Race zwischen Auflösung
  und Bestätigung erreichbar, da die `id` Sekunden zuvor aus einem frischen
  `async_list_automations()`-Read stammt).
- `nlu/context.py::PendingAutomationDeletion` (NEU) + neues Feld
  `pending_automation_deletion` auf `ConversationContext`: Gegenstück zu
  `PendingAutomationConfirmation`, gleiches Muster (frozen Dataclass, in
  `ConversationContextStore` gehalten, per gemeinsamer
  `classify_confirmation_reply()`-Vokabular aufgelöst – Regel 6, kein
  zweites Ja/Nein-Vokabular).
- `parsers.py::AutomationDeleteParser` + neuer Intent
  `HassAutomationDelete` (17. separat kompilierte Grammatik,
  `intents/de/automation_delete/automation_delete.yaml`): `{name}` ist hier
  pflicht (anders als V5.29s "welche Automationen gibt es?" ohne Ziel) – ein
  zielloses "lösche die Automation" hieße "lösche alle", das wird nie
  geraten. Wiederverwendet `AutomationQueryParser`s
  entity-gefilterte Auflösung (`resolve_entity_scored` → Filter auf
  `entity_id in referenced_entity_ids`), keine zweite Targeting-Logik.
  Liefert `AutomationDeleteMatch` (Entity + alle Treffer, 0/1/2+) – die
  Kardinalitäts-Entscheidung selbst liegt bei `engine.py`, nicht beim
  Parser (gleicher Split wie `QueryExecutor`/`ResponseGenerator`).
- `engine.py::match_automation_delete()` + `AutomationDeletionMatchResult`
  (NEU): `_AUTOMATION_DELETE_RE` als billiges Regex-Gate. Bewusst **nicht**
  die bestehende Query-Pipeline (`QueryCommand`/`QueryExecutor`)
  wiederverwendet – deren Kardinalitäts-Handling behandelt jeden Treffer
  ≥1 als `MATCHED` (richtig zum Auflisten, falsch für ein eindeutiges
  Löschziel). Stattdessen eine parallele, aber einfachere
  Ergebnis-Form: 0 Treffer → Ablehnung ("Ich habe keine Automation
  gefunden, die X steuert."), 2+ Treffer → eigene Ablehnung ("Das kann ich
  nicht eindeutig löschen."), genau 1 Treffer → gesprochene Bestätigungsfrage
  mit `_automation_label()` (aus `nlu/response_generator.py`
  importiert/wiederverwendet, nicht dupliziert).
- `conversation.py`: neuer Match-Cascade-Schritt für
  `_AUTOMATION_DELETE_RE`, bewusst **vor** dem bestehenden
  `_AUTOMATION_QUERY_RE`-Schritt platziert – Lösch-Sätze enthalten auch das
  Wort "Automation" und würden sonst unnötig zuerst einen zweiten,
  erfolglosen Query-Pfad-Read auslösen. Dieselbe lazily-konstruierte,
  Entity-Lifetime-`AutomationExecutor`-Instanz wie Query/Creation.
  `_async_handle_automation_deletion_confirmation_reply()` spiegelt
  `_async_handle_automation_confirmation_reply()`s Form 1:1 (UNCLEAR
  re-asked mit erhaltenem Pending-State, NO/Fehler löschen den Context und
  löschen nichts, nur ein klares YES ruft
  `async_delete_automation()` auf).

**Tests:** 21 neue Tests über 3 Dateien (`test_automation_executor.py`: +5
für `async_delete_automation()` inkl. Not-Found, Reload-Rollback,
Metadata-Löschung; `test_engine_automation_delete.py`, NEU: 8 direkte
`match_automation_delete()`-Tests inkl. Regex-Gate, 0/1/2+-Kardinalität,
"niemals raten"-Ablehnung bei unaufgelöstem/mehrdeutigem Namen, Fallback auf
`alias` ohne `source_text`; `test_conversation_automation_delete.py`, NEU: 8
E2E-Tests über die echte `_async_handle_message()`-Orchestrierung – Ja/Nein/
Unclear-Rundlauf, 0/2+-Treffer-Ablehnung ohne Pending-State, sowie ein Test,
der beweist, dass `async_list_automations()` für eine gewöhnliche
Steuerungs-Anweisung gar nicht erst aufgerufen wird). Vollständige
Regression: 1523 passed, 14 skipped (vorher 1502/14) – kein bestehender Test
verändert.

⸻

## 6j. V5 Teil 8/10 (Wave 11) – V5.28 Rest "Automation Disable/Enable" (Ergebnis, 2026-08-20)

**Ziel:** der in Wave 10 (6i) bewusst zurückgestellte Rest von V5.28 –
eine per Entity-Referenz eindeutig identifizierte Automation per Sprache
dauerhaft deaktivieren/aktivieren.

**Regel-4-Korrektur gegenüber Wave 10:** Wave 10s Doku (6i) behauptete,
DISABLE/ENABLE brauche zwingend `automation.turn_on`/`turn_off`-
Service-Calls ohne jede `automations.yaml`-Schreiboperation – korrekt für
diese beiden Service-Calls selbst, aber nicht vollständig: gegen echten
Upstream-Code verifiziert (`homeassistant/components/automation/
config.py` + `homeassistant/components/automation/__init__.py`) existiert
mit `initial_state` (`CONF_INITIAL_STATE`) ein YAML-Config-Key, der beim
Setup/Reload gelesen wird und Vorrang vor jedem zuvor persistierten
Runtime-Zustand hat – explizit bestätigt: ein `automation.turn_off` gefolgt
von `automation.reload` reaktiviert die Automation wieder, sofern
`initial_state` nicht explizit `false` gesetzt ist. Das macht `initial_state`
den einzigen dauerhaften Deaktivierungsmechanismus ohne Service-Calls –
und erlaubt, denselben Read-Modify-Write-Reload-Rollback-Pfad wie
`async_delete_automation()` wiederzuverwenden, ganz ohne Entity-Registry-
Mapping (das der Test-Stub ohnehin nicht unterstützt hätte).

**Bausteine:**

- `automation_summary.py::AutomationSummary.enabled` (NEU, Feld, Default
  `True`): spiegelt den `initial_state`-Key 1:1.
- `automation_executor.py::AutomationExecutor.async_disable_automation()`/
  `async_enable_automation()` (NEU): beide delegieren an eine private
  `_async_set_initial_state()`, die `initial_state` im passenden Eintrag
  von `automations.yaml` setzt (Enable setzt ihn explizit auf `True`, statt
  den Key nur zu entfernen – genauso ausdrücklich reversibel wie das
  Deaktivieren) und danach `automation.reload` ruft. Gleiches
  Transaktions-/Rollback-Muster wie `async_delete_automation()`: Lock,
  Rollback bei Reload-Fehler, `ValueError` bei unbekannter `id`.
  `async_list_automations()` liest `initial_state` (Default `True`) jetzt
  mit in jede `AutomationSummary`.
- `parsers.py::AutomationToggleParser` + zwei neue Intents
  `HassAutomationDisable`/`HassAutomationEnable` (18. separat kompilierte
  Grammatik, `intents/de/automation_toggle/automation_toggle.yaml`):
  `{name}` ist pflicht (dieselbe "kein zielloses Massen-Kommando"-Regel wie
  beim Löschen). Ein Parser für beide Intents, unterschieden durch ein
  zusätzliches `enable: bool`-Feld auf `AutomationToggleMatch`. Identifiziert
  die Automation über dieselbe entity-gefilterte Auflösung wie
  `AutomationDeleteParser`/`AutomationQueryParser` – kein dritter,
  eigenständig erfundener Targeting-Mechanismus.
- `engine.py::match_automation_disable()`/`match_automation_enable()` +
  gemeinsame private `_match_automation_toggle()` + `AutomationToggleMatchResult`
  (NEU): zwei billige Regex-Gates, `_AUTOMATION_DISABLE_RE`
  (`\bdeaktivier\w*\b`) und `_AUTOMATION_ENABLE_RE` (`\baktivier\w*\b`,
  wortgrenzensicher – matcht nicht versehentlich in "deaktiviere"). 0/2+
  Treffer → Ablehnung wie beim Löschen, genau 1 Treffer → sofortige
  Ausführung, **keine** Ja/Nein-Bestätigung.
- **Bewusste Design-Entscheidung – kein Bestätigungs-Rundlauf:** anders als
  Erstellung/Löschung (die praktisch irreversibel bzw. schwer rückgängig
  zu machen sind) ist ein Toggle trivial reversibel – einfach den
  gegenteiligen Satz sagen. Deshalb wird hier kein drittes Pending-State-
  Konstrukt neben `PendingAutomationConfirmation`/`PendingAutomationDeletion`
  eingeführt (Regel 6); die Ausführung erfolgt direkt im selben Turn wie ein
  gewöhnlicher TURN_ON/TURN_OFF-Befehl.
- `conversation.py`: zwei neue Match-Cascade-Schritte für
  `_AUTOMATION_DISABLE_RE`/`_AUTOMATION_ENABLE_RE`, platziert nach dem
  Lösch-Gate und vor dem Query-Gate (gleicher Grund wie bei Delete: die
  Sätze enthalten ebenfalls das Wort "Automation"). Neuer
  `isinstance(result, AutomationToggleMatchResult)`-Zweig: löscht
  vorsorglich den Context, führt bei genau einem Treffer sofort
  `async_enable_automation()`/`async_disable_automation()` aus, fängt
  Ausführungsfehler mit `FAILED_TO_HANDLE` ab.

**Tests:** 26 neue Tests über 3 Dateien (`test_automation_executor.py`: +7
für Disable/Enable inkl. Not-Found, Reload-Rollback in beide Richtungen,
`enabled`-Feld in `async_list_automations()`; `test_engine_automation_toggle.py`,
NEU: 13 direkte Tests für beide Richtungen inkl. Regex-Gates,
Wortgrenzen-Test "deaktiviere" löst nicht auch das Enable-Gate aus, 0/1/2+-
Kardinalität, "niemals raten"-Ablehnung; `test_conversation_automation_toggle.py`,
NEU: 6 E2E-Tests über die echte `_async_handle_message()`-Orchestrierung –
Disable/Enable ohne Bestätigungs-Rundlauf, Beweis dass ein "Ja" danach nur
ein gewöhnlicher unmatchter Folgesatz ist, 0/2+-Treffer-Ablehnung ohne
Datei-Mutation, sowie ein Kosten-Gate-Test). Vollständige Regression: 1549
passed, 14 skipped (vorher 1523/14) – kein bestehender Test verändert.

⸻

## 7. Sicherheitsregeln

- **Niemals bei echter Ambiguität raten.** Je unsicherer die
  Interpretation, desto weniger darf HomeIntent handeln: eindeutig
  ("Schalte die Deckenlampe im Wohnzimmer aus.") → ausführen; mehrdeutig
  ("Schalte die Lampe aus.") → Rückfrage; unklar ("Mach es.") → Rückfrage.
  Niemals aus Bequemlichkeit raten.
- **Kein automatisches Lernen.** Kein "User sagte X → speichere X
  dauerhaft" ohne kontrollierten Mechanismus. Ein späteres
  Alias-/Lernsystem muss kontrolliert, nachvollziehbar und reversibel sein.
- **Fallback-Kaskade während der Migration:** Neue Semantic Engine →
  sicher verstanden → Semantic Result; nicht sicher verstanden → Legacy
  Parser. Der Legacy-Parser darf die neue Architektur nicht blockieren,
  bestehende Parser werden nicht sofort gelöscht (pro Parser prüfen:
  vollständig ersetzbar vs. als spezialisierter Recognizer
  weiterverwendbar).
- **Performance-Grenze:** Muss auf Raspberry-Pi-Klasse Hardware laufen –
  keine ML-Inferenz/GPU/Netzwerkrequests/externe APIs, keine unnötigen
  vollständigen Entity-Scans, keine mehrfachen HA-Registry-Zugriffe pro
  Request.
- **Teststrategie ohne Testinflation:** pro Kernfeature 1-3 Unit-Tests +
  1 Integrationstest + 1 Ambiguity-Test (falls relevant) + wenige
  Golden-Tests für sprachliche Varianten; ~100 hochwertige reale
  Golden-Eingaben statt hunderter Satzvarianten. Bestehende Tests müssen
  als Regression weiterlaufen.

⸻

## 8. Verweis auf Brain

Dieses Dokument ist die **Kurzfassung/Landkarte** für den V6-Umbau, **nicht
die einzige Quelle der Wahrheit**. Vollständige Begründungen, Beispielsätze
je Phase und die laufende Status-Historie liegen im Brain-Knowledge-Graph
(`localhost:3000`, MCP-Tool `brain_get`):

| Node-ID | Inhalt |
|---|---|
| `247360ab-8493-42e4-8aef-bd4d0b95b1db` | Teil 1/7 – Vision, Grundregel, Architekturregeln R1-R7 |
| `52ae9a3a-c380-4a26-9a49-ce8b1db94367` | Teil 2/7 – Zielarchitektur, Primitives/Frame/Lexicon |
| `755ef579-e0ba-43b7-bba9-1596c11854cd` | Teil 3/7 – Composer, World Model, Reasoning-Bausteine |
| `2a0871f8-05a4-4e0d-8cb6-80a8ff939480` | Teil 4/7 – Reference, Context, Locations, Quantity etc. |
| `c3ddab01-2beb-40aa-8a43-e4ea43045957` | Teil 5/7 – Query Semantics, State Reasoning, Reasoning Engine |
| `8124f839-9a72-4f83-9d39-ccff0fedbb3f` | Teil 6/7 – Automation, Performance, Teststrategie, Migration, Sicherheit |
| `c2cfa095-9a1b-46c0-a9b9-fd542fffe3f4` | Teil 7/7 – Definition of Done, Leitprinzip, Endziel |
| `15884008-4107-4f8b-8227-e0de518c745c` | Wave 0: Architektur-Bestandsaufnahme + die 4 bestätigten Architekturentscheidungen |

Bei Widerspruch zwischen diesem Dokument und dem Brain gilt: den Brain
konsultieren und dieses Dokument nachziehen (`brain_recall`/`brain_get`,
Details siehe `/home/philipp/CLAUDE.md`). Nach jedem abgeschlossenen
V6.x-Schritt sollte die Statusspalte in Abschnitt 6 aktualisiert werden.
