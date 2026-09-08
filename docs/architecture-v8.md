# HomeIntent V8 – inkrementelle Understanding-Architektur

Stand: 8. September 2026
Status: Direct-Command-Integrationspass umgesetzt; andere Subsysteme sind
unten ausdrücklich als `IMPLEMENTED`, `PARTIALLY MIGRATED`,
`OBSERVABILITY ONLY` oder `UNSUPPORTED` gekennzeichnet.

Die vollständige Ist- und Gap-Analyse steht in
[`architecture-v8-audit.md`](architecture-v8-audit.md). Dieses Dokument
beschreibt den danach implementierten Stand.

## Datenfluss und Autorität

```text
Originaltext
  -> LanguageDocument
       -> GermanStructuralAnalysis + TemporalSemantics
       -> bestehendes SemanticLexicon
  -> SemanticGraph je MeaningCandidate
       -> bestehende Entity-/Area-/Floor-Auflösung
       -> Diskurs + WorldModel/HouseGraph-Evidence
  -> zentrale SemanticProjection
  -> SemanticFrame als kompatible flache Projektion
  -> UnderstandingOutcome
  -> unverändert: Capability/Validator -> Policy/Bestätigung
  -> bestehender ServiceMapper/Query/Automation -> zentraler Executor
```

Parsing, Graph, Kandidaten, Diskurs und Reasoning importieren keinen
Home-Assistant-Serviceexecutor. `nlu/semantic_projection.py` ist die
strukturierte Graph-zu-Compatibility-Brücke für die bereits unterstützten
Direct-Command-Formen. Sie erzeugt keinen deutschen Zwischentext und ruft
weder `analyse_language()` noch `analyse_semantics()` noch einen Textcompiler
auf. Identity- und Location-Grounding delegiert sie an die vorhandenen
Resolver; Servicepläne, Capability- und Policy-Entscheidungen bleiben später.

## German Structural Analysis

Die leichte Analyse arbeitet tokenbasiert, ohne externes NLP-Modell. Sie hält
Source-Spans, Wortklassen, konservative Prädikat-/Argumentphrasen, trennbare
Verbpartikel, Haupt-/Neben-/Relativ-/Reparaturklauseln und lokale
Negationsbereiche fest. Beziehungen werden als `IF`, `THEN`, `AND`, `OR`,
`EXCEPT`, `BEFORE`, `AFTER`, `UNTIL`, `WHILE`, `MODIFIES` und `REPLACES`
modelliert. Koordination bleibt explizit mehrdeutig, wenn ihr Scope nicht
belegt ist; der Strukturparser rät ihn nicht.

Das ist ein domänenbegrenzter Strukturparser, kein allgemeiner deutscher
Dependenzparser. Die vorhandenen V7-Fachparser bleiben für noch nicht
migrierte Projektionen zuständig.

## SemanticGraph und SemanticFrame

`SemanticGraph` repräsentiert die nicht ausführbare Bedeutung eines Turns.
Knoten umfassen Klauseln, Aktionen, Entityklassen, Properties, Zustände,
Werte, Quantifier, Vergleiche, Negation, Referenzen, Bedingungen, Zeit sowie
geerdete Entity-, Area- und Floor-IDs. Kanten bilden unter anderem `TARGET`,
`FILTER`, `EXCLUDE`, `NOT`, logische/temporale Beziehungen, `REPLACES` und
Grounding ab.

Der Graph enthält keine HA-Servicebegriffe. Entity- und Orts-IDs stammen
ausschließlich aus den vorhandenen autoritativen Resolvern. `SemanticFrame`
wurde nicht gebrochen oder dupliziert: Es trägt den Graph additiv und bleibt
die rückwärtskompatible Projektion für Validator, Reasoning, ServiceMapper und
Querypfade. `HouseGraph` beschreibt dagegen belegtes Hauswissen; beide
Konzepte sind absichtlich getrennt.

Der produktive Relationspfad unterstützt eindeutig gebundene relative
Zustandsfilter zusammen mit vorhandenen Ausschlüssen:

```text
Mach im Wohnzimmer die Lampen aus, die noch an sind, außer der Stehlampe.

ACTION(turn_off)
  TARGET(light)
  LOCATED_IN(living_room)
  FILTER(state=on)
  EXCLUDE(light.stehlampe)
```

