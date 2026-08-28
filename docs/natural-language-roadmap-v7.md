# HomeIntent V7 – Roadmap für belastbares natürliches Sprachverständnis

Stand: 28. August 2026
Analysierter Stand: `b808844` / HomeIntent 4.59.0

## Umsetzungsstand

Die sechs Phasen wurden in der vorgesehenen Reihenfolge als V7-Kern
umgesetzt: typisierte Outcomes und Shadow-Vergleich, gemeinsames
Sprach-Frontend, zentraler Katalog, Kandidaten-Interpreter, erklärbare
Target-Auflösung, ein Live-Einstieg für direkte und Automations-Turns,
zentrale Dialogpriorität sowie CI-, Contract- und Performance-Gates.

Die aktive Architektur ist in
[`architecture-v7.md`](architecture-v7.md) beschrieben. Historische
Fachparser bleiben vorerst als Payload-Erzeuger **hinter** der neuen Grenze,
wo ihre bewährte Capability-Abdeckung noch nicht vollständig semantisch
ersetzt ist. Sie umgehen weder das einmalige Frontend noch dessen globales
Sicherheitsgate. „Phase umgesetzt“ bedeutet daher nicht, dass schon jeder
Kompatibilitätsparser gelöscht wurde; dieser Abbau erfolgt capabilityweise,
damit breite Funktionalität nicht durch einen Big-Bang-Umbau verloren geht.

Der nachgelagerte Mehrdeutigkeitsausbau ist ebenfalls umgesetzt: ein
gemeinsames `EntityCandidateSet`, bounded Schreib-/ASR-Ähnlichkeit,
nummerierte unterscheidbare Rückfragen, Auswahl per Name/Alias/Ort/Etage/
Merkmal/Ordinal, wiederholbare Fehlversuche und Revalidierung der stabilen
Entity-ID vor Ausführung. Direkte Befehle, Singular-Queries, Kalender sowie
Listen- und Timerdialoge verwenden denselben Auswahlvertrag;
Automationsmodelle verweigern weiterhin jedes nicht eindeutig aufgelöste
Ziel.

## 1. Ziel und ehrliches Produktversprechen

Das Ziel ist nicht, für jede neue Formulierung einen neuen Test und eine neue
Regex oder Hassil-Satzschablone einzubauen. Eine Äußerung soll aus
wiederverwendbaren Bedeutungsbestandteilen verstanden werden:

```text
Sprache
  -> Äußerungsart und Klauseln
  -> semantische Bestandteile
  -> eine oder mehrere vollständige Bedeutungs-Hypothesen
  -> Auflösung gegen Kontext und Home-Assistant-Weltmodell
  -> Capability- und Sicherheitsprüfung
  -> Antwort, Rückfrage, Query oder geprüfter Ausführungsplan
```

„Egal wie man es sagt oder schreibt“ kann kein begrenztes NLU-System absolut
garantieren. Insbesondere bleiben echte Mehrdeutigkeit, unbekannte Begriffe und
Äußerungen außerhalb des Smart-Home-Bereichs. Das belastbare Versprechen soll
daher lauten:

> Innerhalb der unterstützten Smart-Home-Bedeutungen versteht HomeIntent freie
> Wortstellung, gebräuchliche Synonyme, Flexion, Zusammensetzungen, Füllwörter,
> typische Schreib- und ASR-Varianten sowie eindeutige Folgeäußerungen. Wenn
> die Bedeutung nicht eindeutig ist, fragt es gezielt nach und führt niemals
> eine nur erratene Aktion aus.

Der wichtigste Qualitätsmaßstab ist damit nicht „immer irgendeinen Treffer
liefern“, sondern diese Reihenfolge:

1. richtig verstehen und richtig auflösen,
2. bei behebbarer Unvollständigkeit gezielt nachfragen,
3. bei unbekannter oder widersprüchlicher Bedeutung nachvollziehbar ablehnen,
4. niemals eine falsche Aktion ausführen.

## 2. Bestandsaufnahme

Der aktuelle Stand ist funktional und sicherheitsbewusst:

