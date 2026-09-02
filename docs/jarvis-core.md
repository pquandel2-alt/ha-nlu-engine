# Lokaler Agentenkern

Stand: 1. September 2026

HomeIntent besitzt einen lokalen, deterministischen Agentenkern. Er ist kein
freier Chatbot: Er verarbeitet nur typisierte Haus-, Dialog-, Gedächtnis-,
Ereignis- und Planungsbedeutungen. Keine dieser Schichten darf selbst einen
Home-Assistant-Dienst aufrufen.

## Gemeinsame Fakten und Hausgraph

`WorldModel` bleibt die pro Turn frisch erzeugte Sicht auf Home Assistant.
`HouseGraph` projiziert genau diese stabilen Entity-, Device-, Area- und
Floor-IDs in typisierte Knoten und Beziehungen. Konfigurierbar sind unter
anderem Nachbarschaft, über/unter, Zugehörigkeit, Beobachtung, Einfluss,
bevorzugtes Gerät und Sprachursprung.

Jede Beziehung trägt Herkunft und Vertrauensklasse. Direkt beobachtete,
konfigurierte, bestätigte, abgeleitete und statistische Aussagen bleiben
unterscheidbar. Eine statistische Beziehung ist ausdrücklich kein sicherer
Fakt und wird bei `asserted_only` nicht zurückgegeben.

## Gedächtnis

Das dauerhafte Gedächtnis ist standardmäßig aus. Nach Aktivierung speichert
`MemoryStore` atomar in `.storage/ha_nlu_memory.sqlite3`. SQLite-Migrationen
werden über `PRAGMA user_version` versioniert; WAL schützt Transaktionen bei
einem Prozessabbruch.

Jeder Eintrag enthält stabile ID, Typ, strukturierten JSON-Inhalt, Herkunft,
Erstellungs- und Änderungszeit, optionales Ablaufdatum, Person,
Vertrauensklasse und kontrollierten Löschzeitpunkt. Vollständige
Sprachtranskripte werden vom Store abgelehnt. Arbeitsgedächtnis ist pro
Conversation im RAM und wird nach Neustart nicht wiederbelebt.

Persönliche Präferenzen brauchen eine authentifizierte Person und eine
explizite Ja/Nein-Bestätigung. Unterstützt sind Auflisten, Korrigieren,
einzelnes Vergessen, Löschen pro Person, Reset, Aufbewahrungsregeln und ein
redigierter Export. Der Export enthält nur Zähler, niemals Inhalt oder IDs.

## Dialogmanager

Der zentrale `DialogManager` verwaltet typisierte Aufgaben mit Ablaufzeit,
Benutzerbindung und fester Priorität. Sicherheitsbestätigungen liegen vor
normalen Auswahlen und Ergänzungen. Eine Ordinalauswahl ist nur innerhalb der
Kandidatenliste gültig; eine unklare Kurzantwort lässt den Dialog offen.
Vollständige neue Befehle können einen optionalen Gedächtnisdialog ersetzen.
„Was hast du verstanden?“ und „Warum fragst du?“ lesen ausschließlich den
strukturierten Taskzustand.

„Mach es hier gemütlicher“ wird nur dann zu einem konkreten ASK-Vorschlag,
wenn genau eine bestätigte, personengebundene Präferenz auf ein aktuelles,
fähiges Gerät passt. Ein eindeutiges Ja lädt einen frischen Snapshot und
durchläuft geschlossenen Validator, Policy und gemeinsamen Executor. Ohne
eindeutige Präferenz bleibt es bei einer Rückfrage ohne Aktion. Eine
nachträgliche Zielkorrektur nimmt eine sicher reversible vorige Aktion zuerst
policygebunden zurück; schlägt das fehl, wird das neue Ziel nicht geschaltet.

## Ereignisse, Routinen und Proaktivität

`SituationRuntime` konsumiert Home Assistants `state_changed`-Bus. Der
Listener wird mit dem Config Entry registriert und beim Unload durch denselben
Unsubscribe-Callback entfernt. Ereignisse werden mit stabilem Ziel, altem und
neuem semantischem Zustand, Zeit, Bereich, Anwesenheit, Modus, Quelle und
Qualität normalisiert.

