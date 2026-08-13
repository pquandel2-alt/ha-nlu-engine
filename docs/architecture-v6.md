# v6 – Semantic Intelligence Architecture

Referenz: Brain-Knoten `247360ab-8493-42e4-8aef-bd4d0b95b1db` bis
`c2cfa095-9a1b-46c0-a9b9-fd542fffe3f4` (Teil 1/7 – 7/7 des HomeIntent-Plans
V6) sowie `15884008-4107-4f8b-8227-e0de518c745c` (Wave-0-Bestandsaufnahme,
2026-08-13). Dieses Dokument ist die **Kurzfassung/Landkarte** für den
V6-Umbau im Repo – die vollständigen Begründungen, Beispiele und
Detail-Spezifikationen pro Phase liegen im Brain-Knowledge-Graph (siehe
Abschnitt 8). Stand: Wave 3 (Capability Reasoning + Constraint Resolver), HEAD `2d3a9e7`.

Vorstufe: `docs/architecture-v4.md` (v4 – Advanced Natural Language,
abgeschlossen). v5 (Automation Engine) läuft parallel und ist nicht
Gegenstand dieses Dokuments.

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
| V6.6 | Home World Model | Entity-Modell zu semantischer HA-Sicht erweitern (Entities, Devices, Areas, Floors, Domains, Device Classes, Capabilities, States, Attributes, Aliases, Relationships); HA bleibt Quelle der Wahrheit | nicht begonnen |
| V6.7 | World Model Indexes | Performance-Indizes (domain, device_class, area, floor, capability, alias); States nicht unkontrolliert dauerhaft cachen | nicht begonnen |
| V6.8 | Capability Reasoning | Benötigte Capability aus Semantik ableiten, inkompatible Entities ausschließen | **abgeschlossen** (`nlu/capabilities.py::required_capability_for_property`) |
| V6.9 | Constraint Resolver | Neue Komponente: sucht Entities, die ALLE Constraints erfüllen, bevor Quantity angewendet wird | **abgeschlossen** (`nlu/constraint_resolver.py`, domain/area/floor/device_class/property) |
| V6.10 | Ambiguity Reasoning | Bei mehreren gleichwertigen Kandidaten: `AMBIGUOUS_ENTITY` + konkrete Rückfrage statt zufälliger Auswahl | bereits vorhanden vor V6 (`entities.py::resolve_entity_scored` Margin=5 + `ClarificationRequest`), von Constraint Resolver bewusst wiederverwendet statt dupliziert |
| V6.11 | Reference Resolution | Pronomen/Referenzen ("es/sie/das/dort/hier/wieder/die anderen/das gleiche") semantisch über Context auflösen | nicht begonnen |
| V6.12 | Semantic Context | `ConversationContext` über Text-History hinaus erweitern (last_intent, last_action, last_target, last_property, last_value, pending_reference, ...); nicht global mutable | nicht begonnen |
| V6.13 | Relative Locations | "hier/dort/oben/unten/nebenan/drüben/im selben Raum"; ohne eindeutige Interpretation Rückfrage statt erfundener Position | nicht begonnen |
| V6.14 | Quantity Semantics | Internes `QuantityConstraint`-Modell (alle/beide/drei/ein paar/alle außer...) statt Satzregeln | nicht begonnen |
| V6.15 | Degree Semantics | "etwas/leicht/deutlich/viel/komplett" → SLIGHT/MODERATE/STRONG/MAXIMUM/MINIMUM | nicht begonnen |
| V6.16 | Number Normalization | "50/50%/fünfzig Prozent" etc. → einheitliches `NumericValue` | nicht begonnen |
| V6.17 | Comparison Semantics | "mehr als/mindestens/höchstens" → `Comparison(operator, value)`, generisch statt an Prozent/Temperatur gekoppelt | nicht begonnen |
| V6.18 | Query Semantics | Queries und Commands nutzen dieselben Bausteine, Unterschied nur in der Operation | nicht begonnen |
| V6.19 | State Reasoning | HA-Zustände semantisch normalisieren UNTER Berücksichtigung der device_class (nicht pauschal on=OPEN) | nicht begonnen |
| V6.20 | Natural Query Language | Verschiedene Frageformen ("sind offen?"/"noch offen?"/"gibt es offene...?") auf dieselbe Semantik abbilden | nicht begonnen |
| V6.21 | Natural Command Language | Analog für Commands: viele Formulierungen → dieselbe Action/Target/Property-Kombination | nicht begonnen |
| V6.22 | Multi-Command Semantics | `CommandPlan` mit mehreren Commands, gesamter Plan wird vor Ausführung validiert (nicht Ad-hoc-Split) | nicht begonnen |
| V6.23 | Natural Context | Folgeäußerungen ohne neue vollständige Satzregeln, Reference auf `previous_target` | nicht begonnen |
| V6.24 | Explainability | Debug-Modus: INPUT→LINGUISTIC→SEMANTIC FRAME→WORLD MODEL candidates→CAPABILITY FILTER→CONSTRAINT RESOLUTION→FINAL TARGET/COMMAND | nicht begonnen |
| V6.25 | Reasoning Engine | Neue zentrale Komponente: Frame+Context+WorldModel+Capabilities+Constraints → `ResolvedSemanticIntent`, keine Service-Calls | nicht begonnen |
| V6.26 | Resolved Semantic Intent | Neues Modell mit vollständig aufgelöster Bedeutung, danach Command Validator → ServiceMapper | nicht begonnen |
| V6.27 | Query Result | Strukturierte Query-Ergebnisse (operation, status, entities, count); 0 Treffer = SUCCESS+EMPTY, nicht NO_INTENT_MATCH | nicht begonnen |
| V6.28 | Automation Foundation | V5-Automationen nutzen dieselben Semantic Frames/Resolver, keine eigene parallele Sprachlogik | nicht begonnen |
| V6.29 | Natural-Language Automation | Automation Engine arbeitet vollständig auf semantischer Ebene (Trigger + Action + Property + Value aus natürlicher Sprache) | nicht begonnen |

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
