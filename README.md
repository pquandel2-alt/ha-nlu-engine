# HomeIntent

**Lokale, schnelle und deterministische Sprachsteuerung für Home Assistant Assist.**

- Aktuelle Version: **4.20.0**
- Sprache: **Deutsch**
- Installation: **HACS Custom Repository**

## Was ist HomeIntent?

HomeIntent ist ein eigener Conversation Agent für Home Assistant Assist. Die Integration übersetzt deutsche Smart-Home-Sätze in geprüfte Home-Assistant-Befehle, Zustandsabfragen oder echte Automationen.

Anders als ein allgemeines Sprachmodell versucht HomeIntent nicht, beliebige Gespräche zu verstehen. Es konzentriert sich bewusst auf ein kleineres, klar definiertes Problem:

> Einen Smart-Home-Befehl zuverlässig verstehen, das richtige Gerät finden, die gewünschte Aktion prüfen und erst danach Home Assistant steuern.

HomeIntent benötigt dafür:

- keine Cloud-API,
- kein Large Language Model (LLM),
- keine GPU,
- keinen externen Server und
- keine Internetverbindung für die Verarbeitung eines Sprachbefehls.

Die Erkennung basiert auf deutschen Hassil-Grammatiken, strukturierten semantischen Modellen und deterministischen Resolvern. Derselbe Satz führt bei demselben Home-Assistant-Zustand und Gesprächskontext zum selben Ergebnis.

## Warum ein deterministischer Ansatz?

Ein allgemeines LLM kann sehr flexibel formulierte Texte verstehen, sein Ergebnis ist aber nicht zwangsläufig reproduzierbar. Bei einem Smart Home ist Vorhersagbarkeit oft wichtiger als Kreativität: Eine mehrdeutige Anweisung soll nicht versehentlich das falsche Licht, die falsche Rolllade oder eine falsche Automation steuern.

HomeIntent verfolgt daher diese Reihenfolge:

```text
Gesprochener oder geschriebener Satz
                │
                ▼
       Normalisierung und Grammatik
                │
                ▼
       Semantische Bedeutung (AST)
                │
                ▼
     Geräte-, Bereichs- und Kontextauflösung
                │
                ▼
      Fähigkeiten- und Sicherheitsprüfung
                │
                ▼
    Home-Assistant-Service oder Automation
```

Wenn ein Ziel nicht eindeutig aufgelöst werden kann, rät HomeIntent nicht. Der Befehl wird abgelehnt oder es wird – sofern der jeweilige Dialogpfad dies unterstützt – nachgefragt.

## Funktionsumfang

### Direkte Gerätesteuerung

HomeIntent kann aktuell unter anderem folgende Home-Assistant-Domänen verwenden:

| Domäne | Beispiele |
| --- | --- |
| `light` | ein-/ausschalten, dimmen, Helligkeit, Farbe, Farbtemperatur |
| `switch` | ein-/ausschalten, umschalten |
| `fan` | ein-/ausschalten, Geschwindigkeit setzen oder verändern |
| `cover` | öffnen, schließen, Position in Prozent setzen |
| `script` | Home-Assistant-Skripte starten |
| `sensor` | Werte und Vergleiche abfragen (nur lesend) |
| `binary_sensor` | Zustände abfragen, zum Beispiel Fenster oder Türen (nur lesend) |

Beispiele:

```text
Mach das Wohnzimmerlicht an.
Schalte alle Lichter im Erdgeschoss aus.
Stell das Wohnzimmerlicht auf 40 Prozent.
Mach das Licht blau.
Fahre die Rolllade im Wohnzimmer auf 30 Prozent.
Stelle den Ventilator auf Stufe 3.
Starte Gute Nacht.
```

### Bereiche, Etagen und mehrere Geräte

HomeIntent berücksichtigt nicht nur den Anzeigenamen einer Entität, sondern auch:

- Entity-ID und Friendly Name,
- in Home Assistant hinterlegte Aliase,
- Bereich und Bereichs-Aliase,
- Etage,
- Domäne und Geräteklasse,
- unterstützte Fähigkeiten,
- Quantifizierer wie „alle“, „beide“ oder Anzahlen,
- Ausschlüsse mit „außer“ sowie
- den bisherigen Gesprächskontext.