- 2.443 Tests bestehen, 12 sind übersprungen;
- die zuletzt gemessene Gesamt-Coverage liegt bei 85 %; die zentralen
  Sprachmodule liegen überwiegend deutlich höher, `conversation.py` erreicht
  nach dem risikobasierten Dialogtestausbau 80 %;
- 147 Python-Testdateien sind vorhanden;
- `SemanticUtterance`, `SemanticAnalysis`, `SemanticFrame`, `WorldModel`,
  Constraint Resolver, Capability-Prüfung und strukturierte Dialogzustände
  existieren bereits;
- Queries und schreibende Befehle werden vor der Ausführung getrennt;
- Ambiguität wird überwiegend abgelehnt oder durch Rückfragen behandelt;
- direkte Befehle, Automationen und Dialoge besitzen Bestätigungs- und
  Sicherheitsgrenzen.

Die vorhandene Testsuite belegt Regressionstreue, aber noch keine breite
Generalisierung:

- das echte Dialog-Evaluationskorpus enthält 45 Fälle;
- die 1.024 Fälle der Paraphrasenmatrix kombinieren 16 künstliche Namen, vier
  Partikel und acht Satzhüllen, prüfen semantisch aber nur `light.turn_on` und
  `light.turn_off`;
- viele Tests stammen aus denselben Wortlisten und Satzformen wie die
  Produktivlogik und sind deshalb nicht wirklich „ungesehen“.

Die wesentlichen Architekturbremsen sind:

1. **Semantik ist capabilityweise Autorität.** Seit dem Audit vom
   28. August laufen direkte Turns in `NluEngine.understand()` semantisch
   zuerst. Die explizite autoritative Matrix umfasst die vermessenen Core-
   Commands, Prozent-/Temperaturwerte sowie Zustands-, Verb- und
   Messwertqueries. Nur nicht migrierte Fachcapabilities behalten Legacy als
   Kompatibilitätsfallback. `_select_parser()` bleibt für diese Restmenge eine
   offene Architekturbremse.
2. **Routing ist reihenfolgeabhängig.** `conversation.py::_async_handle_message()`
   probiert viele Dialog-, Kalender-, Produktivitäts-, Geräte-, Automations-
   und Core-Matcher nacheinander. Der erste Treffer gewinnt. Die Bedeutung
   wird dadurch nicht einmal zentral erkannt und danach fachlich geroutet.
3. **Vokabular und Operationen sind verteilt.** Trotz
   `nlu/domain_operations.py` besitzen unter anderem `engine.py`,
   `group_semantics.py`, `device_control.py`, Kalender-, Produktivitäts- und
   Automationsmodule eigene überlappende Wort- und Regexbestände.
4. **Normalisierung verändert teilweise Satzstruktur.** Einige natürliche
   Hüllen werden vor der Analyse in kanonische Befehle umgeschrieben. Das
   hilft bekannten Fällen, kann aber Modalität, Negationsbezug oder
   Klauselrollen verdecken.
5. **Mehrere parallele Sprachpfade erzeugen Drift.** Der Core umfasst derzeit
   108 Python-Dateien, rund 31.000 Zeilen, 259 `re.compile()`-Aufrufe, 50
   Intent-YAML-Dateien und etwa 450 Hassil-Satzeinträge. Eine Verbesserung in
   einem Pfad gilt deshalb nicht automatisch für die anderen.
6. **Der Dialogzustand ist explizit klassifiziert, die Handler bleiben aber
   orchestral fragmentiert.** `active_pending_dialog()` bildet bereits eine
   deterministische State-Machine mit sichtbaren Konflikten. Die einzelnen
   Zustände werden in `conversation.py` dennoch durch getrennte Handler
   behandelt. Das ist nicht mit einer fehlenden State-Machine gleichzusetzen,
   bleibt aber Integrations- und Testschuld.

### 2.1 Verifizierter Shadow-Ausgangsstand

`scripts/v7_shadow_report.py` vergleicht Legacy und vollständig kompiliertes
V7 ohne Serviceausführung. Der versionierte Bericht
`docs/perf/v7-shadow-baseline-4.62.0.json` umfasst 3.772 Turns:

- 3.752 semantisch identische Ergebnisse,
- 0 Treffer nur im Legacy-Pfad,
- 0 Treffer nur im V7-Pfad,
- 0 Divergenzen,
- 20 beidseitige sichere Fehlschläge (kontextabhängige Folgeturns oder
  bewusst nicht ausführbare/ungültige Einzelturns).

Query-to-Action-, Unsafe-Action- und Ambiguous-to-Action-Leakage sind in
diesem Lauf jeweils null.

Die zuvor belegten Legacy-only-Fälle und die Antwortdivergenz wurden durch
domain-aware Konfliktauflösung, typisierte Verb-/Messwertqueries und
kompositionale Mehrzielbefehle geschlossen. Entfernt werden historische
Fachparser trotzdem erst capabilityweise; ein sauberer Shadow-Bericht ist
die notwendige, nicht die allein hinreichende Löschfreigabe.

## 3. Zielarchitektur

V7 macht einen gemeinsamen `UnderstandingEngine` zum einzigen sprachlichen
Einstieg. Fachmodule erhalten keine rohe Äußerung mehr, sondern eine
strukturierte Interpretation.

```text
                         +----------------------+
Text + Dialogkontext --->| German Language Frontend |
                         +----------+-----------+
                                    |
                  Tokens, Spans, Varianten, Klauseln
                                    |
                         +----------v-----------+
                         | Semantic Interpreter |
                         +----------+-----------+
                                    |
                       0..n MeaningCandidate
                                    |
             +----------------------+----------------------+
             | Context + WorldModel + Entity/Area Resolver |
             +----------------------+----------------------+
                                    |
                     UnderstandingOutcome (genau eins)
                                    |
          +-------------------------+-------------------------+
          |                         |                         |
        Query                 Safe Command              Clarification
          |                         |                         |
    Query Executor       Validator/Policy/Mapper          Dialog State
```

### 3.1 Einheitliches Ergebnis

Jeder Turn liefert genau einen typisierten Ausgang:

- `UnderstoodQuery`
- `UnderstoodCommand`
- `UnderstoodAutomation`
- `UnderstoodManagementOperation`
- `NeedsClarification`
- `UnsupportedMeaning`
- `AmbiguousMeaning`
- `UnsafeMeaning`

Jeder Ausgang enthält erkannte Spans, ungeklärte Tokens, Kandidaten,
Konfidenz/Margin, angewandte Korrekturen und eine maschinenlesbare Begründung.
`None` als bedeutungsarmes universelles „nicht verstanden“ wird aus der
Produktionspipeline entfernt.

### 3.2 Ein gemeinsamer semantischer Katalog

Ein deklarativer Katalog wird die einzige Quelle für diese Informationen:

- Aktionen und ihre sprachlichen Ausdrücke,
- Domänen, Geräteklassen und Eigenschaften,
- Zustände, Werte, Einheiten, Richtungen und Abstufungen,
- Query-Operationen, Mengen und logische Operatoren,
- benötigte Capabilities,
- erlaubte Domain-/Action-/Property-Kombinationen,
- Zuordnung zu Query-Operation oder HA-Service erst nach Validierung.

Domainmodule registrieren fachliche Operationen und Capabilities, keine
vollständigen deutschen Sätze. Ein neues Synonym erweitert dadurch alle
Wortstellungen, Queries, Befehle, Automationsaktionen und Folgeäußerungen, in
denen seine Bedeutung zulässig ist.

### 3.3 Verlustarmes deutsches Sprach-Frontend

Das Frontend erzeugt Varianten, überschreibt den Originalsatz aber nicht. Es
benötigt:

- Tokenisierung mit stabilen Quellspannen;
- Groß-/Kleinschreibung, Umlaute und `ss`/`ß` als orthografische Varianten;
- leichte deutsche Flexions- und Imperativnormalisierung;
- trennbare Verben ohne satzspezifische Rewrite-Regeln;
- Zahl-, Bruch-, Zeit- und Einheitenparser als typisierte Werte;
- Dekomposition deutscher Zusammensetzungen gegen dynamische HA-Namen,
  Bereiche, Etagen und bekannte Gerätenomen;
