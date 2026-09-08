# HomeIntent V8 – produktiver Integrationsaudit

Stand: 8. September 2026  
Audit-Basis: `main`, Commit `d0df5436fd4cfeef0b803f474dcce53e0b1b7df4`

## Ergebnis

V8 ist im direkten Command-/Query-Pfad die produktive Orchestrierungsgrenze,
aber der `SemanticGraph` ist noch nicht durchgehend die Quelle der
Domain-Projektion. `SemanticInterpreter` baut den Graph, ruft anschließend
jedoch überwiegend textbasierte Compiler auf und hängt deren geerdetes Ergebnis
danach wieder an den Graph. Damit ist der Graph für Provenienz, Snapshots und
Safety-Beobachtung relevant, für viele positive Ausführungsentscheidungen aber
noch nicht autoritativ.

Die letzte Schreibgrenze ist konsolidiert: Direct Commands passieren
`validate_command`, `ReasoningEngine`, `ServiceMapper`, `ExecutionPolicy` und
`async_execute_service_plan`. Queries benutzen den read-only `QueryExecutor`.
Automationen besitzen einen getrennten, ebenfalls validierten Modell-, Preview-
und Write-Pfad. Diese Grenzen werden durch die Migration nicht ersetzt.

## Stufen-Audit

| Stufe | Bedeutungsquelle / Modell | Graph-Nutzung | Reparse / Parallelität | Verlust- und Legacy-Risiko |
|---|---|---|---|---|
| Conversation-Eingang | `LanguageDocument`, daneben Router-Regexe und Fachparser | einmal erzeugtes Dokument wird Direct/Management übergeben | Fachrouter analysieren `source_text` weiter selbst | Router vor dem Direct-Pfad können Graph und Candidates vollständig ignorieren |
| Language Frontend | Originaltext, Tokens, Varianten, `SemanticUtterance`, Lexikon, `GermanStructuralAnalysis`, Temporal | Graph wird erst im Interpreter gebaut | Varianten werden jeweils neu tokenisiert/analysiert; Registry-Compound-Fallback baut ein zweites Dokument | Original bleibt erhalten, aber normalisierte Varianten können später Compiler-Autorität gewinnen |
| Structural Analysis | tokenbasierte Clauses, Relations, Negation | liefert Graph-Klauseln und Kanten | kein HA-Zugriff; noch begrenzte Clause-Bindung | koordinierte NPs und koordinierte Prädikate sind nicht immer eindeutig unterschieden |
| Semantic Interpreter | Varianten, flache Slots, Compilerresultat, `MeaningCandidate` | Graph wird je Variante gebaut und nach Resolverresultat ergänzt | `analyse_semantics`, `analyse_turn`, Compiler und Composition analysieren Varianten/Text erneut | Compilerresultat bestimmt Vollständigkeit; Graph selbst projiziert nur Sonderfälle |
| Semantic Projection | Relative-/Exclusion-Sonderpfade | beobachtet Struktur, erstellt danach Compatibility-Frame | entfernt Klauseltext bzw. synthetisiert deutschen Text und ruft Compiler plus `analyse_semantics` erneut | Graph ist Auslöser, rekonstruierter Text bleibt Wahrheit |
| Composition | `SemanticTurn`, Mention-Scan, `CompositionalPlan` | kein Graph-Input | löscht andere Entitynamen per Regex, entfernt Konjunktionen, kompiliert pro Ziel neu | Scope kann durch Textoperationen verloren gehen; nur Shared-Predicate-Sonderform |
| Entity Grounding | `entity_resolution.py`, EntityIndex, Area-/Floor-Resolver, `WorldModel.select_entities` | geerdete IDs werden nachträglich mit `RESOLVES_TO` angehängt | Resolver sind autoritativ, aber Mention-/Registry-Hilfsscans existieren zusätzlich | kein zweiter Identitätsresolver, jedoch mehrfache Registry-Scans und getrennte Aufruflogik |
| Command Projection | `SemanticFrame` / `SemanticCommand` | Graph nur additives Frame-Feld | zahlreiche typisierte Bedeutungen verbleiben parallel in `parameters` | Action/Target/Filter/Exclusion/Temporal können zwischen Graph und Flat Frame divergieren |
| Capability / Validation | `validate_command`, Operation Registry | ignoriert Graph absichtlich und validiert Domainmodell | Parser besitzen zusätzliche Vorvalidierungen; Validator bleibt autoritativ | zulässig als Defense-in-depth; hoher Candidate-Score bedeutet nicht ausführbar |
| Reasoning / Policy | `ReasoningEngine`, `ExecutionPolicy` | Reasoning liest Frame/Context, nicht Graph | Policy wird vor und unmittelbar im Executor geprüft | Graphinformation ohne Frame-Projektion beeinflusst keine Ausführung |
| Service Mapping / Execution | `ServiceMapper`, `ServiceCallPlan`, zentraler Executor | keine Graph-Nutzung, korrekt späte Grenze | kein zweiter Direct-Executor | Queries werden vor Serviceplan geschützt; Live-Target/Capability wird erneut geprüft |
| Query | `SemanticQueryCompiler` -> `QueryCommand` -> `QueryExecutor` -> Response | Candidate trägt Graph, QueryCommand entsteht textbasiert | Spezialquerys in `parsers.py`, Household/History/Extended Router parallel | QueryCommand/Result liegen zusätzlich in `SemanticFrame.parameters`; Relation-NL nur teilweise projiziert |
| Follow-up / Reference | `ConversationContext`, `DiscourseState`, mehrere `match_*followup`-Methoden | vorheriger Graph/MeaningCandidate wird nicht gespeichert | Discourse-Resolver konkurriert mit last-entity/area/floor- und Spezialmatchern | Live-Entity-Prüfung ist sicher; Querygruppen/Fokus/Exclusions/Graphfragment fehlen |
| Automation | eigener Trigger-/Condition-/Action-Split -> `AutomationModel` -> Validator -> Preview -> Generator/Write | Interpreter baut Graph erst neben dem bereits geparsten Automationresultat | Komma-, Verbmarker-, IF- und AND-Splits sowie Fachparser analysieren Text mehrfach | Graph ist Observability; Clause-Grenzen und Fachmodell haben getrennte Autorität |
| Management / Calendar / Productivity | gemeinsames Dokument als Router-Eingabe, danach eigene Domainparser | kein produktiver Graph | eigene Datums-, Item- und Intent-Semantik; eigene Validatoren je Domain | benutzt `UnderstandingOutcome`, aber nicht dieselbe Bedeutungsprojektion |
| Temporal / Repair | Graphknoten und `REPLACES`; alte Temporal-Parameter/Parser | überwiegend Observability | CommandCompiler strippt Temporaltext rekursiv; Repair wird nicht allgemein projiziert | korrekt geparste Formen bleiben teils unsupported; das ist sicherer als Vereinfachung |
| Semantic Aliases | produktive bestätigte Entity-Aliase; separater `ConfirmedSemanticAliasStore` | keine Graph-Expansion | zwei Aliasmodelle; semantischer Store ohne Conversation-Persistenz/Use | Semantic Alias ist derzeit API/Tests, nicht end-to-end produktiv |
| WorldModel / HouseGraph | frischer HA-Snapshot; belegte Registryrelationen | getrennt vom Turngraph, wie beabsichtigt | ein WorldModel; HouseGraph wird im Conversation-Pfad gebaut, aber kaum abgefragt | Relationsdaten sind überwiegend Observability; keine erfundenen Beziehungen |

