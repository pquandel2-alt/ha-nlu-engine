# HomeIntent V8 – Architektur-Audit, Gap-Analyse und Migrationsplan

Stand: 7. September 2026
Audit-Basis: Commit `c7ec22b`, Release `4.71.0`

## 1. Auftrag und Prüfmethode

Dieser Bericht ist die verpflichtende Bestandsaufnahme vor der ersten
V8-Codeänderung. Untersucht wurden die vollständige Produkt- und Teststruktur,
die zentralen NLU-Module, Conversation-Routing, World Model und House Graph,
Query- und Automation-Modelle, Dialogzustand, Entity Resolution, Capability-
und Policy-Grenzen, Service Mapping und Ausführung sowie CI, Sprach-Evaluation,
Shadow-Vergleich und Performance-Dokumentation.

Der Quellbaum enthält 144 Python-Produktmodule mit rund 43.000 Zeilen, 170
Python-Testdateien mit rund 30.000 Zeilen, 50 Intent-YAML-Dateien und 538
satzartige YAML-Einträge. Im Produktcode gibt es 290 `re.compile()`-Aufrufe
und insgesamt 642 direkte Aufrufe der untersuchten `re`-Matchingfunktionen.
Diese Zahlen belegen keine Fehler für sich; sie zeigen aber, dass eine neue
Relationsschicht die vorhandenen Oberflächenmatcher schrittweise ablösen muss,
statt eine weitere gleichartige Sammlung daneben zu stellen.

Verifizierter Ausgangsstand:

- Sprach-Evaluation: 124 Tests bestanden.
- Gesamtsuite vor der Migration: 2.892 Tests bestanden, 12 übersprungen, ein
  bereits vorhandener Release-Metadatenfehler. `manifest.json` nannte 4.71.0,
  während README, CI-Shadow-Pfad und versionierter Bericht noch 4.70.0
  referenzierten. Die Metadaten wurden nach dem Audit mit einem neu
  berechneten, inhaltlich identischen 4.71.0-Shadow-Report abgeglichen.
- Pyflakes: ohne Befund.
- Read-only Shadow-Lauf: 3.772 Turns, 3.752 identisch, 20 beidseitig ohne
  Einzelturn-Treffer, keine Divergenz und keine Query-/Unsafe-/Ambiguous-
  Action-Leakage. Die 20 Fehlschläge enthalten überwiegend kontextabhängige
  Folgeturns, die der Einzelturn-Shadow bewusst ohne Dialogzustand auswertet.
- Kurzer lokaler `understand`-Benchmark mit 10 Messungen je Fall: bei 5.000
  synthetischen Entities lagen alle bestehenden sieben Fälle unter 100 ms
  p95; der höchste beobachtete Wert war rund 62,7 ms für die freie
  Query-Wortstellung. Die Stichprobe ist kleiner als das CI-Gate und ersetzt
  keine Messung auf Raspberry-Pi-/HA-Zielhardware.

## 2. Aktive Ist-Architektur

Der produktive direkte Gerätepfad ist heute:

```text
Text + Registry-Snapshot
  -> normalize/analyse_language
  -> SemanticUtterance + SemanticAnalysis
  -> SemanticInterpreter
  -> RegisteredOperationCompiler oder SemanticCommand/QueryCompiler
  -> ParseResult/SemanticFrame
  -> SemanticCommand
  -> Validator
  -> ReasoningEngine als Konsistenzprüfung
  -> ServiceMapper oder QueryExecutor
  -> UnderstandingOutcome
  -> Conversation-Routing
  -> ExecutionPolicy/Bestätigung
  -> einziger physischer ServiceExecutor
```

Dieser Pfad ist sicherer und stärker vereinheitlicht als die historischen
Parserpfade. Er ist jedoch noch kein struktureller Parser: Satzart, Klauseln,
Aktionen, Eigenschaften, Zustände und Ziele werden überwiegend mit Regex,
Lexikonspans, Wortmengen, Textumschreibungen und priorisierten Spezialfällen
erkannt. Beziehungen zwischen den Spans werden nicht in einem gemeinsamen
Modell erhalten.

Automationen besitzen bereits reichere, getrennte Zielmodelle:

```text
Automation-Regex/Hassil-Split
  -> TriggerModel
  -> ConditionNode(AND/OR/NOT, ConditionModel leaves)
  -> ActionModel/ActionGroup
  -> AutomationModel
  -> AutomationValidator
  -> Preview + explizite Bestätigung
  -> HA-Automationsgenerator
  -> AutomationExecutor
```