- typische ASR-Tokenisierung und eng begrenzte Laut-/Edit-Distanz-Kandidaten
  mit Herkunft und Kosten;
- Erhalt von Negation, Modalität, Satzzeichen und Klauselgrenzen.

Alle Normalisierungen bilden eine Kandidaten-Lattice. Original und Varianten
bleiben sichtbar, sodass keine frühe Umschreibung die spätere Bedeutung
unbemerkt verändert.

### 3.4 Kandidaten statt First-Match

Der Interpreter erzeugt bei strukturell möglichen Lesarten Kandidaten und
bewertet explizit:

- sprachliche Evidenz,
- Abdeckung der bedeutungstragenden Tokens,
- grammatische beziehungsweise klausale Konsistenz,
- Kontextpassung,
- eindeutige Entity-/Area-Auflösung,
- Capability-Passung,
- Kosten einer Schreib-/ASR-Korrektur.

Scoring darf nur ordnen. Ausgeführt wird ausschließlich, wenn genau eine
vollständige Interpretation eine definierte Mindestgüte und einen
ausreichenden Abstand zur zweitbesten Interpretation besitzt. Andernfalls
wird aus den konkurrierenden Slots eine konkrete Rückfrage erzeugt.

### 3.5 Gemeinsame Semantik, getrennte Ausführung

Direkte Befehle, Queries, Automationen, Kalender und Produktivität verwenden
dieselben Frontend- und Bedeutungsprimitive. Fachlich notwendige Modelle und
Executor bleiben getrennt. Insbesondere bleibt unverändert:

- Queries dürfen nie einen Serviceplan erzeugen;
- Parser beziehungsweise Interpreter führen nie HA-Services aus;
- HA-Zustand und HA-Capabilities bleiben Quelle der Wahrheit;
- risikoreiche Aktionen behalten Bestätigung und Policy-Prüfung.

## 4. Umsetzungsphasen

Jede Phase ist ein eigenständig reviewbarer Schritt. Legacy-Code wird nicht
auf unbestimmte Zeit als gleichberechtigter Fallback behalten, sondern in
Shadow Mode verglichen und nach bestandenen Gates entfernt.

### Phase 0 – Messbarkeit vor Umbau

**Lieferumfang**

- `UnderstandingOutcome` und ein durchgängiger, datenschutzfreundlicher
  Debug-Trace;
- Inventar, welcher aktuelle Matcher welchen Turn gewinnt;
- semantische Metriken statt bloßer „Matcher gab etwas zurück“-Metriken;
- ein Shadow-Harness, das Legacy-Ergebnis und neue Interpretation ohne
  doppelte Ausführung vergleicht;
- Baseline getrennt nach Commands, Queries, Automationen, Dialog,
  Entity-Auflösung, Schreibweise und Sicherheitsfällen.

**Gate**

- jede bestehende Äußerung kann einem aktuellen Sprachpfad und einem
  strukturierten Ergebnisgrund zugeordnet werden;
- null ungeprüfte Serviceausführungen im Shadow Mode.

### Phase 1 – Ein Frontend und ein Vokabular

**Lieferumfang**

- zentraler semantischer Katalog auf Basis von `domain_operations.py` und
  `semantic_lexicon.py`;
- Token-/Span-Modell und verlustarme Normalisierungs-Lattice;
- zentrale Parser für Zahlen, Einheiten, Zeit, Menge und Negation;
- Compound-, Flexions-, Schreib- und ASR-Kandidaten;
- Drift-Tests, die doppelte Aktions-/Domain-/Property-Wortlisten außerhalb
  des Katalogs verhindern.

**Gate**

- eine neue lexikalische Variante wird an genau einer Stelle eingetragen;
- Originalspan und jede angewandte Normalisierung sind im Trace sichtbar;
- Negation, Frage/Befehl und Trigger/Aktion bleiben unter allen
  Normalisierungen invariant.

### Phase 2 – Vollständiger Semantic Interpreter

**Lieferumfang**

- ein Interpreter für Sprechakt, Modalität, Klauseln und koordinierte
  Strukturen;
- ein gemeinsames Kandidatenmodell für Action, Target, Property, State,
  Value, Unit, Quantity, Location, Exclusion, Time und Reference;