Domain, Area, Quantifier, Zustandsfilter und Ausschluss werden strukturiert
projiziert; Entity-/Area-/Floor-Identität stammt weiterhin ausschließlich aus
den vorhandenen Resolvern. Erst danach laufen Validator, ReasoningEngine und
ServiceMapper. Ein unbekanntes oder mehrdeutiges Relativprädikat bleibt nicht
ausführbar. Eigenständige koordinierte Prädikate werden nur anhand belegter
Clause-Relationen atomar kompiliert; `OR` und unvollständige Gruppen werden
nicht vereinfacht.

## Hypothesen, Evidence und Ambiguität

`MeaningCandidate` ist eine vollständige Hypothese mit Graph, Slots,
Vollständigkeit, Konflikten, Ablehnungsgrund und strukturierter positiver oder
negativer Evidence. Gewichte und Strafen liegen zentral in `nlu/evidence.py`.
Lexical-, Structural-, Registry-, Entity-, Area-, Floor-, Capability-,
Property-, Unit-, Temporal-, WorldModel-, Correction- und Negative-Evidence
erzeugen eine deterministische Score-Erklärung. Alle begrenzten Textvarianten werden ausgewertet; die
Interpretation endet nicht mehr beim ersten Compiler-Treffer. Ähnlich starke,
verschiedene und vollständige Bedeutungen erzeugen `AMBIGUOUS_MEANING`.
Entity-Margins und `ClarificationRequest` bleiben autoritativ. Ein Graphscore
allein macht nichts ausführbar; Capability-Evidence ersetzt insbesondere
nicht `validate_command()`.

`build_semantic_snapshot()` bildet stabil ab:

```text
Input -> Structure -> SemanticGraph -> MeaningCandidates
      -> selected meaning -> resolved entities -> UnderstandingOutcome
```

Der Shadowreport vergleicht zusätzlich Kandidaten- und Graphsignaturen als
beobachtende Stage-Daten. Diese beeinflussen während der Migration weder
Paritätsklassifikation noch Ausführung.

## Diskursreferenzen und Salience

`DiscourseState` hält begrenzt mehrere stabile Entity-IDs samt Typ, belegtem
Genus, Numerus, Area/Floor, Erwähnungsrolle, Turnnummer, Property, Zustand und
Aktion. Zusätzlich speichert er Focus-Entity-/Area-/Floor-IDs und das
ausgewählte Graphfragment. Queryresultate werden als `QUERY_RESULT`, nicht als
Action-Targets gespeichert. Recency und Rollen werden deterministisch gewichtet. Der Resolver
arbeitet nur gegen aktuelle Live-Snapshots; verschwundene IDs werden nicht
wiederbelebt. Bei kleiner Margin liefert er eine bestehende Entity-
Clarification statt einer Wahl. Alte Follow-up-Matcher bleiben vorerst als
Kompatibilitätsfallback für noch nicht migrierte Dialogformen.

## WorldModel, HouseGraph und relationale Queries

Der vorhandene `WorldModel` bleibt die einzige Quelle des `HouseGraph`.
Zusätzlich zu Entity→Area und Entity→Device werden nur belegbare
Entity→Floor-, Sensor→Property- und Entity→Capability-Kanten aufgebaut. Jede
Relation behält ihre Provenienz.

Das Query-Modell kann zwei vollständig geerdete Property-Operanden mit
`LT/LTE/EQ/GTE/GT` vergleichen. Es liest Live-Werte über den WorldModel,
verweigert `unknown`/`unavailable` und verweigert inkompatible Einheiten.
Die natürliche Sprache für beliebige relationale Hausqueries ist noch nicht
vollständig projiziert; der Executor erfindet deshalb keine Beziehungen.

## Zeit, Reparatur, Pragmatik und Aliase

Zeit wird als `now`, relative Verzögerung, Dauer, absolute Uhrzeit,
Datum/Wochentag, `before`, `after`, `until`, `while`, `since` und
Sonnenereignis repräsentiert. Parsing bedeutet nicht Ausführbarkeit:
nicht unterstützte Zeitgraphen bleiben unsupported.

Reparaturen behalten Original, Marker und Ersatz und verbinden kompatible
Werte mit `REPLACES`. Direkte Befehle und explizite höfliche Bitten sind
ausführbare Requests. Implizite Beschwerden wie „Das Licht ist mir zu hell“
sind `ASK_BEFORE_ACTION`; neutrale Aussagen, Fragen und Hypothesen bleiben
nicht ausführbar.

