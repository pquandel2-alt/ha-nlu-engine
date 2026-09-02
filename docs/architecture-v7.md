# HomeIntent V7 – aktive Understanding-Architektur

Stand: 28. August 2026

## Produktgrenze

HomeIntent V7 versteht Bedeutung innerhalb der unterstützten Smart-Home-
Operationen. Es verspricht nicht, jede beliebige deutsche Äußerung der Welt
auszuführen. Bei unvollständiger, widersprüchlicher oder mehrdeutiger
Bedeutung ist eine Rückfrage oder sichere Ablehnung das korrekte Ergebnis.
Eine nur ähnlich klingende Formulierung darf niemals ungeprüft eine Aktion
auslösen.

## Aktiver Pfad

```text
Originaltext + Registry + Dialogkontext
                 |
                 v
      loss-aware LanguageDocument
      - Originaltokens und Quellspannen
      - Normalisierungsvarianten mit Kosten/Herkunft
      - Sprechakt, Modalität, Polarität und Klauseln
                 |
                 v
        SemanticInterpreter
      - wiederverwendbare Katalogeinträge
      - vollständige MeaningCandidates
      - Konflikte, fehlende Slots, ungeklärte Tokens
                 |
                 v
       gemeinsamer Target Resolver
      - Exact/Alias/Token/Ort/Etage/Domain
      - nachvollziehbare Scores
      - Gleichstand => Rückfrage
                 |
                 v
        UnderstandingOutcome
      QUERY | COMMAND | AUTOMATION | CLARIFICATION
      AMBIGUOUS | UNSUPPORTED | UNSAFE
                 |
                 v
      Capability/Policy/Bestätigung/Executor
```

`NluEngine.understand()` ist die kanonische Grenze für direkte Turns,
`NluEngine.understand_automation()` für Automationsformulierungen. Die
Conversation-Integration erstellt pro frischem Turn genau ein
`LanguageDocument` und reicht es an diese Grenzen weiter.

Direkte Turns werden in `understand()` semantisch zuerst interpretiert. Eine
explizite Capability-Liste in `semantic_catalog.py` entscheidet, für welche
bereits vermessenen Paare aus HA-Domäne und Intent V7 autoritativ ist. Der
aktive Schnitt umfasst Ein/Aus für Licht, Schalter, Ventilator, Heizung,
Luftbefeuchter und Input-Boolean, Öffnen/Schließen für Cover und Ventile,
Media Play/Pause, Saugroboter Start/Stopp, Szenenaktivierung, Cover-/Licht-
Prozentwerte, Heizungs-Solltemperatur sowie typisierte Zustands-, Verb- und
Messwertabfragen. Nicht migrierte Fachcapabilities bleiben kontrollierter
Kompatibilitätsfallback. `UnderstandingOutcome.authority` macht diese
Entscheidung beobachtbar; der Live-Router lässt einen autoritativen V7-Treffer
vor dem historischen Device-Router passieren. Ausführbare V7-Autorität setzt
einen vollständigen Kandidaten und bei konkurrierenden vollständigen Lesarten
mindestens zehn Scorepunkte Abstand voraus; echte Target-Mehrdeutigkeit bleibt
unabhängig davon eine nicht ausführbare Klärung.

## Sicherheitsinvarianten

- Der Originaltext bleibt erhalten; Varianten überschreiben ihn nicht.
- Query, Hypothese, Unsicherheit und Negation sind nicht direkt ausführbar.
- Eine eindeutig erkannte, leicht vertippte Negation bleibt negativ.
- Phonetische Entity-Korrekturen werden nie still ausgeführt.
- Registry-Namen werden nicht als Grammatik interpretiert. Beispielsweise
  bleibt ein Script namens „Gute Nacht“ trotz der Nähe von „Nacht“ zu
  „nicht“ ein positives Ziel.
- Ein gleichwertiger Target-Gleichstand erzeugt eine Klärung, keinen
  First-Match.
- Klärungen nennen bis zu fünf unterscheidbare Kandidaten und akzeptieren
  Name, Alias, Bereich, Etage, Merkmal oder Ordinalzahl. Ein einzelner nur
  ungefähr passender Name verlangt ein explizites Ja; Nein bricht ab.
- Eine unklare Folgeantwort hält den Dialog offen. Abbruch, Timeout oder ein
  vollständiger neuer Befehl beenden ihn definiert.
- Die ausgewählte stabile Entity-ID wird vor Ausführung gegen den aktuellen
  Registry-Snapshot und die aktuelle Capability erneut validiert.
- Erst ein validierter `ServiceCallPlan` darf den Executor erreichen.

## Entity-Kandidatenvertrag