- Kandidatenkonflikte und ungeklärte bedeutungstragende Tokens als
  erstklassige Ergebnisse;
- generische Slot-Vervollständigung aus Dialogkontext und World Model;
- semantisch erzeugte, slotgenaue Rückfragen.

**Pilotumfang**

Nicht nur Licht an/aus, sondern eine vertikale Matrix:

- direkte Aktionen für Licht, Cover, Climate, Fan und Media Player;
- Zustands-, Existenz-, Anzahl-, Orts- und Messwertqueries;
- Mengen, Ausschlüsse, Werte, Vergleiche und zwei Klauseln;
- positive, negierte, hypothetische, widersprüchliche und mehrdeutige Formen.

**Gate**

- alle Pilotdomänen laufen zuerst durch dieselbe Interpreter-API;
- Wortstellungs- oder Hüllenvarianten verändern bei gleicher Bedeutung weder
  Frame noch aufgelöstes Ziel;
- unbekannte bedeutungstragende Zusätze können keinen ausführbaren Plan
  erzeugen.

### Phase 3 – Entity-, Orts- und Referenzauflösung vereinheitlichen

**Lieferumfang**

- ein indexierter Resolver für Namen, Aliase, Entity-IDs, Bereiche, Etagen,
  Geräteklassen und Capabilities;
- nachvollziehbare Teil-Scores für exakt, Alias, Compound, Tokenfolge,
  phonetisch und Edit-Distanz;
- genau ein Ambiguitätsmodell mit Margin und Kandidatenherkunft;
- kontextuelle Referenzen über einen Salienz- und Scope-Stack statt
  einzelner Pronomen-Sonderrouten;
- vollständige neue Befehle dürfen offene Ergänzungsdialoge systematisch
  ersetzen; echte kurze Antworten ergänzen den offenen Slot.

**Gate**

- dieselbe Namensform wird in Command, Query, Automation und Follow-up gleich
  aufgelöst;
- Entity-Auflösung findet pro Turn nur einmal statt und nutzt Indizes;
- gleichwertige Ziele führen immer zur Rückfrage, nie zum First-Match.

### Phase 4 – Einen Router statt einer Matcher-Kaskade

**Lieferumfang**

- `UnderstandingEngine.understand(text, context, world_model, now)` als
  einziger Spracheinstieg in `conversation.py`;
- explizite Dialog-State-Machine für offene Bestätigungen und Slotfragen;
- fachliches Dispatching anhand des typisierten Ergebnisses, nicht anhand
  weiterer Regex-Gates auf dem Rohtext;
- Shadow-Vergleich und schrittweise Migration von Core Commands, Queries,
  Automationen, Kalender, Produktivität und Management;
- Entfernung der abgelösten `_select_parser()`-, First-Match-, Hassil- und
  Regexpfade nach jeder erfolgreich migrierten Capability-Matrix.

**Gate**

- Reihenfolge von Fachmodulen kann die erkannte Bedeutung nicht mehr ändern;
- jede rohe Äußerung wird genau einmal sprachlich analysiert;
- kein migriertes Feature fällt zurück in einen zweiten Sprachparser.

### Phase 5 – Dialog als semantische Fortsetzung

**Lieferumfang**

- kanonisches Turn-Memory mit letzter Interpretation, Fokus, Scope,
  Referenten und offenen Slots;
- allgemeine Behandlung von Ellipsen, Pronomen, Korrekturen und
  Ziel-/Wertwechseln;
- klare Regeln für Fortsetzen, Korrigieren, Abbrechen und Ersetzen eines
  Dialogs;
- Rückfragen aus fehlenden oder konkurrierenden Slots statt fest codierter
  Dialogpfade.

**Gate**

- dieselbe Folgeäußerung verhält sich für alle kompatiblen Domänen gleich;
- ein unbekannter neuer Gerätename kann niemals auf das alte Fokusgerät
  umgeleitet werden;
- der Trace erklärt, welcher Kontextwert übernommen oder verworfen wurde.

### Phase 6 – Legacy-Abbau und Release-Härtung

**Lieferumfang**

