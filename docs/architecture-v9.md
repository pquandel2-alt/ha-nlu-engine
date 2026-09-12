# HomeIntent V9 – Semantic Reasoning

## Grenze zwischen V8 und V9

V8 beantwortet, welche Bedeutung ein deutscher Turn ausdrückt. Seine
autoritative Kette bleibt unverändert: `LanguageDocument` →
`GermanStructuralAnalysis` → `SemanticGraph` → `MeaningCandidates` und
`Evidence` → Grounding. V9 interpretiert den Text nicht erneut. Es wertet
die geerdete Bedeutung über ausschließlich bekannte Fakten des turn-lokalen
`WorldModel` und dessen `HouseGraph` aus.

Beispiel: V8 liefert Zieltyp *Area* sowie den relationalen Filter
*enthält Fenster mit Zustand offen*. V9 berechnet daraus die konkreten Areas.
Ein `ReasoningResult` ist niemals eine Ausführungserlaubnis.

## Typisierte Query-Algebra

`QueryCommand` bleibt das einzige Query-Modell und `QueryExecutor` der einzige
Evaluator. Einfache V8-Queries verwenden weiterhin `target` und `filter`.
Komplexe Queries setzen optional einen typisierten `algebra`-Baum aus:

- `SourceExpression`, `StateFilterExpression` und `RelationFilterExpression`
- `TraverseExpression` und explizite `QueryTraversal`-Pfade
- `SetExpression` für Intersection, Union und Difference
- `AggregateExpression` für COUNT, EXISTS, ANY, ALL sowie typisierte
  MIN/MAX/AVG-Eingaben
- `GroupExpression` und `ThresholdExpression`
- `MeasurementExpression`, `CompareExpression`, `OrderExpression`, `LimitExpression`

Es gibt keine SQL-Strings und kein frei interpretierbares Bedeutungs-Dict.
Die Ausdruckstypen tragen `RelationKind`, Richtung, Property, Operator und
Zieltyp explizit.

## Graph-Traversal und Fakten

`HouseGraph.traverse()` folgt ausschließlich einem vorgegebenen Pfad aus
bekannten `RelationKind`-Werten. Standardmäßig gilt `asserted_only=True`.
OBSERVED, CONFIGURED, CONFIRMED_MEMORY und DERIVED sind belegte Kanten;
STATISTICAL ist keine harte Tatsache. Die Traversal ist auf höchstens acht
Hops begrenzt (Query-Standard: vier), schützt jeden Pfad gegen Zyklen und
liefert deterministisch sortierte Ergebnisse samt `GraphRelation`-Belegen.
Outgoing-/Incoming- und Edge-Lookups verwenden die vorhandenen Indizes.

Produktive relationale Filter kombinieren Target + Relation + Nested
Constraint. Unterstützt sind insbesondere Areas mit offenen Fenstern,
Entities in solchen Areas und Same-Area-Abfragen. Dieselbe Auswahl wird für
relationale Commands benutzt; deren IDs werden vor der normalen Action-
Pipeline aus dem aktuellen `WorldModel` erneut geerdet.

## Aggregate, Grouping und Superlative

COUNT und EXISTS arbeiten auf typisierten Mengen. Group-by projiziert über
eine explizite Graphrelation, beispielsweise `entity --ON_FLOOR--> floor`.
Superlative bestehen aus Selection Scope, eindeutigem Measurement Binding,
Sortierrichtung und Limit. Ein Raumwert existiert nur bei genau einem
passenden Messsensor oder einer expliziten `PREFERRED_MEASUREMENT`-Kante.
Mehrere gleichwertige Sensoren ergeben AMBIGUOUS; es wird weder der erste
Sensor gewählt noch automatisch gemittelt.

## Measurement Binding und Units

Messsensoren werden über `MEASURES` an `SemanticProperty` gebunden. V9
normalisiert nur die geschlossene, getestete Liste °C↔°F, W↔kW und Wh↔kWh.
Unbekannte oder dimensionsfremde Einheiten bleiben nicht auswertbar.
Comparative Set Queries verlangen auf der Referenzseite genau einen
eindeutigen Messwert.

## Mengen und Discourse

Union, Intersection und Difference operieren auf geerdeten stabilen IDs.
`DiscourseState` speichert komplexe Resultate zusätzlich als begrenzte
`DiscourseGroup`: Group-ID, semantischer Typ, Member-IDs, Origin Query,
Graphfragment, Filter, Relationsprovenienz, Turn und Salienz. Die Gruppe ist
ein Dialogreferent, kein ausführbares Target-Cache. Aktionen müssen ihre
Mitglieder gegen einen frischen Live-Snapshot erneut erden.

