# Architekturstand 4.22

Version 4.22 erweitert HomeIntent in vier getrennten Bereichen, ohne die
zentrale Regel zu verändern: Parsing und Auflösung erzeugen strukturierte
Modelle; nur validierte Modelle dürfen Home Assistant lesen oder verändern.

## Automationspersistenz

`AutomationExecutor` serialisiert eigene Änderungen weiterhin über eine pro
Home-Assistant-Instanz geteilte Sperre. Zusätzlich wird die gelesene
`automations.yaml` als Byte-Snapshot mit SHA-256-Fingerabdruck erfasst. Direkt
vor dem atomaren Ersetzen muss der Fingerabdruck noch übereinstimmen. Eine
externe Änderung führt zu `ConcurrentAutomationUpdateError` und wird nicht
überschrieben.

Vor einer Mutation speichert `AutomationTransactionJournal` den alten
Dateiinhalt und den erwarteten Fingerabdruck. Nach dem Schreiben enthält das
Journal auch den neuen Fingerabdruck. Beim Start darf eine unterbrochene
Transaktion nur zurückgerollt werden, wenn die aktuelle Datei noch dem von
HomeIntent geschriebenen Stand entspricht. Andernfalls bleibt sie unverändert,
damit nachträgliche Änderungen von Home Assistant oder dem Benutzer erhalten
bleiben.

Der anschließende Startabgleich entfernt Metadaten ohne zugehörige Automation
und repariert die Kategoriezuordnung bekannter HomeIntent-Automationen. Erst
danach werden verpasste, datumsgebundene Einmal-Aufträge bereinigt.

## Zeitmodelle

Relative Dauern und kalendarische Angaben bleiben getrennte Parserpfade:

- `relative_time_command_parser.py` liefert Sekunden bis Stunden und
  zusammengesetzte Dauern.
- `scheduled_time_command_parser.py` liefert `CalendarSchedule` für relative
  Tage, Wochentage und konkrete Datumsangaben.
- `resolve_pending_schedule()` berechnet den absoluten Termin erst bei der
  Bestätigung in der lokalen Home-Assistant-Zeitzone.

Das resultierende `AutomationModel` enthält den absoluten Zeitpunkt. Der
Generator kombiniert einen Uhrzeit-Trigger mit einer Datumsbedingung. Dadurch
wird ein verpasster Einmal-Termin nicht am nächsten Tag ausgeführt.

## Automationsverwaltung

`automation_management.py` erkennt reine Verwaltungsanfragen unabhängig vom
großen Conversation-Router. Die Conversation-Schicht liest dafür
`AutomationSummary`-Objekte und übergibt schreibende Änderungen wieder an den
Executor. Mehrere Treffer werden nie über ihre Reihenfolge aufgelöst.

Run-begrenzte Automationen speichern `max_runs` und `run_count` in den
Metadaten. Nach jeder erfolgreichen Ausführung ruft die generierte Automation
`ha_nlu.record_automation_run` auf. Beim Grenzwert entfernt der Executor sie
über denselben transaktionalen Löschpfad.

## Neue Gerätedomänen

`device_control.py` kapselt die direkten Kernaktionen für `climate`,
`media_player`, `vacuum`, `scene` und `lock`. Quellen, Betriebsmodi und andere
fähigkeitsabhängige Parameter werden gegen den aktuellen WorldModel-Zustand
validiert. Entriegeln und Garagentorbewegungen erzeugen zunächst eine
`PendingServiceConfirmation` und werden erst nach ausdrücklichem Ja ausgeführt.

Diese neuen Module sind zugleich der erste verhaltensneutrale Schritt zur
weiteren Zerlegung von `engine.py`, `conversation.py` und `parsers.py` nach
Zuständigkeiten.