`EntityCandidateSet` enthält Score, Matchquelle, passenden Registry-Namen,
Edit-Distanz, Margin und die stabile Entity-ID. Exakte Namen und Aliase
liegen über Teiltreffern; fuzzy Evidenz liegt darunter. Ein einzelner
fuzzy-only Treffer ist `CONFIRMATION_REQUIRED`, mehrere Treffer innerhalb
der Sicherheitsmargin sind `AMBIGUOUS`.

Der Vertrag wird von direkten Befehlen, Singular-Queries und den bestehenden
Kalender-, Listen- und Timer-Auswahldialogen konsumiert. Automationsparser
nutzen denselben Resolver und dürfen ein mehrdeutiges Ziel nicht in ein
`AutomationModel` übernehmen.

## Migration und Kompatibilität

Die öffentliche V7-Grenze und der erste autoritative Capability-Schnitt sind
live. Bereits bewährte Hassil- und Spezialparser erzeugen während der
Migration weiterhin den größeren Teil der validierten Payloads hinter dieser
Grenze. Sie dürfen das gemeinsame Frontend und dessen Sicherheitsentscheidung
nicht umgehen. Redundante Gruppen-Semantik wurde entfernt und auf den
Semantic Compiler delegiert.

Der read-only Shadow-Vergleich ist über
`NluEngine.compare_understanding_pipelines()` reproduzierbar. Das Skript
`scripts/v7_shadow_report.py` führt ihn über Dialogkorpus, 1.024
Lichtparaphrasen und 2.688 domänenübergreifende Direktbefehle aus. Der
versionierte Bericht enthält 3.772 Turns: 3.752 semantisch identisch, keinen
nur-Legacy- oder nur-V7-Treffer, keine Divergenz und 20 beidseitige sichere
Fehlschläge. Diese Fehlschläge sind kontextabhängige Folgeturns oder bewusst
nicht ausführbare Hypothesen, unbekannte/ungültige Ziele und Werte. Der Shadow-Pfad erzeugt
nur unveränderliche Pläne und Antworten und besitzt keinen HA-Executor.
Im selben Lauf sind Query-to-Action-, Unsafe-Action- und
Ambiguous-to-Action-Leakage jeweils null.

Das ist bewusst keine Behauptung, sämtliche historischen Parser seien schon
gelöscht. Kalender, Produktivität und einzelne Managementfunktionen besitzen
weiterhin fachspezifische Parser. Ihr nächster Umbau ist eine interne
Migration hinter dieselbe `UnderstandingOutcome`-Grenze; die zentrale
Sicherheitsklassifikation schützt sie bereits heute.

## Qualitätsgates

Der Sprach-Eval-Lauf bündelt das unabhängige Dialogkorpus, metamorphe
Invarianzprüfungen, die bestehende 1.024er-Paraphrasenmatrix und die
domänenübergreifenden V7-Semantikverträge:

```bash
bash scripts/run_language_eval.sh
```

Der vollständige Projektlauf sowie Pyflakes und der blockierende
Pyright-Strict-Scope bleiben zusätzlich verpflichtend. CI prüft auf Python
3.12 außerdem den versionierten Shadow-Bericht und ein 100-ms-p95-Budget bei
5.000 synthetischen Entities. Performancewerte und die noch erforderliche
Messung auf echter Pi-Hardware stehen in
[`perf/v7-understanding.md`](perf/v7-understanding.md).

`conversation.py` erreicht 80 % Coverage. Der Ausbau konzentriert sich auf
offene Dialogzustände und risikoreiche Übergänge: Entity-Auswahl,
Bestätigung/Abbruch, Wizard-Retries, Todo-Mutationen, Mehrfachbefehle mit
Undo, Automationsauswahl sowie Laufzeitfehler. Ein End-to-End-Test schlägt
weiterhin fehl, sobald ein migrierter V7-Pfad wieder den alten Device-Router
erreicht.

## Nachgelagerter lokaler Agentenkern

V7 bleibt der einzige Spracheinstieg. Dahinter teilen sich Dialogmanager,
Hausgraph, Gedächtnis, Situationen und Planer dieselben stabilen IDs aus dem
pro Turn gebauten `WorldModel`. Der vollständige Vertrag ist in
[`jarvis-core.md`](jarvis-core.md) dokumentiert. Keine dieser Schichten darf
Home-Assistant-Dienste ausführen; auch Mehrschrittpläne und persistierte
Agentenaktionen laufen ausschließlich durch Execution Policy und gemeinsamen
Executor mit frischem Snapshot.

Katalogisierte Komfort- und Haushaltsszenarien werden erst nach dem
`LanguageDocument` erkannt. Sie arbeiten ausschließlich mit stabilen IDs und
geben typisierte ASK-Vorschläge beziehungsweise `AutomationModel`-Bäume an
die vorhandenen Validator-, Vorschau- und Bestätigungsstrecken weiter. Sie
führen keine rohe Äußerung direkt in einen Home-Assistant-Serviceaufruf um.
