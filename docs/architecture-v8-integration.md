# HomeIntent V8 – produktiver Abschlussstand

Stand: 9. September 2026
Ausgangsbasis: `main` bei `46c5bc8a7d3ae20d40f1b9c5a4c2aabc66f6bc83`

## Geltungsbereich

V8 bezeichnet die gemeinsame deterministische Understanding-Architektur für
unterstützte Home-Assistant- und Haushaltssemantik. Es ist kein allgemeines
Sprachmodell. Eine erkannte, aber nicht verlustfrei projizierbare Bedeutung
endet ausdrücklich `UNSUPPORTED` oder `CLARIFICATION`; sie wird nie durch
Weglassen von Negation, Relation, Zeit, Repair oder unbekannten Wörtern zu
einer Aktion vereinfacht.

```text
Originaltext
  -> LanguageDocument
  -> GermanStructuralAnalysis
  -> SemanticGraph
  -> MeaningCandidates + Evidence
  -> DiscourseState + WorldModel/HouseGraph
  -> zentrale Resolver / Constraint Resolution
  -> Domainprojektion
  -> UnderstandingOutcome
  -> Validator -> ExecutionPolicy -> ServicePlan/Query/AutomationModel
```

Parser, Graph, Candidates, Discourse und Reasoning führen keine HA-Services
aus. Queries besitzen keinen Service-Mapping-Eintrag. `UNSUPPORTED`,
`AMBIGUOUS`, `CLARIFICATION` und `UNSAFE` können keinen ausführbaren Plan
tragen. Query-Ergebnisse liefern Referenzkontext, niemals Aktionsberechtigung;
vor Aktionen werden gespeicherte IDs erneut gegen den Live-Snapshot geprüft.

## Produktive Autoritäten

| Subsystem | Produktive Autorität | V8-Endzustand | Bewusste Grenze |
|---|---|---|---|
| Language Frontend | `LanguageDocument` | gemeinsamer Eingang mit Original, Tokens, Varianten, Speech Act, Struktur und Temporal | keine freie statistische Korrektur |
| Clause/Scope | `GermanStructuralAnalysis` | IF, AND, OR, EXCEPT, Negation, Relative, Temporal und Repair werden strukturell gebunden | unklare Bindung wird nicht per first-match entschieden |
| Bedeutung | `SemanticGraph` | produktive IR für strukturierte Commands, Filter, Exclusions, unabhängige Prädikate, Repair und relationale Queries | nicht jede theoretische Graphform besitzt eine Domainprojektion |
| Kandidaten | `MeaningCandidate` + `evidence.py` | Graph-/Slot-Hypothesen, Konflikte, Missing Slots, Provenienz; Ranking nutzt ungekappte Raw Scores | Display-Score allein autorisiert nichts |
| Commands | Graphprojektion -> `SemanticFrame` -> `SemanticCommand` | Shared Predicate, unabhängige Prädikate, relative State-Filter und Exclusions ohne rekonstruierten Satz | reichere nicht repräsentierbare Modifier bleiben unsupported |
| Queries | `QueryCommand` -> `QueryExecutor` | strikt read-only; vorhandene Status-/Property-Queries bleiben erhalten | kein Query-to-Action-Fallback |
| Relationale Queries | Graph + `HouseGraph` -> vorhandener `QueryExecutor` | Entity-/Raum-Vergleich und belegte SAME_AREA-Beziehung produktiv | Superlative, Aggregate und mehrdeutige Sensorwahl unsupported |
| Composition | Structural AND + Graphprojektion | gemeinsame Targets und vollständige Prädikate werden unterschieden und direkt projiziert | alter Reparse nur Kompatibilität für noch nicht migrierte Shapes |
| Discourse | `DiscourseState` / `DialogFocus` | mehrere Referenten, Gruppen, Query-Ergebnisse, Fokus und Graphfragment werden konsumiert | geringer Salience-Abstand führt zur Klärung |
| WorldModel / HouseGraph | frischer HA-Snapshot + indexierte Sicht | belegte Entity/Area/Floor/Device/Property/Capability-Beziehungen werden produktiv gelesen und pro Turn gecacht | keine erfundenen Beziehungen |
| Temporal | typisierte TemporalExpression + Graph | Delay, Dauer, Zeitpunkt und Relationen bleiben erhalten | generischer Direktpfad ist parsed-but-not-executable; sichere Scheduling-Pfade müssen zuerst projizieren |
| Repair | REPLACES-Struktur + Graphprojektion | eindeutiger Entity-Repair ersetzt das Original vollständig | Value-/Property-/Temporal-Repair ohne verlustfreie Projektion unsupported |
| Automationen | gemeinsame IF-/Clause-Struktur -> Fachprojektoren -> `AutomationModel` | äußere Trigger/Condition/Action-Grenzen stammen aus V8; Fachparser klassifizieren abgegrenzte Clauses | Textsplitter nur Kompatibilitätsfallback für unklassifizierte Formen |
| Automation Follow-ups | `AutomationModel` + Edit-Operationen | Conditions, Targetersatz, Werte und Ergänzungen bearbeiten das Modell | unklare Änderung verlangt Klärung; kein Schreiben vor Preview/Bestätigung |
| Aliase / Concepts | Entity-, bestätigter Semantic- und Procedure-/Routine-Store | Typen bleiben strikt getrennt; kein stilles Lernen | undefinierte Konzepte werden nicht in Gerätewerte übersetzt |
| Management / Calendar / Productivity | gemeinsame Understanding-Grenze -> Domainmodelle | gemeinsame Speech-Act-, Repair-, Referenz-, Temporal-, Ambiguitäts- und Confirmation-Schicht | Fachmodelle bleiben eigene Domainprojektionen |
| Execution | ServiceMapper / QueryExecutor / AutomationExecutor | genau ein Ausführungspfad je Domäne | keine Ausführung in NLU/Graph/Reasoning |
| Safety | Validator + ExecutionPolicy + Confirmation | autoritativ und unmittelbar vor Ausführung erneut geprüft | Candidate-Score kann diese Grenze nie überstimmen |