## Konkrete Reparse- und Rekonstruktionsstellen

- `nlu/semantic_projection.py`: `_without_clause`, `projected_text` und der
  synthetische `... außer ...`-Satz, jeweils gefolgt von
  `analyse_semantics()` und `SemanticCommandCompiler.compile()`.
- `nlu/composition.py`: `project_target()` entfernt Entitynamen und
  Konjunktionen mit Regex; Interpreter und AutomationActionParser kompilieren
  das Ergebnis erneut.
- `engine.py`: produktives `_AND_SPLIT_RE` in `understand()` und
  `_v7_multi_result()`; weitere Vorkommen im explizit read-only Legacy-Shadow.
- `SemanticInterpreter`: jede Textvariante wird neu lexikalisch und strukturell
  analysiert; `compile_text` wird nochmals semantisch gescannt.
- `SemanticCommandCompiler`: Exclusion und Temporal werden über Textsplit bzw.
  rekursives Textstrippen behandelt.
- `query_followup_compiler.py` und `semantic_automation.py`: wiederholte
  Lexikonanalyse statt Übergabe der vorhandenen Analyse/Graphteile.
- Automation: `split_trigger_action`, Verbmarker-Suche, `re.split(...oder
  wenn...)` und `split_on_top_level_and` bilden eine parallele Clause-Autorität.

## Typ- und Qualitätsbaseline vor Änderungen

- sauberer Checkout auf `main`;
- Pyflakes: 0 Befunde;
- vollständiges Pyright: 101 Fehler. Schwerpunkte sind `conversation.py`,
  `management_dialogs.py`, `parsers.py`, Automation-Parser/-Preview sowie
  Optional-Narrowing in Area/Floor/Query-Code;
- vollständiger Pytest-Baseline-Lauf: 2.948 bestanden, 12 übersprungen;
- CI enthält bereits Language Eval, Shadowreport, 5k/20/3/p95-100-ms-Gate,
  Coverage, Pyflakes, Strict-Scope, Hassfest, HACS und HA-Stable-Smoke.

## Migrationsstrategie

1. **Direct Graph Projection:** eine strukturierte, nicht ausführende
   Projection für sichere Shared-Predicate-, Relative-Filter- und
   Exclusion-Graphformen einführen. Sie benutzt ausschließlich vorhandene
   Entity-/Area-/Floor-Resolver und erzeugt `ParseResult/SemanticFrame` ohne
   deutschen Zwischentext.
