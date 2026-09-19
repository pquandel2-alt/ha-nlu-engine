# HomeIntent – Qualitätscheckliste

HomeIntent ist eine HACS-Custom-Integration und hat deshalb keinen offiziell
von Home Assistant vergebenen Bronze-/Silver-/Gold-/Platinum-Status. Diese
Checkliste orientiert sich trotzdem an der aktuellen Integration Quality Scale
und trennt nachweisbar Erledigtes von offenen Arbeiten. Sie ist keine
Selbstzertifizierung.

Stand: 19. September 2026

## V9 Completion / 4.76.0

- [x] Query-Algebra bleibt einziger Reasoning-Evaluator
- [x] relationale Klassen, Kardinalität, Difference und Discourse-Literalsets
- [x] State Duration nur mit vollständigem `last_changed`-Beleg
- [x] Event-History ohne Recorder niemals aus aktuellem Zustand abgeleitet
- [x] Value-/Property-/relative Temporal-Repair behält nur finalen Slot
- [x] Target Repair bewahrt `REPLACES`-Evidenz und führt nur das neue Ziel aus
- [x] absolute und relative One-shot-Zeitbefehle nutzen die persistente Automation
- [x] 159 unabhängige handgeschriebene V9-OOD-Fälle samt Ergebnis-/Safety-Orakel
- [x] HouseGraph: depth-, visited-node-, frontier- und path-bound
- [x] Query/Ambiguous/Unsupported bleiben ohne ServicePlan
- [x] explizite Recorder-Queries nutzen den vorhandenen History-Adapter;
  nicht belegbare Mengen-History bleibt unsupported

## Abschlussvalidierung 4.76.0

- [x] Gesamtsuite: 3.047 bestanden, 12 übersprungen, 0 fehlgeschlagen
- [x] Coverage: 87,75 Prozent (17.462/19.899 Zeilen)
- [x] Language Safety: 252 bestanden
- [x] Shadow: 3.772 Turns, 0 Divergenzen, 0 Action-Leakage
- [x] vollständiges Pyright: 0 Fehler; CI-identischer Strict-Scope: 0 Fehler
- [x] lokaler Schema-Smoke mit echtem Home Assistant 2025.1.4:
  `HOME_ASSISTANT_AUTOMATION_AND_CALENDAR_SCHEMA_OK`
- [x] unverändertes 5k-Performance-Gate in GitHub Actions: grün; höchster
  gemessener V9-p95 15,57 ms (relationaler Command), produktiver
  Discourse-Follow-up 2,96 ms
- [x] HA-Stable-Container-Smoke, Hassfest und HACS: grün in
  [CI-Lauf 35452062222](https://github.com/pquandel2-alt/ha-nlu-engine/actions/runs/35452062222)

Der zusätzliche lokale 5k-Lauf unter einer Host-Last von etwa 61 auf vier
sichtbaren CPUs war nicht vollständig grün; seine Messwerte werden deshalb
nicht als Release-Gate gewertet. Die Grenzen wurden nicht verändert. Details
und die maßgebliche CI-Messung stehen im Performanceprotokoll.

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
- Lesende und steuernde Freigaben können getrennt werden; zentrale Richtlinien
  begrenzen Zielanzahl, Bestätigungsstufe, zugelassene Benutzer,
  Administratorziele sowie Nicht-Administrator-Aktionen.
- Offene Service- und Automationserstellungsbestätigungen sind an die bekannte
  Home-Assistant-Benutzer-ID gebunden.
- Gemeinsame Engine und Dialogzustände werden typisiert über
  `ConfigEntry.runtime_data` gehalten; direkte Testkonstruktion besitzt einen
  kompatiblen Fallback.
- Config-/Options-Flow und interne Dienste besitzen deutsche und englische
  UI-Übersetzungen.
- Eine eigene Fehlerdiagnose-Anleitung deckt Auswahl, Ortsbezug, Richtlinien,
  Recorder, Benachrichtigungen und Automationspersistenz ab.

## Noch offen vor einer möglichen Aufnahme in Home Assistant Core

- Offizielle Brand-Assets im Home-Assistant-Brands-Repository fehlen.
- Eine belastbare, modulweise gemessene Testabdeckung von mehr als 95 Prozent
  ist noch nicht nachgewiesen. Das ist ausdrücklich keine Aussage über die
  Anzahl der bestehenden Tests.
- Die vielen dynamisch erzeugten Conversation-Antworten sind noch nicht
  vollständig in Home Assistants Übersetzungssystem überführt.
- Strikte Typprüfung ist für die sicherheits- und semantikkritischen Kernmodule
  konfiguriert; der vollständige Repository-Scope läuft zusätzlich im normalen
  Pyright-Modus.
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
Transaktionen sowie nun Ortskontext, Rücknahme, lokale Anpassungen,
Benachrichtigungsautomation und Recorder-Verlauf. Weitere Aufteilungen sollen
jeweils verhaltensneutral und mit Regressionstests erfolgen.
