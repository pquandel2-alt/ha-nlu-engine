# HomeIntent – Qualitätscheckliste

HomeIntent ist eine HACS-Custom-Integration und hat deshalb keinen offiziell
von Home Assistant vergebenen Bronze-/Silver-/Gold-/Platinum-Status. Diese
Checkliste orientiert sich trotzdem an der aktuellen Integration Quality Scale
und trennt nachweisbar Erledigtes von offenen Arbeiten. Sie ist keine
Selbstzertifizierung.

Stand: 24. August 2026

## Bereits erfüllt oder für HomeIntent nicht anwendbar

- Einrichtung und nachträgliche Konfiguration erfolgen über Config Flow und
  Options Flow; eine zweite Installation wird verhindert.
- Entitäten werden dynamisch aus der Assist-Freigabe oder einer bewusst
  gespeicherten Auswahl gelesen; HomeIntent pollt keine Geräte und benötigt
  keine externe Verbindung.
- Eigene Dienste werden beim Laden registriert und beim Entladen entfernt.
- Config Flow, Options Flow, Laden, Entladen, Conversation Agent,
  Automationspersistenz und Dialoge besitzen automatisierte Tests.
- Die README beschreibt Zweck, Installation, Optionen, unterstützte Funktionen,
  Sicherheitsregeln, Beispiele und bekannte Grenzen.
- Es gibt einen benannten Code Owner, ein öffentliches Issue-Tracking und eine
  deklarierte MIT-Lizenz.
- Die Integration verwendet ausschließlich lokale Home-Assistant-Daten und hat
  keine versteckte Laufzeitabhängigkeit oder Cloud-Anmeldung.
- Fehler bei Dateiänderungen werden transaktional zurückgerollt; gleichzeitige
  Änderungen werden über Fingerabdrücke erkannt und nicht überschrieben.
- Diagnoseinformationen sind vorhanden und enthalten keine Äußerungen,
  Entity-IDs oder Zustände.

## Noch offen vor einer möglichen Aufnahme in Home Assistant Core

- Offizielle Brand-Assets im Home-Assistant-Brands-Repository fehlen.
- Die Integration verwendet noch nicht durchgängig `ConfigEntry.runtime_data`;
  langlebige Objekte liegen derzeit auf der Conversation Entity beziehungsweise
  in der Home-Assistant-Datenablage.
- Eine belastbare, modulweise gemessene Testabdeckung von mehr als 95 Prozent
  ist noch nicht nachgewiesen. Das ist ausdrücklich keine Aussage über die
  Anzahl der bestehenden Tests.
- Übersetzbare Fehlermeldungen und eine vollständige Übersetzungsabdeckung für
  alle Nutzertexte fehlen noch.
- Strikte Typprüfung für den gesamten Codebestand ist noch nicht eingerichtet.
- Die offiziellen Regeln zu Discovery, Reauthentication, Firmware-Updates,
  Geräteentitäten und Offline-Verfügbarkeit sind für einen lokalen Conversation
  Agent überwiegend nicht anwendbar; eventuelle Ausnahmen müssten in einem
  Core-Review durch Home Assistant bestätigt werden.
- Eine offizielle Einstufung ist erst im Rahmen einer Aufnahme und Prüfung durch
  das Home-Assistant-Core-Team möglich.

## Architekturfortschritt

Die vormals stark gebündelte Logik wird schrittweise nach Zuständigkeit
getrennt. Eigene Module kapseln inzwischen unter anderem Gradsemantik,
semantische Rückfragedialoge, zusätzliche Gerätedomänen, Kalenderabfragen,
Kalender-Laufzeitzugriffe, Automations-Aktionsänderungen, Metadaten und
Transaktionen. Weitere Aufteilungen sollen jeweils verhaltensneutral und mit
Regressionstests erfolgen.