Die logischen Automationsmodelle sind wiederverwendbare Domainziele. Ihre
Spracherzeugung ist aber weiterhin an eigene Hassil-/Regex-Parser gebunden und
nicht das Ergebnis einer gemeinsamen Satz- und Bedeutungsstruktur.

`conversation.py::_async_handle_message()` erstellt pro Turn genau einen
Entity-/Device-Snapshot, ein `WorldModel`, einen `HouseGraph` und ein
`LanguageDocument`. Anschließend werden Dialogzustände und zahlreiche
Fachrouter noch in fester Reihenfolge geprüft. Ein Teil dieser Router erzeugt
typisierte `UnderstandingOutcome`s, andere liefern eigene Ergebnisobjekte oder
direkte `ServiceCallPlan`s. Der gemeinsame Executor und die Policy bleiben
trotz dieser Orchestrierungsfragmentierung die letzte Schreibgrenze.

## 3. Komponentenbefund

| Bereich | Vorhanden und wiederzuverwenden | Fehlende oder begrenzte Funktion |
|---|---|---|
| `LanguageDocument` | Originaltext, Quellspannen, Tokens, kostenbehaftete Varianten, Utterance und Lexikonanalyse | Keine Satzstruktur, Wortarten, Phrasen, Dependenzen oder Reparatursegmente; Semantik wird nur für eine Oberfläche gehalten |
| `SemanticUtterance` | Speech Act, Modalität, globale Polarität, grobe Klauselrollen, konservatives `safe_to_execute_directly` | Satzart und Klauseln sind Regex-klassifiziert; Negation ist global; nur erster Trigger-/Condition-Split; kein Scope-Baum |
| `SemanticTurn` | Bündelt Utterance, Lexikonanalyse, Zeitperspektive und grobe Koordination | Koordination ist ein globales Enum; keine Operanden oder Bindungsbereiche |
| `SemanticAnalysis` | Zentraler spanbasierter Katalog mit Konflikt- und Residualtoken-Erkennung | Bedeutungswörter sind flach; keine Argumentrollen oder Beziehungen; Füllwortliste enthält unter anderem `nicht` und kann keine lokale Rolle darstellen |
| `SemanticFrame` | Stabiler kompatibler Vertrag mit Target, Area, Quantifier, Parametern und additiven typisierten Primitiven | Flache Einzelprädikatprojektion; Ausschlüsse, Zeit und Vergleiche liegen teils in untypisierten Parametern; keine verschachtelte Bedeutung |
| `MeaningCandidate` | Score, Vollständigkeit, Slots, Konflikte und Evidenz existieren | Kandidaten sind überwiegend Oberflächenvarianten derselben Slotmenge; Compilation stoppt nach erstem Parse; Score ist im Kern `50 + 5 * Spananzahl - Penalties`; keine vollständigen konkurrierenden Graphhypothesen |
| Evidence | Quellspannen, Art, Score und Detail sind typisiert | `UnderstandingOutcome.evidence` wird im direkten Pfad nicht befüllt; keine Claims, Polarität oder negative Evidenz; Registry-Evidenz ist pauschal 1.0; Auswahlbegründung wird nicht aus dem Evidenzmodell erzeugt |
| Composition | Sichere gemeinsame Aktion auf mehrere explizit benannte Ziele; atomare Mehrfachbefehle | Zielprojektion löscht Namen per Regex und kompiliert erneut; `und` wird global gesplittet; keine gemeinsamen/unterschiedlichen Modifier, Filter, Alternativen oder verschachtelten Gruppen |
| Entity Resolution | Ein kanonischer Scorer, stabile IDs, Exact/Alias/Fuzzy-Provenienz, Ambiguitätsmargin und Index | Referenzauswahl und semantische Hypothesenbewertung nutzen dessen Evidenz nicht gemeinsam; mehrere Helfer scannen Namen zusätzlich für Mention Detection |
| Constraint Resolver | Wiederverwendete Domain-/Entity-/Area-/Floor-/Device-Class-/Property-Capability-Filterung | State, relationale Constraints, Vergleiche zwischen Entitäten, Exclusion und Quantifier werden anderswo behandelt |
| Reasoning Engine | HA-freie Konsistenzprüfung über Frame, Kontext, World Model und Constraints | Keine Hypothesenauflösung; wird erst nach Parser/Validator verwendet; kann weder Graph noch logische/temporale Beziehungen auswerten |
| DialogFocus/Context | TTL, letzter Command/Entities/Area/Floor/Property/State, typisierte pending Dialoge, ein kohärentes `DialogTurnMemory` | Im Wesentlichen letzter Turn; keine Liste von Diskursreferenten, Erwähnungsrollen, Gender/Number, Salience, Referenzkandidaten oder mehrturnige Historie |
| Referenzen | Einige pronomen-, orts- und `andere`-bezogene Follow-ups funktionieren sicher | Eigene reihenfolgenabhängige Matcher; keine generische Koreferenz; unauflösbare Referenzen kollabieren häufig zu `None` statt typisierter Reference-Clarification |
| Korrekturen | Explizites Retargeting des letzten Commands und Query-Ortskorrekturen | Einleitungsregexe; keine `ORIGINAL -> REPAIR_MARKER -> REPLACEMENT`-Struktur und keine lokale Wert-/Action-/Exclusion-Reparatur im selben Turn |
| World Model | Pro Turn frisch, HA bleibt Source of Truth, Indizes für Domain/Class/Area/Floor/Capability, Entity-Device-Zuordnung | Noch keine allgemeine relationale Constraint-Abfrage |
| House Graph | Getypter Registrygraph mit Provenienz und Confidence; Entity/Device/Area/Floor-Beziehungen | Wird im Conversation-Pfad zwar gebaut, anschließend aber nicht konsumiert; Sensor-Property, Controls, Same-Device und Presence-Zuordnungen fehlen; er ist ausdrücklich kein Turn-SemanticGraph |
| Query-System | Typisierte QueryCommand/Target/Filter/Scope/Result-Pipeline, read-only | Filter enthält nur konstanten Zustand; keine Objekt-zu-Objekt-Vergleiche oder relationale Räume; Teile der Query-Erkennung verbleiben in Spezialroutern |
| Automation-System | Reife Trigger-/Condition-/Action-ASTs, verschachteltes AND/OR/NOT, Validator, Preview, Bestätigung, Generator und transaktionaler Executor | Gemeinsamer Structural/Semantic-Graph-Input fehlt; Trigger-/Condition-/Actiongrenzen werden separat und regex-/Hassil-lastig erkannt |
| Ontologie/Aliase | Bestätigte lokale Entity-Aliase; getrennte Routinen/Prozeduren existieren als Produktkonzepte | Kein typisiertes Schema für Entity Alias vs. Semantic Alias vs. Routine Alias; kein kontrollierter unbekannter Konzeptdialog |
| Explainability | Erklärt finalen Command mit Aktion, Zielen, Ort, Wert und Ausschlüssen | Rekonstruiert nur aus `SemanticCommand`; erklärt keine Kandidaten, Scopeentscheidung, negative Evidenz, Margin oder Ablehnung |
| Shadow | Read-only Legacy-vs-V7-Vergleich mit Payloadsignatur und Leakage-Zählern | Vergleicht noch keinen Parsed-Structure-/Graph-/Candidate-Verlauf; Dialog-Follow-ups werden als isolierte Turns gemessen |
| Tests/Eval | Breite Regressionstests, 1.024 Lichtparaphrasen, Domainmatrix, 45 Dialogfälle, Metamorphik und Performancegate | Viele Fälle werden aus denselben Wortlisten/Hüllen erzeugt; kein unabhängiges versioniertes OOD-Korpus, keine semantischen Graphsnapshots, keine geforderten komplexen Scope-/Koreferenzfälle |