- Entfernung redundanter Hassil-Grammatiken, Wortlisten und Regexrouter;
- Performanceprofil auf Raspberry-Pi-Klasse;
- Typprüfung des neuen Core-Pfads im Strict Mode;
- Migration der Debug-/Erklärungsantworten auf `UnderstandingOutcome`;
- aktualisierte Architektur- und Nutzergrenzen.

**Gate**

- keine steigende Zahl paralleler Parser während der Migration;
- p95-Latenz und Speicherbudget werden vor Phase 0 festgelegt und auf echter
  Zielhardware eingehalten;
- alle Sicherheits-, HA-Stable-, HACS- und Hassfest-Gates bleiben grün.

## 5. Teststrategie ohne Einzelfall-Tretmühle

Tests bleiben notwendig, aber sie werden aus Bedeutungen und Eigenschaften
abgeleitet, nicht als Sammlung zufälliger Benutzersätze gepflegt.

### 5.1 Semantic Contract Cases

Eine kleine deklarative Spezifikation beschreibt je Fall nur die Bedeutung:

```yaml
meaning:
  speech_act: command
  action: set
  target: cover
  location: office
  property: position
  value: 50_percent
expect:
  outcome: command
  service: cover.set_cover_position
```

Die sprachlichen Formen werden unabhängig davon erzeugt oder aus einem
gehaltenen Korpus zugespielt. Produktivcode importiert niemals Testformen.

### 5.2 Metamorphe Eigenschaften

Transformationen müssen die Bedeutung erhalten oder definiert verändern:

- Höflichkeit, Füllwörter und Interpunktion ändern den Frame nicht;
- erlaubte Wortstellungsänderungen ändern den Frame nicht;
- Alias und Friendly Name ergeben dasselbe Ziel;
- Ziffer, Zahlwort und zulässiger Bruch ergeben denselben Wert;
- Aktiv/zulässige Wunschform ergeben dieselbe Aktion;
- Negation oder Hypothese entfernt zwingend die Ausführbarkeit;
- Austausch von Raum, Gerät, Wert oder Aktion ändert genau den zugehörigen
  Slot und keinen anderen;
- ein unbekannter bedeutungstragender Modifier kann nie unbemerkt
  verschwinden.

So prüft ein Generator tausende Kombinationen über alle Capability-Klassen,
ohne tausende erwartete Einzelsätze manuell zu schreiben.

### 5.3 Unabhängiges Held-out-Korpus

Ein separates Korpus wird weder aus Produktivregexen noch aus dem
semantischen Katalog generiert. Es enthält unabhängig formulierte:

- kurze und lange gesprochene Befehle;
- Chat-Schreibweisen, Umlaute/ASCII, Tippfehler und typische ASR-Ausgaben;
- Queries, Commands, Automationen und Mehrturn-Dialoge;
- echte Ambiguitäten, unvollständige und fachfremde Äußerungen;
- unterschiedliche Home-Assistant-Welten mit Namenskollisionen und fehlenden
  Capabilities.

Optional können Nutzer lokal und ausdrücklich fehlgeschlagene Äußerungen in
anonymisierter Form exportieren. HomeIntent sammelt oder versendet weiterhin
nichts automatisch.

### 5.4 Release-Metriken

Die endgültigen Schwellen werden nach Phase 0 gegen eine ehrliche Baseline
festgelegt. Mindestanforderungen für jeden Release:

- **Unsafe Action Rate:** exakt 0;
- **Query-to-Action Leakage:** exakt 0;
- **Wrong Target Rate:** exakt 0 in Ambiguitäts- und Kollisionssätzen;
- **Semantic Exact Match:** getrennt nach Capability und Sprachdimension,
  nicht nur als Gesamtdurchschnitt;
- **Clarification Quality:** fehlender beziehungsweise konkurrierender Slot
  korrekt benannt;
- **Held-out Coverage:** darf gegenüber dem letzten Release nicht sinken;
- **Legacy Divergence:** jede Abweichung im Shadow Mode ist klassifiziert,
  bevor ein Legacy-Pfad entfernt wird.