2. **Structure-authoritative Composition:** Clause-/Relation-Struktur
   entscheidet, ob `AND` Ziele oder vollständige Prädikate verbindet. Erst
   alle Teilprojektionen validieren, danach einen atomaren `CommandPlan`
   freigeben. `OR` und nicht vollständig projizierbare Gruppen bleiben
   unsupported.
3. **Evidence:** Evidence-Arten und Gewichte in einem Modul zentralisieren;
   Registry-, Entity-, Area-, Floor-, Capability-, Property-, Unit-, Scope-,
   Context- und negative Evidenz nachvollziehbar erfassen. Ranking wählt
   Bedeutung, der Validator weiterhin Ausführbarkeit.
4. **Evaluation:** handgeschriebene OOD-Snapshots über Structure, Graph,
   Candidate, Grounding und Outcome; positive und negative metamorphische
   Kerne; echte Dialogsequenzen mit Conversation-ID-/TTL-/stale-Entity-Gates.
5. **Folgewellen:** Query-Follow-ups und relationales NL auf Graphprojection
   umstellen; danach Automation-Clause-Projection auf vorhandene
   Trigger/Condition/Action-Fachparser. Management und semantische Alias-
   Persistenz folgen erst, wenn dieselbe Grenze ohne zweiten Validator oder
   Resolver nutzbar ist.
6. **Type Safety:** Runtime-Grenzen in der geforderten Reihenfolge bereinigen
   und Strict-Scope nur erweitern, wenn der neue Slice tatsächlich 0 Fehler
   hat. CI wird bis zum vollständigen 0-Fehler-Lauf nicht abgeschwächt.

## Bewusst nicht als vollständig deklariert

Automation-, Management-, beliebige relationale Query-, allgemeine Temporal-
und Repair-Projection sowie semantische Alias-Persistenz sind nach diesem Audit
`PARTIALLY MIGRATED` oder `OBSERVABILITY ONLY`. Ein erkannter Graphoperator ist
kein Versprechen, dass er bereits sicher in ein ausführbares Domainmodell
projiziert werden kann.

## Umgesetzte erste Migrationswelle

- `semantic_projection.py` rekonstruiert keinen deutschen Satz mehr. Die
  sichere Projektion für Relative-State-Filter, Exclusions, Quantifier,
  Locations und Shared-Predicate-Targets erzeugt direkt den Compatibility-
  `SemanticFrame` und nutzt die bestehenden Resolver.
- Die produktive AND-Erkennung in `engine.py` wird aus strukturell belegten,
  vollständigen Prädikatklauseln abgeleitet. Source-Spans werden unverändert
  weitergereicht; unvollständige Operanden und `OR` werden nicht teilweise
  ausgeführt. Regex-Splitting bleibt nur im read-only Legacy-Shadow.
- Candidate-Scores stammen aus einer zentralen Evidence-Policy und tragen
  erklärbare positive und negative Beiträge. Validator und Policy bleiben
  davon unabhängig autoritativ.
- `DiscourseState` trägt mehrere Referenten, Grounding-Fokus und das aktuelle
  Graphfragment; Query-Ergebnisse werden als solche markiert und niemals als
  Action-Evidence umgedeutet.
- OOD-Tests prüfen jetzt Speech-Act, semantische Knoten und Graphkanten;
  negative Metamorphik schützt Negation, AND/OR und EXCEPT/ONLY.
- Ungebundene mehrklauselige Queries und kontextfreie Referenzen enden früh
  `UNSUPPORTED`, bevor ein bedeutungsloser 5k-Fuzzy-Registry-Scan startet.

Diese Welle konsolidiert Direct Commands und die gemeinsame IR. Automation,
allgemeine relationale Query-Projection, Repair-/Temporal-Projection und
Semantic-Alias-Persistenz bleiben absichtlich Folgewellen.

## Verifikation nach der Welle

- Gesamtsuite: 2.955 bestanden, 12 übersprungen; Gesamt-Coverage 88 %.
- Language-Eval: 125 bestanden.
- Shadow-Baseline: 3.752 identisch, 20 beidseitig abgelehnt, 0 divergent;
  Query-, Ambiguous- und Unsafe-Action-Leakage jeweils 0.
- 5k-Registry-Benchmark: 16 Fälle, 20 Iterationen, drei Warmups, höchster
  p95 79,94 ms bei einem Budget von 100 ms.
- Pyflakes: 0 Befunde. CI-Strict-Pyright: 0 Fehler. Full-Pyright bleibt bei
  den bereits vorhandenen 101 Fehlern; diese Welle hat den globalen
  Restbestand nicht mit `Any`, Ignorierungen oder unsicheren Casts verdeckt.
- Hassfest, HACS Action und der echte HA-Stable-Smoke bleiben CI-Gates. In
  der lokalen Umgebung standen weder Docker noch das `homeassistant`-Paket
  bereit; Manifest und `hacs.json` wurden lokal als valides JSON geprüft.