Ereigniskategorien müssen ausdrücklich konfiguriert werden. Die eingebauten
Regeln erkennen Sicherheitsalarm, Geräteausfall, nächtliche Öffnung bei
Abwesenheit, Fenster plus Heizung, Licht im unbesetzten Bereich und
konfigurierbar lange Zustände. Vor jedem AgentEvent läuft die zentrale
proaktive Entscheidungsreihenfolge; nur ein eindeutig validierbarer,
policyerlaubter Vorschlag kann ASK werden. Die Schicht führt selbst nichts
aus.

Routineerkennung ist standardmäßig aus. Sie nutzt Häufigkeiten nach Stunde
und Wochentag, Zustandsdauern, Mediane, Sequenzen, Mindestbeobachtungszahl,
Cooldown und Hysterese. Jede Bewertung nennt Beobachtung, Normalbereich,
Anzahl, Relevanz, Confidence und Unsicherheit. Wiederholung allein gewährt
niemals AUTO.

Bei einer nächtlichen Öffnung während Abwesenheit enthält die Begründung
Sensorqualität und Anwesenheit. Ist die Routineerkennung aktiv, kommen
Normalbereich, Beobachtungszahl und der ausdrückliche Vermutungsstatus hinzu.

## Antwortplanung

`ResponsePlan` trennt Dialogakt, Ergebnis, Dringlichkeit, Sicherheitsstufe,
Kürze, Ansprache, Betriebsmodus, Banter und TTS-Eignung. Die deutsche
Realisierung besitzt die Stile `neutral`, `precise` und `jarvis`. Rauch, CO,
Wasser, Einbruch, Alarm und medizinisch wirkende Kategorien unterdrücken Stil
und Banter vollständig. Erklärungen dürfen nur übergebene, im Weltmodell
belegte Fakten ausgeben.

## Ziel- und Mehrschrittplaner

Der Planer materialisiert `Goal`, Checks und bekannte `ServiceCallPlan`-
Aktionen vollständig vor Ausführung. Jeder Schritt besitzt Preconditions,
Effects, Invariants, Risiko, Reversibilität, Dependencies, Verification und
optional eine Compensation. Unbekannte Ziele oder fehlende Capabilities
brechen die Materialisierung ab.

Der `PlanExecutor` lädt vor jedem Check und jedem Aktionsschritt einen frischen
Snapshot. Die Ausführungs-Callback muss der gemeinsame HomeIntent-Executor
sein; der Planer hat keinen eigenen HA-Schreibpfad. Nach jedem Schritt wird
die Wirkung geprüft. Bei Fehler stoppt der Plan, und nur ausdrücklich
reversible, bereits ausgeführte Schritte werden in umgekehrter Reihenfolge
erneut policygebunden kompensiert.

Das geschlossene Szenario „Wenn niemand mehr unten ist …“ bindet genau einen
konfigurierten Anwesenheitssensor, die abschaltbaren Geräte derselben Etage
und genau ein Flurlicht. Die Vorschau schaltet zunächst die übrigen Geräte
aus, wartet zehn Minuten und schaltet dann das Flurlicht aus. Mehrdeutige
Sensoren oder Flurlichter erzeugen keine Automation.

## Adapter

Alle Adapter sind opt-in und read-only:

- Frigate nimmt nur vorhandene Objekt-, Paket- und Personenmetadaten an;
  Erkennungen bleiben Schätzungen.
- Der Dokumentindex ist auf ein freigegebenes Stammverzeichnis, UTF-8-TXT,
  Markdown und begrenzte PDF-Textoperatoren, Dateizahl und Dateigröße
  beschränkt. Symlink-Ausbrüche werden verworfen. Treffer kommen mit
  relativer Quelle aus SQLite FTS5. Verschlüsselte oder reine Scan-PDFs
  werden nicht per OCR interpretiert.
- Der HA-Quellenadapter akzeptiert nur strukturierte Daten aus Kalender,
  Wetter, Recorder, Logbook, Energie, Anwesenheit, Todo und Timer.

Die Adapter erzeugen Evidenz, niemals einen Serviceplan oder eine erfundene
Zusammenfassung.

## Bewusste Grenzen

Deterministisch unterstützt werden nur katalogisierte Smart-Home-Bedeutungen,
konfigurierte Beziehungen und bekannte Planaufgaben. Offene Wissensfragen,
freie Zusammenfassungen, beliebige Prozeduren und Gespräche außerhalb des
Haushaltsbereichs sind ohne LLM nicht möglich. HomeIntent verspricht deshalb
nicht „versteht alles“.
