# Proaktiver HomeIntent-Agent

HomeIntent kann lokale Home-Assistant-Zustände über seine bestehenden,
nativen HA-Automationen beobachten und daraus proaktive Meldungen erzeugen.
Der gesamte Pfad bleibt deterministisch, ohne LLM, Cloud oder zusätzliche
Laufzeitabhängigkeiten.

## Architektur

```text
gesprochene Automationsanweisung
  -> bestehende Automation-AST und Validierung
  -> native HA-Automation in automations.yaml
  -> ha_nlu.proactive_message
  -> AgentEvent (atomare Sidecar-Persistenz)
  -> Deduplizierung, Cooldown und Policy
  -> Push und/oder TTS
  -> mobile_app_notification_action
  -> frischer Entity-Snapshot + Policy + gemeinsamer ServiceCallPlan-Executor
```

HomeIntent betreibt keine zweite State-/Timer-Engine. State-, Numeric-State-,
Zeit-, Sonnen- und Kalenderauslöser bleiben Aufgaben der Home-Assistant-
Automation Engine. Von HomeIntent erzeugte Regeln werden in
`automations.yaml` gespeichert, der HA-Kategorie **HomeIntent** zugeordnet und
sind deshalb unter **Einstellungen > Automationen & Szenen > Automationen**
sichtbar. Dort können sie aktiviert, deaktiviert, bearbeitet und gelöscht
werden. Die Sprachbefehle für Auflisten, Pausieren, Fortsetzen, Ändern und
Löschen bleiben ebenfalls verfügbar.

## Einrichtung

Unter **Einstellungen > Geräte & Dienste > HomeIntent > Konfigurieren**:

- **Proaktives Agentenverhalten aktivieren** schaltet den kompletten
  Agentenpfad ein oder aus. Bei ausgeschaltetem Schalter werden weder neue
  AgentEvents noch Push-/TTS-Ausgaben oder Notification Actions verarbeitet.
- **Ausgabekanäle** erlaubt Push, TTS oder beide Kanäle.
- **Push-Ziele** wählt eine oder mehrere `notify.*`-Entities. Ohne Auswahl
  fällt Push lokal und ohne Interaktionsbuttons auf eine persistente
  Home-Assistant-Benachrichtigung zurück.
- **TTS-Engine** wählt eine `tts.*`-Entity.
- **TTS-Lautsprecher oder Sprachsatelliten** wählt die Media Player für
  `tts.speak`.
- **Standard-Cooldown** verhindert wiederholte Meldungen derselben
  Regelsituation.

Kein Ziel ist im Code fest verdrahtet.

## Regeln per Sprache

Die vorhandene Automationssprache bleibt der Einstieg. Ein verifizierter
Beispielsatz ist:

> Kannst du mich benachrichtigen, wenn die Außentemperatur 28 Grad beträgt?

HomeIntent zeigt wie bisher eine Vorschau und verlangt die Bestätigung zur
Automationserstellung. Nach der Bestätigung wird eine normale HA-Automation
angelegt. Eine zieloffene Benachrichtigungsaktion wird an den Agenten
gebunden und respektiert anschließend die konfigurierten Push-/TTS-Kanäle.

Benachrichtigungen an ein im Satz eindeutig genanntes `notify.*`-Ziel bleiben
bewusst eine direkte Automation. Sie sind eine explizite Benutzeranweisung
und werden nicht nachträglich auf andere Agentenkanäle umgeroutet.

## AgentEvent-Lifecycle

Konkrete Situationen werden in `ha_nlu_agent_events.json` atomar gespeichert.
Mögliche Zustände sind:

- `ACTIVE`
- `NOTIFIED`
- `ACKNOWLEDGED`
- `SNOOZED`
- `RESOLVED`
- `EXPIRED`

Der Deduplizierungsschlüssel kombiniert Regel-ID und beobachtete Entität.
Aktive, zugestellte oder snoozende Situationen erzeugen keine zweite Meldung.
Abgeschlossene Situationen beachten anschließend den konfigurierten Cooldown.

## Push-Aktionen und Snooze

Push-Meldungen enthalten abhängig von der Policy:

- **Ausführen** bei `ASK` und einer validierten vorgeschlagenen Aktion,
- **Ignorieren**,
- **In 30 Minuten erinnern**.

Action IDs tragen nur eine zufällige AgentEvent-ID. Sie enthalten weder
Entity-ID noch Serviceparameter. Beim Ausführen lädt HomeIntent das Event,
beansprucht es atomar gegen Doppelklicks, baut frische Entity-Snapshots und
prüft Ziel und Execution Policy erneut.

Snooze verwendet eine vorhandene, persistente HomeIntent-One-Shot-Automation.
Nach 30 Minuten wird die Situation erneut geprüft. Ist der beobachtete
Zustand beziehungsweise numerische Grenzwert inzwischen verschwunden, wird
keine alte Nachricht wiederholt. Bei einer von HomeIntent erzeugten Regel
wird außerdem die ursprüngliche HA-Automation mit `skip_condition: false`
erneut angestoßen. Damit werden auch deren aktuellen Presence-, Wetter-,
Zeit- und sonstigen Conditions erneut durch Home Assistant geprüft.

Eine über TTS gestellte `ASK`-Frage kann außerdem mit „Ja“ oder „Nein“ in
Assist beantwortet werden. HomeIntent akzeptiert die Kurzantwort nur, wenn
kein normaler Conversation-Dialog offen ist und genau eine unexpired,
tatsächlich per TTS zugestellte Agentenfrage existiert. Bei mehreren offenen
Fragen wird niemals geraten.

## INFORM, ASK und AUTO

- `INFORM` liefert nur die Meldung aus.
- `ASK` bietet eine Aktion an und führt sie erst nach einer gültigen
  Notification Action aus.
- `AUTO` darf nur einen von der normalen Execution Policy erlaubten Plan mit
  niedrigem Risiko ausführen. Mittlere, hohe oder kritische Risiken werden
  automatisch auf `ASK` herabgestuft.

Der öffentliche HA-Action-Editor zeigt `ha_nlu.proactive_message` auch für
fortgeschrittene Regeln an. Vorgeschlagene Aktionen werden durch eine
geschlossene Service-Allowlist geprüft; freie `domain.service`-Ausführung ist
nicht möglich.