Beispiele:

```text
Mach oben die Lichter aus.
Fahre beide Rollläden im Wohnzimmer hoch.
Mach alle Lichter aus außer der Stehlampe.
Mach die drei Lampen an.
```

### Zustands- und Vergleichsabfragen

Abfragen sind lesend aufgebaut und führen keinen Home-Assistant-Service aus.

```text
Welche Fenster sind offen?
Gibt es offene Fenster im Keller?
Ist das Schlafzimmerfenster geöffnet?
Wie warm ist es im Wohnzimmer?
Welche Lichter sind heller als 50 Prozent?
Warum ist das Küchenlicht an?
```

Bei der „Warum“-Frage nennt HomeIntent passende Automationen als mögliche Ursache. Es behauptet nicht, einen vollständigen kausalen Ablauf beweisen zu können.

### Gesprächskontext und Rückfragen

HomeIntent speichert Kontext pro Assist-Konversation. Dadurch sind kurze Folgesätze möglich:

```text
Du: Schalte das Wohnzimmerlicht ein.
Assist: Wohnzimmerlicht eingeschaltet.
Du: Und jetzt wieder aus.
```

Auch Pronomen und bereichsbezogene Folgefragen können – innerhalb der unterstützten Grammatik – auf zuvor aufgelöste Entitäten verweisen:

```text
Du: Wie warm ist es im Wohnzimmer?
Du: Und in der Küche?
```

### Mehrteilige Befehle

Mehrere direkte Aktionen können nacheinander formuliert werden. Vor der Ausführung werden alle Teilbefehle aufgelöst und validiert.

```text
Mach die Wohnzimmerlampe an und fahre den Rollladen Büro hoch.
```

## Natürlichsprachige Automationen

HomeIntent kann Automationen nicht nur verstehen, sondern als echte Home-Assistant-Automationen anlegen, abfragen, aktivieren, deaktivieren und löschen.

### Dauerhafte Automation erstellen

```text
Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.
```

Der Ablauf ist absichtlich zweistufig:

1. HomeIntent zerlegt den Satz in Trigger, optionale Bedingungen und Aktionen.
2. Entitäten, Bereiche, Fähigkeiten, Werte und logische Struktur werden validiert.
3. Assist zeigt eine verständliche Vorschau.
4. Erst nach einer ausdrücklichen Bestätigung mit „Ja“ wird die Automation geschrieben.
5. HomeIntent ergänzt `automations.yaml` atomar und ruft `automation.reload` auf.
6. Die neue Automation erscheint in Home Assistant und erhält die Kategorie **Homeintent**.

Ein „Nein“ bricht die Erstellung ab, ohne etwas zu speichern.

### Bedingungen

Trigger können mit Bedingungen kombiniert werden:

```text
Wenn das Küchenfenster geöffnet wird und es nach 18 Uhr ist, schalte das Küchenlicht ein.
Wenn das Küchenfenster geöffnet wird und niemand zuhause ist, schalte das Küchenlicht ein.
Wenn das Küchenfenster geöffnet wird und Samstag ist, schalte das Küchenlicht ein.
```

Die zentrale Struktur dafür ist das `AutomationModel`: ein validierter Syntaxbaum aus Triggern, Bedingungen und Aktionen. Erst der HA-Automation-Generator übersetzt dieses Modell in Home-Assistant-YAML.

### Einmalige Automation

Mit „einmalig“ oder „nur einmal“ wird eine Automation nach ihrer ersten erfolgreichen Ausführung automatisch wieder gelöscht:

```text
Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht einmalig ein.
Wenn es 20 Uhr ist, schalte das Küchenlicht nur einmal ein.
```

Technisch erhält die Automation als letzten Schritt einen internen Aufruf von `ha_nlu.delete_automation`. Dieser entfernt genau die betreffende Automation aus `automations.yaml` und lädt die Automationen neu.

### Zeitversetzter Einmal-Befehl

Relative Zeitangaben erzeugen ebenfalls eine einmalige Automation:

```text
Fahre in 5 Minuten die Wohnzimmer Rolllade auf 30 Prozent.
Fahre in 30 Sekunden die Wohnzimmer Rolllade auf 30 Prozent.
In einer Stunde schalte das Küchenlicht ein.
```

HomeIntent berechnet aus der lokalen Home-Assistant-Zeit einen absoluten Zeitpunkt mit Sekundenpräzision. Minuten-, Stunden- und Tageswechsel sowie Sommerzeitwechsel werden berücksichtigt. Nach der Aktion löscht sich die Automation selbst.

Das ist **keine täglich wiederkehrende Automation**. Der intern verwendete Zeittrigger wäre zwar grundsätzlich täglich, wird aber nach dem ersten Auslösen durch die Self-Delete-Aktion entfernt.

### Automationen verwalten

```text
Welche Automationen gibt es?
Was schaltet das Küchenlicht?
Warum ist das Küchenlicht an?
Deaktiviere die Automation für Küchenlicht.
Aktiviere die Automation für Küchenlicht.
Lösche die Automation für Küchenlicht.
```

Löschen erfordert eine Bestätigung. Aktivieren und Deaktivieren ändern den dauerhaften `initial_state` in `automations.yaml`; die Einstellung bleibt daher auch nach einem Reload oder Neustart erhalten.

## Installation über HACS

