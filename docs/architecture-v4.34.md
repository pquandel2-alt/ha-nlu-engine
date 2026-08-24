# HomeIntent 4.34 – Erweiterungswelle

Version 4.34 verbreitert die vorhandene semantische Architektur, ohne ein LLM
oder einen zweiten Resolver einzuführen.

## Gemeinsamer Geräte-Scope und Sicherheit

`entity_scope.py` löst explizite Entitäten, Bereiche, Etagen und homogene
„alle“-Gruppen unabhängig von der Wortreihenfolge auf. Zusatzdomänen verwenden
diese Schicht für Gruppenaktionen und Zustandsabfragen. `risk.py` klassifiziert
konkrete Service-Pläne zentral anhand von Dienst, Domäne, Geräteklasse und
Zielanzahl. Hochriskante Aktionen erreichen Home Assistant erst nach einem
Ja/Nein-Dialog.

`semantic_dialog.py` vervollständigt fehlende Werte nicht mehr nur für
Thermostate. Luftfeuchtigkeit, Warmwasser, Zahlenhelfer und Auswahloptionen
verwenden denselben typisierten Pending-Dialog.

## Kalender

Kalenderabfragen unterstützen freie Zeitfenster. Mutationstreffer bleiben bei
Mehrdeutigkeit im Gesprächskontext und können anschließend gewählt werden.
Datum, Uhrzeit, Titel und Dauer vorhandener Termine lassen sich – abhängig von
`UPDATE_EVENT` – nach Vorschau und Bestätigung ändern. Bei wiederkehrenden
Ereignissen wird der RFC-5545-Scope `this`, `all` oder `THISANDFUTURE`
ausdrücklich abgefragt. Neue wiederkehrende Serien bleiben ausgeschlossen, da
der öffentliche HA-Dienst `calendar.create_event` dafür kein portables Feld
bereitstellt.

## Automationen

Das `AutomationModel` trägt optionale Trigger-IDs und native Kalendertrigger.
Der Generator bildet außerdem strukturierte Wartebedingungen sowie
`if/then/else` in natives Home-Assistant-YAML ab. Alternative Auslöser mit
„oder wenn“ bleiben als mehrere Trigger erhalten.

Schreibende Verwaltungsaktionen werden bestätigt. Neben dem bestehenden
Absturzjournal führt der Executor einen auf zehn Einträge begrenzten
Versionsverlauf, über den die letzte abgeschlossene HomeIntent-Änderung
transaktional zurückgenommen werden kann.

## Integration

Engine und Dialogspeicher gehören nun zur typisierten `ConfigEntry.runtime_data`.
Deutsche UI-Übersetzungen, lokale Brand-Dateien und eine schrittweise
Pyright-Konfiguration bereiten weitere Quality-Scale-Arbeit vor. Die offizielle
Aufnahme von Brand-Assets oder der Integration selbst bleibt ein externer
Review-Schritt.
