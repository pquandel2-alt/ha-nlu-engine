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
  Name, Alias, Bereich, Etage, Merkmal oder Ordinalzahl.
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

Die öffentliche V7-Grenze ist live. Bereits bewährte Hassil- und
Spezialparser erzeugen während der Migration weiterhin einen Teil der
validierten Payloads hinter dieser Grenze. Sie dürfen das gemeinsame
Frontend und dessen Sicherheitsentscheidung nicht umgehen. Redundante
Gruppen-Semantik wurde entfernt und auf den Semantic Compiler delegiert.

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
Pyright-Strict-Scope bleiben zusätzlich verpflichtend. Performancewerte und
die noch erforderliche Messung auf echter Pi-Hardware stehen in
[`perf/v7-understanding.md`](perf/v7-understanding.md).