## Relationen und sichere Ableitung

Produktiv sind Vergleiche zweier explizit und eindeutig geerdeter
Messentities, Vergleiche zweier Räume mit genau einem passenden
Temperatursensor je Raum sowie `im selben Raum wie` über belegte
`Entity -> Area`-Kanten. Einheitengleichheit und Live-Werte sind hart
erforderlich. Mehrere passende Sensoren, fehlende Werte, inkompatible
Einheiten oder eine nicht belegte Device-/Area-Beziehung ergeben keinen
vermeintlichen Wahrheitswert.

Sichere `UNSUPPORTED`-Grenzen sind derzeit:

- Superlative und Hausaggregate (`am wärmsten`, `mehr als zwei Räume`),
- abgeleitete Raum-HAT-Zustandsrelationen mit unklarer Sensor-/Fensterwahl,
- Gerätebesitz ohne Device-Registry-Kante,
- räumliche Nähe, Links/Rechts oder Nachbarschaft ohne bestätigte Relation,
- beliebiger Temporal-/Value-Repair und beliebige verschachtelte Automation,
  wenn das Domainmodell den Scope nicht verlustfrei ausdrücken kann.

Diese Formen dürfen als Struktur/Graph beobachtbar sein, werden aber nicht
als vollständig unterstützt bezeichnet und erzeugen keinen ServicePlan.

## Pragmatik, unbekannte Bedeutung und Aliase

Explizite Imperative und eindeutige höfliche Requests können nach Validation
ausführbar sein. Beschwerden (`Das Licht ist mir zu hell`), Statements,
Hypothesen, Capability-, Erklärungs- und Simulationsfragen bleiben read-only
oder fragen nach. Die geschlossene Füllwortmenge wird getrennt von unbekannten
bedeutungstragenden Tokens behandelt. Ein undefiniertes Wort wie `flauschig`
wird nicht ignoriert, um eine Teilaktion freizugeben. Semantische Konzepte
und Routinen entstehen ausschließlich nach expliziter Bestätigung.

## Legacy

Der produktive Regex-AND-Pfad für migrierte unabhängige Prädikate ist durch
direkte Clause-/Graphprojektion ersetzt. `project_target()` und alte
Hassil-Grammatiken bleiben nur für den read-only Shadowvergleich oder noch
nicht projizierbare Kompatibilitätsformen. Automation-Kommasplit und früherer
Top-Level-AND-Split sind nur Fallback, wenn GermanStructuralAnalysis keine
eindeutige Grenze liefert. Es gibt keinen zweiten EntityResolver, WorldModel,
QueryExecutor, ServiceMapper, Validator, Policy- oder Executor-Pfad.

## Evaluation und Release-Gates

`scripts/run_language_eval.sh` prüft die Pipeline einschließlich
handgeschriebenem OOD-Korpus, positiver/negativer Metamorphik, Semantic
Snapshots, relationaler Projektion, Pragmatik und Mehrturn-Referenzen. Der
Korpus wird nicht aus Produktlexika erzeugt. Der versionierte Shadowreport ist
read-only und prüft Query-/Ambiguous-/Unsafe-Leakage.

Der Release-Gate-Satz umfasst vollständiges Pytest mit Coverage, Language
Eval, Shadow, Registry-Benchmarks bei 100/1.000/5.000 Entities, Pyflakes,
Full Pyright, Strict Pyright, Hassfest, HACS und einen echten Home-Assistant-
Stable-Smoke-Test. Konkrete Messwerte stehen im README und GitHub-Release;
historische Auditwerte sind keine Aussage über diesen Endstand.

HomeIntent beschreibt diesen Stand als: **Deterministic LLM-like
natural-language understanding for supported Home-Assistant and household
semantics.** Das Wort „supported“ ist eine Sicherheitsgrenze.
