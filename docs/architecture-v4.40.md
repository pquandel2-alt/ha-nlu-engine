# Architektur 4.40: domänenübergreifende Kompositionalität

Version 4.40 macht die bisher nur teilweise sichtbare Grenze zwischen dem
semantischen Compiler und domänenspezifischen Direkt-Routern messbar und
verkleinert sie.

## Gemeinsames Operationsregister

`nlu/domain_operations.py` ist HA-frei und enthält keine Satzvorlagen. Das
Modul ordnet unabhängige Bedeutungsbausteine zu:

```text
Geräteausdruck → Domäne
Aktionsausdruck → abstrakte Aktion
Domäne + Aktion → internes Intent
```

Erst `service_call.py` übersetzt das validierte Intent in einen konkreten
Home-Assistant-Service. Dadurch bleiben Spracherkennung und Ausführung
getrennt.

Das Register wird von Lexikon, semantischem Compiler, Sprechakt-Erkennung,
Entity-Scope und Dialogergänzung verwendet. Die jeweiligen Router begrenzen
weiterhin explizit, welche Teilmenge der Domänen sie übernehmen. Das schützt
die etablierte Priorität von Zustandsfragen, Automationen und Kernbefehlen.

## Sicherheitsgrenzen

- Eine Domäne/Aktion-Kombination muss explizit registriert sein.
- Ein Ziel muss anhand des aktuellen Entity-Snapshots eindeutig sein.
- Unbekannte bedeutungstragende Wörter führen weiterhin zur Ablehnung.
- Der zentrale Command Validator prüft erlaubte Domänen.
- Ventiloperationen verlangen die passende Capability `OPEN` oder `CLOSE`.
- Die Execution Policy stuft Ventile weiterhin als hohes Risiko ein und
  erzwingt die bestehende Bestätigung.

## Messung

`tests/test_semantic_domain_matrix.py` enthält 2.304 fachlich passende
Formulierungen über neun Domänen. Die gleichen Fälle werden getrennt geprüft:

1. direkt gegen `NluEngine.match()` und damit den semantischen Compiler,
2. über die Live-Reihenfolge aus erweitertem Direct-Control-Router und Engine.

Die Matrix ist Testcode und wird niemals vom Produktivcode importiert. Ein
grünes Ergebnis belegt daher Generalisierung aus gemeinsamen Komponenten und
nicht das Nachschlagen der Testsätze.

Die alten Spezialpfade bleiben in 4.40 für zusätzliche Werte-, Modus- und
Folgedialogfunktionen erhalten. Sie dürfen erst entfallen, wenn entsprechende
Äquivalenzmatrizen auch diese Operationen vollständig abdecken.