## Repair und Temporalität

Entity Repair aus V8 bleibt autoritativ. V9 projiziert zusätzlich eindeutige
Value Repairs für dieselbe Property und kompatible Unit; der Ersatzwert
überschreibt den alten vollständig. Unvollständige Property Repairs werden
sicher abgelehnt und übernehmen niemals einen alten, inkompatiblen Wert.

Die vorhandenen persistenten One-shot-Automation-Pfade für relative und
kalendergebundene Zeitbefehle bleiben die Scheduling-Autorität. Weder die
Reasoning-Schicht noch `QueryExecutor` schlafen oder halten langlebige
In-Memory-Timer. Delay und Duration sind im `TemporalExpression` und
`AutomationModel` getrennte Bedeutungen. Formen, die der vorhandene
Scheduler nicht sicher konkretisieren kann, bleiben ohne Sofortaktion.

## Reasoning Trace und „Warum?“

Jede Algebra-Auswertung kann einen `ReasoningTrace` aus symbolischen Schritten
erzeugen: Source-IDs, State-Filter, verwendete Relations-IDs, Aggregate,
Grouping, Measurement, Vergleich, Sortierung und Limit. Dies ist kein
Chain-of-Thought, sondern reproduzierbare Programmausführung. Der Trace ist
im Semantic Snapshot sichtbar. Nutzererklärungen nennen ausschließlich die
verwendeten Registry-Entities, Zustände, Sensoren und Werte; die vorhandene
„Warum?“-Discourse-Funktion speichert diese Erklärung für den Folgeturn.

## Safety und Kosten

Query Algebra importiert keinen Service Mapper und kann keinen ServicePlan
erzeugen. QUERY, AMBIGUOUS, UNSUPPORTED, UNSAFE und HYPOTHETICAL bleiben
nicht ausführbar. Relationale Commands durchlaufen weiterhin Capability,
Validator, ExecutionPolicy, Risk/Confirmation, ServiceMapper und Executor.
Negierte relationale Commands gelangen nicht in den positiven Auswahlpfad.

Das deterministische Cost Model berücksichtigt Candidate-Anzahl, Filter,
Traversal-Hops, verschachtelte Relationen, Mengenoperationen, Grouping,
Messung und Sortierung. Überschreitung liefert einen expliziten sicheren
Fehlschlag statt abgeschnittener oder semantisch veränderter Resultate.
Caches gelten nur innerhalb des unveränderlichen Turn-`WorldModel`.

Das bestehende p95-≤-100-ms-Gate bei 5.000 Entities bleibt für gewöhnliche
Query- und Command-Pfade unverändert. Nach Indexoptimierung gelten für bewusst
komplexe V9-Formen zusätzliche 5k-p95-Grenzen: 500 ms für relationale und
Zwei-Hop-Abfragen, 250 ms für verschachtelte relationale Filter und
Gruppenreferenzformen, 400 ms für verschachtelte Aggregate, 300 ms für
Messwert-Superlative und 750 ms für relationale Command-Zielselektion. Der
Benchmark prüft diese Budgets pro Label; eine Überschreitung verändert nie die
Semantik.

## Unterstützte Grenzen

Produktiv sind die typisierte Algebra, bounded Traversal, relationale
Window/Area/Light-Filter, COUNT/EXISTS, Floor-Grouping, eindeutige
Measurement-Superlative, kompatible Unit-Konvertierung, Area-Vergleiche,
Set-Algebra, Value Repair, ReasoningTrace und live re-geerdete relationale
Licht-Commands. Die generischen Typen für ANY/ALL/MIN/MAX/AVG sind vorhanden;
nur sicher typisierte Eingaben werden ausgewertet.

Noch nicht als unterstützt gelten freie Relationserfindungen, automatische
Sensorpräferenzen, automatische Mittelwerte, unbekannte Units, unvollständige
Property Repairs, unbestimmte Dayparts ohne lokale Regel, History-Dauern ohne
Timestamp/Recorder-Beleg sowie direkte Ausführung gespeicherter Discourse-
Gruppen. Diese Grenzen führen zu Clarification/AMBIGUOUS/UNSUPPORTED, niemals
zu einer stillen Ersatzsemantik.