Ein sinnvoller Zielwert nach Aufbau des Held-out-Korpus ist mindestens 97 %
exakter semantischer Treffer für unterstützte, eindeutige In-Domain-Sätze.
Die restlichen Fälle müssen überwiegend gezielte Rückfragen und dürfen keine
falschen Aktionen sein. Der Wert ist ein Ziel, kein vorab behaupteter
Ist-Stand.

## 6. Konkrete Reihenfolge der Pull Requests

1. `UnderstandingOutcome`, Trace und Shadow-Harness ohne Verhaltensänderung.
2. Unabhängiges Eval-Schema, metamorphe Generatoren und Baseline-Bericht.
3. Zentraler Katalog sowie Drift-Checks für doppelte Sprachdefinitionen.
4. Token-/Span-Frontend, Compound/Flexion/Zahl/Einheit und
   korrekturgewichtete Varianten.
5. Interpreter-Pilotmatrix für direkte Kernbefehle und Kernqueries.
6. Gemeinsamer indexierter Name-/Ort-/Capability-Resolver.
7. `conversation.py` auf den einheitlichen Spracheinstieg umstellen; zunächst
   Shadow Mode, danach Core-Pfad autoritativ.
8. Automations-Trigger/-Bedingungen/-Aktionen auf dieselben Frames migrieren.
9. Kalender, Produktivität und Management auf semantische Operationen
   migrieren.
10. Allgemeine Dialogfortsetzung und Slot-Rückfragen konsolidieren.
11. Abgelöste Hassil-/Regex-/Fallbackpfade entfernen.
12. Pi-Benchmark, Strict Typing, Dokumentation und V7-Release-Gate.

Jeder PR muss eine ganze semantische Dimension oder Capability-Matrix
verbessern. Ein PR, dessen Kern nur „diese konkrete Formulierung zusätzlich
erkennen“ lautet, wird nicht akzeptiert, außer es handelt sich nachweislich um
eine isolierte orthografische Normalisierung mit allgemeiner Wirkung.

## 7. Bewusste Nicht-Ziele und spätere Entscheidung

- Kein freier Chatbot und kein Raten außerhalb der unterstützten
  Smart-Home-Semantik.
- Kein probabilistisches Modell darf direkt einen HA-Service bestimmen oder
  die deterministische Capability-/Policy-Prüfung umgehen.
- Kein dauerhaftes Speichern oder automatisches Hochladen von Äußerungen.
- Keine ewige doppelte Architektur aus Legacy und V7.

Falls das unabhängige Korpus nach Abschluss der deterministischen V7-Phasen
auf einem klar messbaren Plateau bleibt, kann separat über einen **optionalen,
lokalen Interpretation Adapter** entschieden werden. Ein solcher kleiner
Parser oder ein lokales Sprachmodell dürfte ausschließlich
`MeaningCandidate`s vorschlagen. Entity-Auflösung, Ambiguität, Validierung,
Policy, Bestätigung und Ausführung blieben vollständig deterministisch. Diese
Option ändert das bisherige Produktversprechen „kein Modell-Download“ und ist
deshalb kein stiller Teil dieser Roadmap, sondern eine spätere bewusste
Produktentscheidung.

## 8. Definition of Done für V7

V7 ist erreicht, wenn:

- jede Äußerung genau einmal durch ein gemeinsames Sprach-Frontend läuft;
- alle Fachpfade dasselbe typisierte Bedeutungsmodell konsumieren;
- ein Synonym, eine Flexions- oder Schreibvariante zentral für alle
  kompatiblen Domänen und Satzformen wirkt;
- Wortstellung und natürliche Hüllen nicht mehr über Parserauswahl
  entscheiden;
- unvollständige und mehrdeutige Bedeutungen slotgenaue Rückfragen erzeugen;
- das unabhängige Held-out-Korpus und metamorphe Capability-Matrizen die
  vereinbarten Gates erfüllen;
- kein Query, unsicherer Satz oder mehrdeutiges Ziel eine Aktion erzeugt;
- die abgelösten parallelen Regex-/Hassil-Sprachpfade entfernt sind;
- Performance und Sicherheit auf echter Home-Assistant-Zielhardware belegt
  sind.