## 4. Doppelte und verteilte semantische Logik

Folgende Überlappungen sind Migrationsziele, nicht Anlass für eine neue
Parallelimplementierung:

1. Speech-Act-, Negations-, Question- und Automation-Cues liegen in
   `semantic_utterance.py`, `semantic_compiler.py`, `engine.py`,
   `conversation.py` und Fachroutern.
2. Zeit-, Datums- und Zahlenlexika existieren in `normalize.py`,
   `semantic_compiler.py`, `calendar_event.py`,
   `scheduled_time_command_parser.py`, Automationparsern und Produktivität.
3. Action-/Domain-Vokabular ist zwar in `domain_operations.py` und
   `semantic_catalog.py` zentralisiert, wird in `semantic_dialog.py`,
   Automationsparsern, Management- und Komfortpfaden teilweise erneut erkannt.
4. Entity-Scoring ist autoritativ in `entities.py`/
   `nlu/entity_resolution.py`; zusätzliche Mention-, Alias- und Wildcardscans
   existieren weiterhin. V8 darf diese nicht durch einen neuen Resolver
   ersetzen, sondern muss dessen Kandidaten und Evidenz konsumieren.
5. Bereichs-/Etagenauflösung besitzt zentrale Resolver, wird jedoch in
   mehreren Fachpfaden erneut über Text-Cues angebunden.