HomeIntent wird aktuell als benutzerdefiniertes HACS-Repository installiert. Das Vorgehen entspricht der offiziellen Anleitung für [benutzerdefinierte HACS-Repositories](https://hacs.xyz/docs/faq/custom_repositories/).

1. Öffne **HACS → Integrationen**.
2. Öffne das Menü oben rechts und wähle **Benutzerdefinierte Repositories**.
3. Trage dieses Repository ein:

   ```text
   https://github.com/pquandel2-alt/ha-nlu-engine
   ```

4. Wähle als Typ **Integration**.
5. Suche anschließend in HACS nach **HA NLU Engine** und installiere die aktuelle Version.
6. Starte Home Assistant neu.
7. Öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen** und füge **HA NLU Engine** hinzu.

## Einrichtung in Assist

Nach der Installation steht **HA NLU Engine** als Conversation Agent zur Verfügung.

1. Öffne die Einstellungen deines Sprachassistenten beziehungsweise deiner Assist-Pipeline.
2. Wähle **HA NLU Engine** als Conversation Agent.
3. Prüfe unter den Assist-/Entitätseinstellungen, welche Entitäten für Assist freigegeben sind.

Standardmäßig verwendet HomeIntent bei jedem Gesprächszug dynamisch die aktuell für Assist freigegebenen Entitäten aus den unterstützten Domänen. In den Optionen der Integration kann stattdessen eine feste Entitätsauswahl gespeichert werden.

Für eine zuverlässige Auflösung empfiehlt es sich:

- verständliche und eindeutige Entity-Namen zu vergeben,
- Geräte den richtigen Bereichen und Etagen zuzuordnen,
- sinnvolle Aliase für Entitäten und Bereiche zu hinterlegen und
- nur die tatsächlich per Sprache benötigten Entitäten für Assist freizugeben.

## Kategorie „Homeintent“

Alle ab Version 4.20.0 neu durch HomeIntent erzeugten Automationen werden automatisch der Home-Assistant-Automationskategorie **Homeintent** zugeordnet. Das gilt für:

- dauerhafte Automationen,
- einmalige zustandsbasierte Automationen und
- zeitversetzte Einmal-Automationen.

Existiert die Kategorie bereits mit einer anderen Groß-/Kleinschreibung, wird sie wiederverwendet. Bereits vor Version 4.20.0 angelegte Automationen werden nicht rückwirkend einsortiert.

Die Kategorie dient nur der übersichtlichen Gruppierung in der Automationsansicht. Sie verändert nicht das Ausführungsverhalten.

## Sicherheit und Datenhaltung

### Keine Ausführung bei Mehrdeutigkeit

Wenn mehrere Entitäten gleich gut passen und kein Bereich oder Kontext die Auswahl eindeutig macht, führt HomeIntent nicht einfach die erste gefundene Entität aus.

### Fähigkeiten werden geprüft

Eine Aktion wird nur erzeugt, wenn die Zielentität die erforderliche Funktion unterstützt. Eine Rollladenposition benötigt beispielsweise Positionsunterstützung; eine Farbe wird nur für ein farbfähiges Licht akzeptiert.

### Automationen brauchen eine Bestätigung

Das Erkennen eines Automationssatzes verändert Home Assistant noch nicht. Erst die Bestätigung startet Generator und Executor.

### Transaktionales Schreiben

Beim Erstellen werden `automations.yaml`, der Live-Zustand nach `automation.reload`, die Homeintent-Kategorie und die internen Metadaten aufeinander abgestimmt. Auch Löschen, Aktivieren und Deaktivieren verwenden geschützte Schreib-/Reload-Abläufe. Schlägt ein erforderlicher Schritt fehl, wird die Datei nach Möglichkeit auf den vorherigen Zustand zurückgesetzt.

### Lokal und privat

Die NLU-Verarbeitung läuft innerhalb von Home Assistant. HomeIntent sendet den gesprochenen Text nicht an einen eigenen Cloud-Dienst.

## Bekannte Grenzen

- Die mitgelieferten Grammatiken sind derzeit auf Deutsch ausgelegt.
- HomeIntent ist absichtlich kein Chatbot und versteht nur unterstützte Smart-Home-Strukturen.
- Relative Einmal-Befehle unterstützen aktuell Sekunden, Minuten und Stunden bis maximal 24 Stunden.
- Formulierungen wie „morgen um 8 Uhr“ gehören noch nicht zum relativen Einmal-Befehlspfad.
- Ist Home Assistant beim berechneten Zeitpunkt ausgeschaltet und startet erst danach wieder, kann ein reiner Uhrzeit-Trigger den verpassten Zeitpunkt nicht zuverlässig nachholen. Für solche Fälle ist künftig eine persistente Datum-/Zeitplanung nötig.
- Nicht jeder intern modellierbare Trigger, jede Bedingung oder Aktion besitzt bereits eine sichere Home-Assistant-YAML-Abbildung. Nicht unterstützte Strukturen werden abgelehnt, statt angenähert zu werden.
- Die Qualität der Zielauflösung hängt von sinnvollen Entity-Namen, Bereichen, Geräteklassen, Fähigkeiten und Assist-Freigaben ab.

## Architektur

Die wichtigsten Schichten sind bewusst getrennt:

```text
Conversation Agent
      │
      ├── Direktbefehl / Abfrage
      │       └── Semantic Frame → Resolver → Validator → Service Mapper
      │
      └── Automation
              └── Trigger/Condition/Action Parser
                  → AutomationModel
                  → AutomationValidator
                  → Vorschau und Bestätigung
                  → HA Automation Generator
                  → AutomationExecutor
```

Der Parser führt keine Home-Assistant-Dienste direkt aus. Dadurch können Sprachverständnis, Auflösung, Validierung, Vorschau und Ausführung unabhängig getestet werden.

Weiterführende technische Dokumentation liegt im Verzeichnis [`docs`](docs/).

## Entwicklung und Tests

Mit einer entsprechend vorbereiteten Python-Umgebung kann die komplette Testsuite so ausgeführt werden:

```bash
python -m pytest -q
```

Stand von Version 4.20.0:

```text
1605 passed, 14 skipped
```

Neue Grammatik oder Ausführungslogik sollte immer mit positiven Fällen, Mehrdeutigkeitsfällen, Negativfällen und einem Regressionstest für bestehendes Verhalten ergänzt werden.

## Mitwirken

Beiträge und Fehlermeldungen sind willkommen. Bitte beachte dabei die Grundprinzipien des Projekts:

- deterministisch statt geraten,
- lokal statt cloudabhängig,
- Bedeutung und Ausführung getrennt halten,
- Fähigkeiten und Parameter vor jeder Aktion validieren,
- neue Formulierungen mit Tests absichern und
- bestehendes Verhalten nicht stillschweigend verändern.

Repository: [github.com/pquandel2-alt/ha-nlu-engine](https://github.com/pquandel2-alt/ha-nlu-engine)
