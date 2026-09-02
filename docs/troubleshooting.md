# HomeIntent – Fehlerdiagnose

Diese Anleitung behandelt die häufigsten Laufzeitprobleme, ohne dass
Gesprächsinhalte oder private Zustände veröffentlicht werden müssen.

## Ein Satz wird nicht verstanden

1. Prüfen, ob **HA NLU Engine** in der verwendeten Assist-Pipeline ausgewählt
   ist.
2. Prüfen, ob das Ziel für Assist freigegeben oder in den HomeIntent-Optionen
   ausgewählt ist.
3. Friendly Name, Bereich, Etage, Geräteklasse und Aliase in Home Assistant
   prüfen.
4. Bei einer festen HomeIntent-Auswahl beachten, dass neue Entitäten nicht
   automatisch ergänzt werden.
5. HomeIntent nach einer Optionsänderung neu laden.

HomeIntent führt bei Mehrdeutigkeit bewusst nichts aus. Eigene Aliasregeln
haben das Format `gesprochener Name = domain.entity` und dürfen nicht auf
mehrere Ziele zeigen.

## „Hier“ findet keinen Raum

Die verwendete Assist-Anfrage muss eine `device_id` oder `satellite_id`
liefern. Das zugehörige Gerät beziehungsweise die Satellitenentität muss in
Home Assistant einem Bereich zugeordnet sein. Ohne diese Information rät
HomeIntent keinen Raum.

## Ein Befehl wird wegen einer Richtlinie abgelehnt

In den Integrationsoptionen prüfen:

- Nur-Lesen-Entitäten,
- nur administrativ steuerbare Entitäten,
- erlaubte Steuerungsbenutzer,
- maximale Zielanzahl,
- Bestätigungsstufe und
- Regeln für Nicht-Administratoren.

Eine leere Benutzerliste bedeutet „alle Benutzer“. Sobald mindestens ein
Benutzer gewählt ist, benötigen steuernde Anfragen eine passende
Home-Assistant-Benutzer-ID.

## Eine Benachrichtigungsautomation erreicht keine Person

„Mich benachrichtigen“ erzeugt eine lokale persistente Home-Assistant-
Benachrichtigung. Für einen Namen wie „Philipp“ muss genau eine freigegebene
`notify.*`-Entität über Friendly Name oder Alias passen. Ohne eindeutiges
Notify-Ziel bleibt die sichere lokale Benachrichtigung erhalten.

## Verlaufsfragen liefern keine Daten

Recorder muss aktiviert sein und die betreffende Entität aufzeichnen.
Numerische Mittelwerte, Minima, Maxima und Veränderungen benötigen passende
Langzeitstatistiken. „Wie oft“ und „wie lange“ lesen die Zustandsfolge aus der
Recorder-Historie. Fehlen Daten, ersetzt HomeIntent sie nicht durch den
aktuellen Zustand.

## Eine Automation wurde bestätigt, läuft aber nicht

1. In **Einstellungen → Automationen & Szenen** nach der Kategorie
   **Homeintent** suchen.
2. Prüfen, ob die Automation aktiviert ist und der erwartete Trigger in der
   Ablaufverfolgung erscheint.
3. Nach einem HACS-Update Home Assistant neu starten; bei großen
   Versionssprüngen die Integration einmal neu laden.
4. Home-Assistant-Protokolle nach `ha_nlu`, `automation.reload` oder einem
   Konflikt mit `automations.yaml` durchsuchen.

HomeIntent überschreibt eine gleichzeitig im UI geänderte Datei nicht blind.
Ein erkannter Dateikonflikt wird abgebrochen und protokolliert.

## Datenschutzfreundliche Diagnose

Unter der HomeIntent-Integration kann eine Diagnose heruntergeladen werden.
Sie enthält Zähler und Richtlinieneinstellungen, aber keine Äußerungen,
Entity-IDs oder Zustände. Für einen Fehlerbericht sind zusätzlich die
Home-Assistant-Version, HomeIntent-Version, genaue Uhrzeit und der relevante
Protokollausschnitt hilfreich.

## Gedächtnis oder Routinen reagieren nicht

Gedächtnis und Routineerkennung sind standardmäßig deaktiviert. Beide
Schalter befinden sich in den Integrationsoptionen. Persönliche Präferenzen
benötigen eine von Assist übermittelte Benutzer-ID und eine ausdrückliche
Ja/Nein-Bestätigung. HomeIntent speichert keine beiläufige Aussage.

## AUTO wird nur als ASK angeboten

Das ist die sichere Normalform. Prüfen, ob AUTO global aktiviert ist, jede
Ziel-ID in der AUTO-Allowlist steht, der frische Zustand verfügbar ist und die
Aktion LOW-Risk sowie reversibel ist. Cover, Schloss, Alarm und vergleichbare
höhere Risiken werden nicht durch Routinewissen zu AUTO.

## Proaktive Ereignisregeln bleiben still

Mindestens eine Ereigniskategorie muss explizit eingetragen sein. Ruhezeiten
unterdrücken TTS, nicht jedoch konfigurierte kritische Kanäle. Ein veralteter,
unbekannter oder bereits deduplizierter Zustand erzeugt keine zweite Ausgabe.