6. Quantifier und `SemanticQuantity` koexistieren als dokumentierte
   Übergangstypen. Exclusion liegt zusätzlich als Parameterstring/ID-Liste im
   Direct- und Automationmodell.
7. `SemanticFrame.parameters` trägt mehrere inzwischen typisierbare Konzepte
   (`comparison`, `temporal`, `locations`, `excluded`, QueryCommand/Result).
8. Automationslogik besitzt bereits einen `ConditionNode`-AST. Ein allgemeiner
   SemanticGraph muss darauf projizieren, nicht einen zweiten Automation-
   Condition-Executor oder -Validator schaffen.
9. Manche fachlichen Dialogpfade erstellen `ServiceCallPlan` direkt. Sie
   passieren zwar Policy und zentralen Executor, umgehen aber den allgemeinen
   `SemanticCommand -> Validator -> ServiceMapper`-Pfad. Das ist bestehende
   technische Schuld; V8 darf sie nicht als Vorbild übernehmen.

## 5. Konkrete strukturelle Lücken

Die geforderten Beispielsätze wurden gegen den unveränderten Stand mit einem
repräsentativen Snapshot geprüft:

- „Mach im Wohnzimmer die Lampen aus, die noch an sind, außer der
  Stehlampe.“: kein Match; `an` im Relativsatz kollidiert als TURN_ON mit
  TURN_OFF. FILTER und EXCLUDE haben keinen gemeinsamen Scope.
- „Wenn draußen kälter ist als drinnen und jemand zuhause ist, mach die
  Heizung aus.“: kein AutomationMatch; Vergleich hat keine zwei Operanden und
  die Konjunktion keine strukturellen Kinder.
- Eingeschobener `falls`-/`nachdem`-Satz: kein Match; der erste Cue-Split kann
  die Verschachtelung nicht darstellen.
- „Mach in Küche und Flur alle Lichter aus.“: korrekt als gemeinsamer
  Ortsbereich ausführbar.
- „Mach nur die Lichter aus, die noch an sind.“: kein Match; wieder TURN_ON-
  Konflikt statt State-Filter.
- Unterschiedliche Aktionen auf Küchen- und Wohnzimmerlicht: funktioniert als
  atomarer `CommandPlan`, aber nur über globales `und`-Splitting.
- „... alle Rollläden runter, aber den im Wohnzimmer nur auf 50 Prozent.“:
  kein Match; kein Contrast/Override-Modell.
- Negierte Commands werden konservativ vollständig blockiert. Das ist sicher,
  bildet aber lokale Negationsscopes und positive Restaktionen noch nicht ab.
- Implizite Beschwerden bleiben nicht ausführbar, werden teils fälschlich als
  Query klassifiziert; eine ASK/SUGGEST-Pragmatik fehlt.
- Same-turn-Wertkorrekturen und widerrufene Ausschlüsse werden nicht als
  Reparaturstruktur verstanden.

## 6. Unveränderliche Sicherheits- und Verantwortungsgrenzen

Die folgenden Grenzen dürfen durch V8 weder ersetzt noch umgangen werden:

- `EntitySnapshot`/Registry und die bestehenden Area-/Floor-/Entity-Resolver
  bleiben die einzige Identitäts- und Auflösungsquelle.
- `WorldModel` bleibt der einzige pro Turn gebaute, HA-abgeleitete Snapshot;
  `HouseGraph` bleibt seine relationale Projektion, nicht eine zweite Wahrheit.
- Capability Validation bleibt eine harte spätere Grenze. Frühere
  Capability-Evidenz darf Kandidaten nur gewichten oder ausschließen, nie eine
  falsche sprachliche Identität überstimmen.
- `UnderstandingOutcome` bleibt die kanonische Routergrenze. Neue Resultate
  werden additiv darin transportiert.
- Queries, Aussagen, Hypothesen, Vorschläge, Ambiguität und nicht aufgelöste
  Referenzen dürfen keinen `ServiceCallPlan` tragen.
- `SemanticGraph`, Structural Analysis, Candidate Ranking, Discourse und
  Reasoning importieren weder HA-Service APIs noch Executor/ServiceMapper.
- Direkte Aktionen durchlaufen weiterhin Command Validator, Service Mapper,
  Execution Policy, gegebenenfalls Bestätigung und den zentralen
  `async_execute_service_plan` mit frischem Snapshot.
- AutomationModel, AutomationValidator, Preview/Bestätigung,
  HA-Automationsgenerator und AutomationExecutor bleiben autoritativ.