Entity Alias, Semantic Alias und Routine Alias sind getrennte Typen.
Semantische/Routine-Regeln können nur explizit bestätigt in den lokalen
Konfigurationsspeicher übernommen werden. Eine unbeaufsichtigte Learning
Engine existiert nicht.

## Migrationsstatus

| Subsystem | Status | Autorität |
|---|---|---|
| Language Frontend / Structural Parser | IMPLEMENTED | gemeinsame Dokument- und Struktureingabe |
| SemanticGraph / Candidates | PARTIALLY MIGRATED | Turn-IR und Ranking; nicht jede Domainprojektion liest alle Kanten |
| Direct Commands / Composition | PARTIALLY MIGRATED | Relative, Exclusion und Shared Predicate strukturiert; normale Compatibility-Compiler bleiben |
| Queries | PARTIALLY MIGRATED | `QueryCommand`/`QueryExecutor` produktiv, viele NL-Projektionen textbasiert |
| Discourse | PARTIALLY MIGRATED | Multi-Referent/Fokus produktiv, ältere `last_*`-Fallbacks bleiben |
| WorldModel / relationale Queries | PARTIALLY MIGRATED | Fakten vorhanden; allgemeine relationale NL-Projection UNSUPPORTED |
| Automationen | OBSERVABILITY ONLY für Graphautorität | Fachparser/Validator/Preview/Write produktiv |
| Temporal / Repair | OBSERVABILITY ONLY außerhalb bestehender Domainpfade | Erkennung impliziert keine Ausführung |
| Semantic Aliases | UNSUPPORTED end-to-end | bestätigter Store, keine allgemeine Graph-Expansion |
| Management / Calendar / Productivity | PARTIALLY MIGRATED | gemeinsame Grenze, separate Fachsemantik |
| Execution / Safety | IMPLEMENTED | Validator, Policy, Mapper und Executor autoritativ |

## Tests und Messwerte

- Gesamtsuite: 2.955 bestanden, 12 übersprungen; 88 % Coverage.
- Language-Evaluation: 125 bestanden.
- Structural-, Graph-, Snapshot-, Projektions-, Diskurs-, HouseGraph-,
  Relation-, Zeit-, Reparatur-, Pragmatik-, OOD- und Metamorphiktests.
- handgeschriebenes OOD-Korpus in `tests/data/v8_ood_de.json`, nicht aus
  Produkttemplates generiert.
- Shadow 4.72.0: 3.772 Turns, 3.752 identisch, 20 beidseitig ohne Treffer,
  keine Divergenz und keine Query-/Unsafe-/Ambiguous-Action-Leakage.
- Das Benchmarkscript enthält nun 16 Fälle einschließlich Multi-Clause,
  Temporal-, Repair-, relationalem Query- und Discourse-Shape.

Jüngste lokale p95-Messwerte der neuen Kategorien:

| Fall | p95 bei 5.000 Entities |
|---|---:|
| komplexer Relativfilter + Exclusion | 34,92 ms |
| Ambiguität | 27,00 ms |
| Multi-Target | 49,96 ms |
| Multi-Clause | 65,36 ms |
| Temporal Parse | 33,50 ms |
| Repair Parse | 41,14 ms |
| relationaler Unsupported-Shape | 50,64 ms |
| kontextfreie Follow-up-Form | 79,94 ms |
| Discourse-Referenz-Shape | 26,92 ms |

Gemessen mit 20 Iterationen und drei Warmups; der höchste p95 aller 16 Fälle
lag bei 79,94 ms und damit unter dem 100-ms-Gate. Mehrturnige Salience ist
implementiert; der Scriptfall misst den kontextfreien Referenz-Shape, nicht
die ConversationContext-Latenz.

## Bewusste Grenzen

- kein allgemeines Weltwissen und kein vollständiger Universalparser,
- keine Ausführung beliebig verschachtelter Condition-/Automationgraphen,
- keine natürliche Projektion jeder relationalen Hausquery,
- keine Ausführung jedes korrekt geparsten Zeit-/Reparaturgraphen,
- Dialog-UI/Persistenz für semantische Aliase bleibt kontrollierte
  Integrationsarbeit,
- Shadow kompletter Dialogsequenzen bleibt zusätzlich zum Einzelturn-Shadow
  offen.

Solche Fälle bleiben beim vorhandenen sicheren Verhalten oder werden
`UNSUPPORTED`/Clarification. Es gibt keinen LLM-, Cloud- oder statistischen
Fallback und keine still lernende Semantik.