- Target-Limits, Benutzerbindung, Admin-/Read-only-Regeln, Risk-Klasse,
  Availability- und Capability-Revalidierung bleiben unverändert wirksam.
- Kein Scoringwert allein macht einen Turn ausführbar. Vollständigkeit,
  Eindeutigkeit, Mindestmargin und sämtliche nachgelagerten Gates sind
  erforderlich.

## 7. V8-Zielarchitektur

`SemanticFrame` soll langfristig Variante **B**, eine kompatible Projektion
des `SemanticGraph`, sein. Ein Ersatz würde alle reifen Validator-/Mapper-
und Querypfade unnötig brechen; ein Frame als unabhängige zweite Wahrheit
würde dagegen Drift erzeugen.

```text
Originaltext + Registry + Dialogkontext
  -> LanguageDocument
  -> GermanStructuralAnalysis
       Tokens/Morphologie, Phrasen, Klauselbaum, Prädikate/Argumente,
       Koordination, Negation, Referenzen, Reparaturen
  -> 1..n SemanticGraph-Hypothesen
  -> MeaningCandidate(graph + structured evidence)
  -> DiscourseResolver + bestehende Entity/Area/Floor Resolver
  -> WorldModel/HouseGraph + Constraint Resolver
  -> deterministisches Ranking + Ambiguity Gate
  -> UnderstandingOutcome
       -> SemanticFrame-Projektion -> bestehender Command/Query-Pfad
       -> AutomationModel-Projektion -> bestehender Automation-Pfad
       -> Clarification/Unsupported/Unsafe/Statement/Suggestion
  -> bestehende Capability-/Policy-/Confirmation-/Execution-Grenzen
```

Der Turn-`SemanticGraph` und der Haus-`HouseGraph` haben verschiedene
Verantwortung:

- SemanticGraph: „Was bedeutet diese Äußerung und wie sind ihre Teile
  verbunden?“
- HouseGraph: „Welche nachweisbaren Beziehungen bestehen zwischen stabilen
  Objekten im aktuellen Haus?“

Grounding verbindet beide über stabile IDs; sie dürfen nicht zu einem
gemeinsamen mutierbaren Graphen verschmolzen werden.

## 8. Vorgesehene Datenmodelle

Neue Modelle bleiben frozen, HA-frei, serialisierbar und deterministisch:

- `SourceSpan(start, end, text)` als einheitliche Quellenreferenz.
- `StructuralToken` mit Lemmakandidaten, grober Wortklasse, Morphologie und
  sicherer Füllwortklassifikation.
- `Phrase` und `Clause` mit IDs, Typ, Parent, Connector, Prädikat,
  Argumentrollen und eingebetteten Kindern.
- `StructuralRelation` für Subjekt, Objekt, indirektes Objekt, Modifier,
  Negation, Koordination, Vergleich, Relativsatz, Temporalbezug und Reparatur.
- `SemanticNode(id, kind, value, span)` und
  `SemanticEdge(source, relation, target, scope)`.
- `SemanticGraph(root_ids, nodes, edges, speech_act, modality)` mit stabiler
  kanonischer Snapshotdarstellung und Invariantenprüfung.
- `SemanticEvidence(type, claim, span, weight, polarity, explanation,
  source_id)`; `confidence` bleibt ein deterministisch berechneter Wert.
- erweitertes `MeaningCandidate` mit Graph, Projection, Resolutionstatus,
  vollständigen positiven/negativen Evidenzen und maschinenlesbarer
  Ablehnungsursache.
- `DiscourseReferent` mit stabilen Entity-IDs, Typ, Gender, Number, Area/Floor,
  Turnindex, Erwähnungsrolle, Property/State/Action und Salience-Faktoren.
- `DiscourseState` als begrenzte, TTL-gebundene Liste statt „letzte Entity
  gewinnt“; `ConversationContext` erhält sie additiv.
- getrennte `EntityAlias`, `SemanticAlias` und `RoutineAlias`-Schemas. Nur
  explizit bestätigte semantische Aliase dürfen persistiert werden.

Die Knotentypen werden klein und fachlich gehalten: Predicate/Action,
Entity/EntityClass, Area/Floor, Property/State/Value, Comparison, Quantifier,
Temporal, Condition/Logical, Reference, Exclusion und Relation. Domainmodelle
wie `ConditionNode`, `ActionModel`, `QueryCommand` und `SemanticFrame` bleiben
Projektionen, nicht duplizierte Knotenklassen mit eigener Ausführung.

## 9. Leichter deutscher Strukturparser

Es wird keine schwere NLP-Abhängigkeit eingeführt. Die vorhandene
Runtime-Dependency-Liste ist leer; ein eigener beschränkter Parser passt zur
HA-/ARM-/Offline-Grenze und vermeidet Modellgröße, Ladezeit und nicht
kontrollierbare Versionsvarianz.

Der Parser wird lexikon- und featurebasiert, nicht satztemplatebasiert:

1. Die bestehende Tokenisierung wird um Satzzeichen-, Wortklassen- und
   Morphologiefeatures ergänzt. Originalspannen bleiben unverändert.
2. Ein kleines deklaratives Funktionswortlexikon beschreibt Artikel,
   Pronomen, Präpositionen, Konjunktionen, Subjunktionen, Modal-/Hilfsverben,
   Negation, Reparatur- und Diskursmarker.
3. Das bestehende Action-/Property-/Domain-Lexikon liefert Prädikat- und
   Nomenkandidaten. Trennbare Verbpartikeln werden über Abstand und
   Klauselgrenzen verbunden, nicht durch Satzregexe.
4. Ein deterministischer, bounded Chart-/Transition-Parser baut mögliche
   Phrasen und Klauseln. Regeln arbeiten auf Features und Rollen, nicht auf
   kompletten Satzstrings.
5. Mehrdeutige Attachments erzeugen getrennte Strukturanalysen. Maximalzahl,
   Baumtiefe und Beamgröße sind feste Konfigurationskonstanten; Sortierung und
   Tie-Breaks sind stabil, Gleichstand bleibt Ambiguität.
6. Safe discourse filler darf nur entfernt werden, wenn kein möglicher
   Bedeutungsclaim daran hängt. Residualtokens bleiben im Graph bzw. führen zu
   UNSUPPORTED/Clarification.

## 10. Migrationswaves

### Wave 0 – Audit- und Contract-Gates

Betroffene Dateien: dieses Dokument, neue unabhängige OOD-Fixtures, Snapshot-
Hilfen und Erweiterung der Performance-/Shadow-Skripte. Zunächst werden die
bekannten Lücken als nicht ausführbare bzw. erwartete zukünftige Semantik
fixiert. Der bestehende Release-Metadatenfehler wird getrennt behandelt.

Exit-Kriterium: alte Suite unverändert, OOD-Korpus versioniert, keine neue
Produktionsautorität.

### Wave 1 – Structural Analysis

Neue Datei: `nlu/german_structure.py`. Erweiterung:
`language_frontend.py`, `semantic_utterance.py`, `german_morphology.py`.
`LanguageDocument` erhält additiv eine Strukturanalyse. Zunächst werden
Tokenfeatures, Prädikat/Argument-Grundrollen, trennbare Verben, Clause Tree,
Koordination und Quellenbezug implementiert. Bestehende Speech-Act-Entscheidung
bleibt autoritativ und wird im Shadow verglichen.

Risiko: falsche Clause-Bindung. Schutz: kein Ausführungsanschluss, bounded
Parser, Snapshot- und Metamorphiktests.

### Wave 2 – SemanticGraph und Evidence

Neue Dateien: `nlu/semantic_graph.py`, `nlu/semantic_evidence.py`,
`nlu/semantic_graph_builder.py`. Erweiterung: `understanding.py`,
`semantic_interpreter.py`, `debug.py`.

Der Graph wird zuerst rein beobachtend aufgebaut. Evidence erhält Claims und
positive/negative Gewichtung. `MeaningCandidate` trägt vollständige
Graphhypothesen; mehrere Attachments/Lesarten bleiben getrennt. Keine
Compilation stoppt nach dem ersten Parse.

Risiko: Kandidatenexplosion. Schutz: feste Maximalwerte pro Ambiguitätstyp,
frühes strukturelles Pruning, keine Registry-Kopie pro Kandidat.

### Wave 3 – Frame-/Query-/Automation-Projektionen im Shadow

Neue Datei: `nlu/semantic_projection.py`. Erweiterung:
`frame.py`, `semantic_compiler.py`, `semantic_automation.py`,
`query_command.py`, `engine.py` und Shadow-Skript.

Einfache Direct Commands und Queries werden aus dem Graph auf bestehende
Modelle projiziert. Die alte Compilation bleibt Autorität; Shadow vergleicht
Parsed Structure, Graph, Candidate, Frame, Entityauflösung, Outcome und Plan.
Pro Capability erfolgt Umschaltung erst nach Gleichheit plus neuen OOD-
Erfolgen. Komplexe, korrekt geparste aber noch nicht projizierbare Zeit- oder
Relationsgraphen liefern `UNSUPPORTED`, niemals einen verkürzten Plan.

### Wave 4 – Scope, Relativsätze, Exclusion und koordinierte Aktionen

Erweiterung: Graph Builder/Projection, `composition.py`,
`constraint_resolver.py`, Queryfilter und Automationprojektion.

Implementiert werden AND/OR/NOT/IF/THEN/EXCEPT/BEFORE/AFTER/UNTIL/WHILE mit
explizitem Scope, State-Filter, Relativsatzbindung, gemeinsame und getrennte
Modifier sowie Action-Gruppen. `composition.py` wird zum Graphprojektor; das
heutige Entfernen von Entitynamen und Rekompilieren wird nach bewiesener
Parität entfernt.

### Wave 5 – Diskursreferenten und Salience

Neue Datei: `nlu/discourse.py`. Erweiterung: `context.py`, `dialog_focus.py`,
`engine.py`, Conversation-Kontextupdates und Clarification.

Der deterministische Score setzt sich aus Recency, grammatischer
Übereinstimmung, Erwähnungsrolle, aktuellem Focus/Queryset, Ort, Domain,
Property und Numerus zusammen. Fehlende Merkmale geben keine positiven
Punkte. Gleichstand oder kleine Margin erzeugen eine typisierte Referenz-
Clarification. Bestehende Follow-up-Matcher werden erst entfernt, wenn ihre
Fälle über den gemeinsamen Resolver laufen.

### Wave 6 – Relationales Grounding und Queries

Erweiterung: `house_graph.py`, `world_model.py`, `constraint_resolver.py`,
`query_command.py`, `query_executor.py`.

Nur aus HA sicher ableitbare Relationen werden ergänzt: Entity→Area,
Area→Floor, Entity→Device, Sensor→Device, Sensor→measured property,
Entity→capability und Same-Device. Relationsevidenz trägt Provenienz.
Objekt-zu-Objekt-Vergleiche benötigen eindeutige Property-/Unit-Kompatibilität.
Nicht belegbare Beziehungen bleiben unsupported.

### Wave 7 – Zeit, Reparatur, Pragmatik und Ontologie

Neue oder erweiterte Module: `nlu/temporal_semantics.py`,
`nlu/repair.py`, `nlu/pragmatics.py`, `nlu/concepts.py`, Alias-Konfiguration
und bestätigte Dialoge.

Zeitgraphen können vollständig geparst werden, auch wenn keine Execution-
Projektion existiert. Reparatur ersetzt nur den explizit markierten Scope.
Pragmatik liefert eine Policy-Klasse: Imperativ/explizite Bitte/Wunsch,
implizite Beschwerde als ASK/SUGGEST, neutrale Aussage. Semantic Aliases sind
getrennt von Entity- und Routine-Alias und werden nur nach Bestätigung aktiv.

### Wave 8 – Autoritätsmigration und Bereinigung

Capabilityweise Migration in `engine.py`/`conversation.py`. Erst nach grüner
Regression, OOD, Metamorphik, Snapshot, Shadow und Performance werden
redundante Speech-Act-, Split-, Exclusion-, Follow-up- oder Compilerregexe
entfernt. Fachparser für Kalender/Produktivität bleiben bestehen, bis auch
deren Domainprojektionen nachweislich gleichwertig sind.

## 11. Test- und Evaluationsplan

Neue Testgruppen:

- Structural Unit Tests für Tokens, Phrasen, Clause Tree, Partikel,
  Negations-/Quantifier-/Relative-Clause-Scope und Reparatursegmente.
- SemanticGraph-Snapshots mit stabiler kanonischer Sortierung:
  Input → Structure → Graph → Candidates → Auswahl → Resolution → Outcome.
- Unabhängiges OOD-JSON-Korpus, manuell formuliert und nicht aus Produktlexika
  generiert: Umgangssprache, Ellipsen, Einschübe, verdrehte Wortstellung,
  Pronomen, mehrere Referenten, Selbstkorrektur und unbekannte Konzepte.
- Metamorphe Transformationen für Wortstellung, Höflichkeit, Füller, sichere
  Synonyme, Ortsverschiebung und Pronomen-Follow-ups.
- Safety-Matrix für Fragen, Hypothesen, Aussagen, implizite Beschwerden,
  Negation, unvollständige Graphen, Candidate-Ties und unsupported temporal
  semantics. Erwartung: niemals Action-Leakage.
- Dialogsequenzen mit mindestens fünf Turns und mehreren aktiven Referenten.
- HouseGraph-/relationale Querytests mit positiver Provenienz und bewusst
  fehlenden Beziehungen.
- Shadowvergleich auf jeder Projektionsstufe und für vollständige Dialoge,
  nicht nur isolierte Einzelturns.

## 12. Performanceplan

Gemessen werden 100, 1.000 und 5.000 Entities für einfachen Command, Query,
komplexen Satz, Follow-up, Ambiguität und Multi-Target. Zusätzlich werden
Parser-only, Graphbau, Grounding und Projektion getrennt ausgewiesen.

Budgets und Maßnahmen:

- Token-/Strukturarbeit ist primär O(T) mit fester Kandidaten-/Tiefengrenze.
- Entity-/Ortserwähnungen nutzen `EntityIndex`; kein Vollscan pro Graphknoten.
- WorldModel und HouseGraph werden einmal pro Turn gebaut und geteilt.
- Lexikon-/Morphologieautomaten sind prozessweit cachebar; Haushaltsdaten
  werden nicht global gecacht.
- Kandidaten teilen unveränderliche Structure/Graph-Fragmente.
- Kein unbeschränktes O(T²); bounded Clause-Chart nur innerhalb kurzer
  Klauseln. Keine O(E²)-Relationssuche.
- Bestehendes 100-ms-p95-CI-Gate bei 5.000 Entities bleibt erhalten und wird
  um die neuen Kategorien ergänzt. Zielhardwaremessungen bleiben separat
  dokumentiert.

## 13. Kritische Planprüfung

Der Plan erzeugt bewusst keine zweite Entity-Suche, Capability-Engine,
WorldModel-, HouseGraph-, Validator-, Policy-, ServiceMapper-, Executor- oder
Dialog-State-Machine. Neue Komponenten enden an bestehenden typisierten
Grenzen:

- Structural Analysis besitzt keine HA-Objekte.
- SemanticGraph besitzt keine Ausführungsbegriffe wie Service/Call.
- Grounding ruft bestehende Resolver/Indizes auf.
- HouseGraph liefert nur belegte Hausrelationen.
- Projektionen erzeugen bestehende `SemanticFrame`, `QueryCommand` oder
  `AutomationModel`-Objekte.
- `UnderstandingOutcome` entscheidet weiterhin zwischen Command, Query,
  Clarification, Ambiguous, Unsupported und Unsafe.
- Nur bestehende Mapper/Generatoren materialisieren ausführbare Artefakte.
- Nur bestehende Policy-/Bestätigungs-/Executorpfade dürfen schreiben.

Die wichtigste Migrationsentscheidung ist daher: **SemanticGraph wird die
kanonische sprachliche Bedeutung; SemanticFrame bleibt seine
rückwärtskompatible Einzelprädikatprojektion.** Der HouseGraph ist die
kanonische Hausbeziehungsquelle. Beide treffen sich ausschließlich in der
auflösenden Reasoning-/Constraint-Schicht.

## 14. Bewusste Grenzen

V8 liefert kein allgemeines Weltwissen und kein neuronales Sprachmodell.
Unbekannte bedeutungstragende Wörter, unbelegte Hausrelationen, unauflösbare
Pronomen, ähnliche vollständige Lesarten und nicht unterstützte Zeit- oder
Automationsprojektionen führen zu Rückfrage oder `UNSUPPORTED`. Lokales Lernen
ist nur explizit, typisiert, bestätigungspflichtig und widerrufbar. Diese
Begrenzung ist Teil des Sicherheits- und Produktversprechens, kein temporärer
Fallback auf Raten.

## 15. Umsetzungsstand nach dem Audit

Nach Abschluss dieses Audits wurden die Waves 0–8 inkrementell umgesetzt.
Produktiv sind Struktur- und Graphaufbau, vollständige Kandidaten/Evidence,
die zentrale Projektion relativer State-Filter, Diskurs-Salience mit
Clarification, beobachtete HouseGraph-Relationen und relationale
Query-Operanden. Zeit, Reparatur, Pragmatik und bestätigte Alias-Typen sind
strukturell modelliert; nicht vorhandene Domainprojektionen bleiben bewusst
`UNSUPPORTED`.

Redundante Fachparser wurden nicht pauschal gelöscht. Sie bleiben dort
erhalten, wo Snapshot-, OOD-, Dialog- und Shadow-Parität für die jeweilige
Funktion noch nicht belegt ist. Details, Messwerte und ausdrücklich offene
Grenzen dokumentiert [`architecture-v8.md`](architecture-v8.md). Der Audit
bleibt die Entscheidungsgrundlage; dieser Nachtrag ändert seine
Ausgangsbefunde nicht.
