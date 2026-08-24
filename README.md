# HomeIntent

**Lokale, schnelle und deterministische Sprachsteuerung für Home Assistant Assist.**

- Aktuelle Version: **4.31.0**
- Sprache: **Deutsch**
- Installation: **HACS Custom Repository**
- Lizenz: **MIT**

[![HomeIntent in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pquandel2-alt&repository=ha-nlu-engine&category=integration)

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

Die Erkennung kombiniert bewährte deutsche Hassil-Grammatiken mit einem
lokalen symbolischen Sprach-Compiler, strukturierten semantischen Modellen
und deterministischen Resolvern. Der Compiler zerlegt eine Formulierung in
unabhängige Bedeutungsbausteine wie Aktion, Gerätetyp, Ort, Anzahl und Wert.
Dadurch müssen diese Bausteine nicht in einer fest vorgegebenen Reihenfolge
stehen. Derselbe Satz führt bei demselben Home-Assistant-Zustand und
Gesprächskontext trotzdem immer zum selben Ergebnis.

## Warum ein deterministischer Ansatz?

Ein allgemeines LLM kann sehr flexibel formulierte Texte verstehen, sein Ergebnis ist aber nicht zwangsläufig reproduzierbar. Bei einem Smart Home ist Vorhersagbarkeit oft wichtiger als Kreativität: Eine mehrdeutige Anweisung soll nicht versehentlich das falsche Licht, die falsche Rolllade oder eine falsche Automation steuern.

HomeIntent verfolgt daher diese Reihenfolge:

```text
Gesprochener oder geschriebener Satz
                │
                ▼
 Normalisierung, Grammatik und semantischer Compiler
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

Der semantische Compiler ist kein eingebautes Sprachmodell. Seit Version
4.27 zerlegt ein gemeinsames spanbasiertes Lexikon jeden Satz in
wiederverwendbare Bedeutungen. Jeder Treffer behält seine Position im Text;
Mehrwortausdrücke, Konflikte und nicht erklärte bedeutungstragende Wörter
können dadurch geprüft werden. Query und Befehl verwenden denselben einmalig
erzeugten Analysepass. Die Interpretation wird anschließend gegen die
tatsächlich in Home Assistant vorhandenen Geräte, Bereiche, Etagen und
Fähigkeiten geprüft. So entsteht flexible Satzstellung ohne Cloud-Latenz,
Modell-Download oder hohe Hardware-Anforderungen. Alte Satzgrammatiken bleiben
als schneller und kompatibler Pfad erhalten.

Dabei werden nicht alle denkbaren deutschen Gespräche vorgetäuscht. Erkennt
HomeIntent einen wichtigen Zusatz nicht oder ergeben die Bausteine mehrere
widersprüchliche Bedeutungen, führt es keine Aktion aus. Ein neuer Ausdruck
erweitert das zentrale Lexikon für alle zulässigen Satzstellungen und muss
nicht als vollständiger Satz in vielen Varianten eingetragen werden.

## Aktuelles Sprachverständnis

HomeIntent wertet einen Satz nicht mehr nur entlang einzelner fest hinterlegter
Formulierungen aus. Der gemeinsame semantische Analysepass erkennt unter
anderem Aktion, Gerätetyp, Zustand, Ort, Etage, Menge, Messgröße,
Vergleichsoperator und Wert als getrennte Bedeutungsbausteine. Danach werden
diese Bausteine fachlich geprüft und mit dem aktuellen Home-Assistant-Modell
abgeglichen.

Dadurch darf sich die Reihenfolge vieler Satzteile ändern, ohne dass für jede
Variante ein eigener vollständiger Beispielsatz programmiert werden muss:

```text
Fahre alle Rollläden im Erdgeschoss hoch.
Im Erdgeschoss bitte alle Rollläden hochfahren.
Nach oben fahren sollen im Erdgeschoss alle Rollläden.

Sind im Erdgeschoss offene Fenster?
Offene Fenster, gibt es die im Erdgeschoss?
Welche Fenster im Erdgeschoss sind noch geöffnet?

Welche Lichter sind heller als 50 Prozent?
Mindestens 50 Prozent, welche Lichter sind das?
Im Wohnzimmer heller als 50 Prozent: Welche Lichter gibt es?

Flurlicht bitte an.
Ich möchte, dass das Bürolicht ausgeschaltet wird.
Komplett hochfahren soll der Rollladen Büro.
Den Rollladen Büro würd ich gern halb runterfahren.
```

HomeIntent trennt dafür die eigentliche Bedeutung von ihrer sprachlichen
Verpackung. Höflichkeit, Wunsch- und Passivformen, umgangssprachliche
Verbendungen sowie elliptische Kurzbefehle werden als Satzhülle behandelt;
Aktion, Ziel, Ort und Wert bleiben dieselben geprüften semantischen Rollen.
Zusammengesetzte Verben wie „hochfahren“ und Wörter wie „oben“ innerhalb eines
echten Gerätenamens werden anhand des Registry-Kontexts unterschieden.

Die gemeinsame Auswertung verbessert mehrere Bereiche gleichzeitig:

| Bereich | Verbesserung |
| --- | --- |
| Befehle | Aktion, Ziel, Bereich oder Etage, Menge und Wert können flexibler angeordnet werden. |
| Zustandsfragen | Einzelne, mehrere, alle, irgendeine oder keine passende Entität können abgefragt werden. |
| Messwerte | Temperatur, Luftfeuchtigkeit, Batterie, Leistung, Energie und Helligkeit verwenden dieselbe Orts- und Vergleichslogik. |
| Vergleiche | Ausdrücke wie „über“, „unter“, „mindestens“, „höchstens“, „heller“ und „dunkler“ werden unabhängig von ihrer Position erkannt. |
| Automationen | Zustandsauslöser und Zustandsbedingungen verwenden denselben geprüften Predicate-Compiler. |
| Folgefragen | Gerät, Raum, Etage und abgefragte Eigenschaft können als Dialogfokus sicher weiterverwendet werden. |
| Gemischte Sätze | Eine Aktion und eine unabhängige Zustandsfrage können gemeinsam vollständig validiert werden. Beziehen sich beide auf dasselbe Gerät, wird die Kombination wegen eines möglicherweise veralteten Abfragewerts abgelehnt. |
| Sicherheit | Widersprüche, unbekannte wichtige Zusätze und fachlich unpassende Einheiten werden abgelehnt statt geraten. |

Beispielsweise kann nach einer Temperaturabfrage eine verkürzte Anweisung den
sicheren Dialogkontext nutzen:

```text
Du: Wie hoch ist die Temperatur im Erdgeschoss?
Assist: 21,6 Grad.
Du: Kannst du die Temperatur auf 22 Grad erhöhen?
Assist: Erdgeschoss Heizung auf 22 Grad gestellt.
```

Auch dabei bleibt HomeIntent vollständig lokal und deterministisch. Es wird
kein Text an einen LLM-Anbieter gesendet, kein Modell heruntergeladen und keine
leistungsstarke Spezialhardware benötigt. Die semantische Analyse braucht in
den Projektmessungen nur wenige Millisekunden, selbst wenn das World Model
mehrere tausend Entitäten enthält.

Diese Flexibilität hat bewusst eine Sicherheitsgrenze: HomeIntent ist kein
allgemeiner Chatbot und behauptet nicht, jeden beliebigen deutschen Satz zu
verstehen. Fehlt eine eindeutige, unterstützte Smart-Home-Bedeutung, wird
nachgefragt oder nichts ausgeführt. So bleibt das Ergebnis reproduzierbar.

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
| `climate` | Solltemperatur und Betriebsmodus setzen |
| `media_player` | Wiedergabe, Lautstärke und Quelle steuern |
| `vacuum` | starten, pausieren, stoppen und zur Station schicken |
| `scene` | Szenen aktivieren |
| `lock` | ver- und entriegeln; Entriegeln nur nach Bestätigung |
| `sensor` | Werte und Vergleiche abfragen (nur lesend) |
| `binary_sensor` | Zustände abfragen, zum Beispiel Fenster oder Türen (nur lesend) |
| `calendar` | Termine über beschreibbare Home-Assistant-Kalender anlegen |

Beispiele:

```text
Mach das Wohnzimmerlicht an.
Schalte alle Lichter im Erdgeschoss aus.
Stell das Wohnzimmerlicht auf 40 Prozent.
Mach das Licht blau.
Fahre die Rolllade im Wohnzimmer auf 30 Prozent.
Auf halbe Höhe im Erdgeschoss bitte sämtliche Rollläden fahren.
Nach oben fahren sollen im Erdgeschoss alle Rollläden.
Stelle den Ventilator auf Stufe 3.
Starte Gute Nacht.
Stelle die Heizung im Wohnzimmer auf 21 Grad.
Pausiere die Wiedergabe auf Wohnzimmer TV.
Schicke den Saugroboter zur Ladestation.
Aktiviere die Szene Filmabend.
```

Sicherheitskritische direkte Aktionen werden nicht sofort ausgeführt. Das
Entriegeln eines Schlosses sowie das Öffnen oder Schließen eines als Garage
klassifizierten Tores erfordern eine ausdrückliche Bestätigung.

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
Welche Fenster sind im Erdgeschoss?
Gibt es offene Fenster im Keller?
Gibt es im Dachgeschoss Fenster?
Ist das Schlafzimmerfenster geöffnet?
Ist das Badezimmer Fenster geschlossen?
Ist das Fenster vom Badezimmer geschlossen?
Welchen Zustand hat das Badezimmer Fenster?
Was ist der Status vom Badezimmer Fenster?
Sind alle Rollläden hochgefahren?
Sind sämtliche Rollläden oben?
Sind im Erdgeschoss offene Fenster?
Offene Fenster, gibt es die im Erdgeschoss?
Ist irgendein Fenster offen?
Ist kein Fenster offen?
Wie viele Fenster sind im Erdgeschoss geöffnet?
Wo sind Fenster offen?
Was ist im Badezimmer eingeschaltet?
Wie viel Grad sind im Badezimmer?
Wie warm ist es im Wohnzimmer?
Welche Lichter sind heller als 50 Prozent?
Mindestens 50 Prozent, welche Lichter sind das?
Im Wohnzimmer unter 20 Grad, welche Räume betrifft das?
Warum ist das Küchenlicht an?
```

Messwerte können über einen einzelnen Raum oder eine ganze Etage abgefragt
werden. Unterstützt werden derzeit Temperatur, Luftfeuchtigkeit, Batteriestand,
Leistung, Energieverbrauch und Helligkeit:

```text
Wie hoch ist die Temperatur im Erdgeschoss?
Luftfeuchtigkeit im Wohnzimmer.
Stromverbrauch Küche.
Batterien oben unter 20 Prozent.
Wie hell Wohnzimmer?
Im Erdgeschoss aktuell die Temperatur wie viel?
Oben Batterien weniger als 20 Prozent?
```

Auch Messwertfragen werden aus Eigenschaft, Ort, optionalem Vergleich und
Zahl zusammengesetzt. Diese Bausteine dürfen frei angeordnet sein. Mehrere
widersprüchliche Eigenschaften oder unbekannte bedeutungstragende Zusätze
werden nicht stillschweigend ignoriert.

Auch Vergleichsfragen sind nicht an eine Reihenfolge gebunden. Zielgruppe,
Ort, Vergleichsoperator, Zahl und Einheit werden unabhängig erkannt. Die
Kombination muss fachlich zusammenpassen: Grad ist nur für Temperaturziele,
Prozent nur für unterstützte Licht- oder Rollladenwerte zulässig.

Gibt es mehrere passende Sensoren, nennt HomeIntent alle Einzelwerte mit ihrem
Entitätsnamen. Es bildet niemals ungefragt einen Mittelwert. Nur eine
ausdrückliche Formulierung wie „durchschnittliche Temperatur im Erdgeschoss“
liefert einen berechneten Durchschnitt. Unbekannte Orte und Orte ohne passenden,
für Assist freigegebenen Sensor erhalten eine konkrete Fehlermeldung.

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
Du: Nein, ich meinte das Büro.
Du: Wie sieht es oben aus?
```

HomeIntent kann außerdem aus einer vorherigen Abfrage den sicheren räumlichen
Kontext für einen anschließenden Stellbefehl ableiten:

```text
Du: Wie hoch ist die Temperatur im Erdgeschoss?
Assist: 21,6 Grad.
Du: Kannst du die Temperatur auf 22 Grad erhöhen?
Assist: Erdgeschoss Heizung auf 22 Grad gestellt.
```

Der Folgesatz darf auch verkürzt sein. HomeIntent merkt sich dazu nicht nur
die zuletzt genannten Entitäten, sondern einen expliziten Dialogfokus aus
Eigenschaft, Raum beziehungsweise Etage und möglichen Zielgeräten:

```text
Du: Wie warm ist es im Wohnzimmer?
Du: Auf 22 Grad.

Du: Wie hell ist es in der Küche?
Du: Auf 35 Prozent.

Du: Wie warm ist es im Wohnzimmer?
Du: Zwei Grad wärmer.
```

Explizite Korrekturen verändern den räumlichen Bezug, ohne die bereits
verstandene Aktion neu erraten zu müssen:

```text
Du: Mach das Küchenlicht an.
Du: Nein, nicht Küche, sondern Büro.
```

Auch bei erweiterten Geräten können kurze Bezüge fortgeführt werden, etwa
„Pausiere es“ nach einem Medienbefehl oder „Schick ihn zur Ladestation“ nach
einem Staubsaugerbefehl. Der Kontext ist pro Assist-Konversation getrennt und
läuft automatisch ab.

Dasselbe Prinzip gilt für bereits unterstützte Stellgrößen wie Lichthelligkeit,
Rollladenposition und Ventilatorstufe. Gibt es im zuvor genannten Raum oder auf
der Etage mehrere passende Geräte, fragt HomeIntent nach. Messwerte ohne sichere
Aktionszuordnung – beispielsweise Batterie, Luftfeuchtigkeit, Leistung oder
Energie – bleiben ausschließlich lesend und lösen niemals eine erfundene Aktion
aus.

### Kalendertermine anlegen

Seit Version 4.30 kann HomeIntent echte Termine über Home Assistants
`calendar.create_event` anlegen. Das funktioniert auch mit einem über CalDAV
eingebundenen Apple-/iCloud-Kalender, sofern die betreffende `calendar.*`-
Entität das Home-Assistant-Feature `CREATE_EVENT` anbietet und für HomeIntent
freigegeben ist. Nur lesbare Kalender werden nicht als Schreibziel angeboten.

Ein vollständiger Termin kann in einem Satz genannt werden:

```text
Trag nächsten Dienstag um 10 Uhr für eine Stunde Zahnarzt ein.
Erstelle am 25. August von 18 bis 20 Uhr den Termin Geburtstag.
Schreibe Urlaub morgen ganztägig in meinen Kalender ein.
Kannst du morgen um 10 Uhr einen Termin mit dem Titel Zahnarzt für 60 Minuten erstellen?
```

Fehlende Pflichtangaben fragt HomeIntent nacheinander ab. Bereits verstandene
Angaben bleiben dabei im Kontext der aktuellen Assist-Konversation erhalten:

```text
Du: Trag einen Termin ein.
Assist: Wie soll der Termin heißen?
Du: Zahnarzt.
Assist: An welchem Datum findet der Termin statt?
Du: Nächsten Dienstag.
Assist: Um wie viel Uhr beginnt der Termin?
Du: Um 10 Uhr.
Assist: Wann endet der Termin oder wie lange dauert er?
Du: Eine Stunde.
```

Sind mehrere beschreibbare Kalender freigegeben, fragt HomeIntent zusätzlich
nach dem Zielkalender. Bei genau einem geeigneten Kalender wird er automatisch
verwendet. Vor dem Schreiben erscheint immer eine vollständige Vorschau mit
Titel, Datum, Beginn, Ende und Kalender. Erst ein ausdrückliches „Ja“ führt
`calendar.create_event` aus. „Nein“, „Abbrechen“ oder „Stopp“ verwirft den
Entwurf ohne Schreibzugriff.

Solange die Vorschau noch nicht bestätigt wurde, können Angaben korrigiert
werden:

```text
Du: Doch um 11 Uhr.
Du: Der Titel soll Kontrolltermin sein.
Du: Nimm den Familienkalender.
```

Für Termine mit Uhrzeit ist eine Endzeit oder Dauer erforderlich; HomeIntent
erfindet keine Standarddauer. Relative Daten, Wochentage, ausgeschriebene und
numerische Daten sowie Ganztagstermine werden in der lokalen
Home-Assistant-Zeitzone aufgelöst. Vergangene oder wegen einer Zeitumstellung
nicht existierende Zeitpunkte werden abgelehnt.

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
Wenn in der Küche offen die Fenster sind, schalte das Küchenlicht ein.
```

Der Ablauf ist absichtlich zweistufig:

1. HomeIntent zerlegt den Satz in Trigger, optionale Bedingungen und Aktionen.
2. Entitäten, Bereiche, Fähigkeiten, Werte und logische Struktur werden validiert.
3. Assist zeigt eine verständliche Vorschau.
4. Erst nach einer ausdrücklichen Bestätigung mit „Ja“ wird die Automation geschrieben.
5. HomeIntent ergänzt `automations.yaml` atomar und ruft `automation.reload` auf.
6. Die neue Automation erscheint in Home Assistant und erhält die Kategorie **Homeintent**.

Ein „Nein“ bricht die Erstellung ab, ohne etwas zu speichern.

Auslöser und Aktion können außerdem in zwei Gesprächsschritten genannt werden:

```text
Du: Wenn das Küchenfenster geöffnet wird.
Assist: Was soll dann passieren?
Du: Schalte das Küchenlicht ein.
Assist: Automation erkannt: … Soll diese Automation erstellt werden?
```

Der unvollständige Entwurf enthält nur den bereits eindeutig geparsten
Auslöser. Eine unverständliche zweite Antwort führt weder einen Direktbefehl
aus noch erzeugt sie eine Automation; HomeIntent fragt erneut nach einer
vollständigen Aktion. Auch hier wird erst nach der anschließenden Vorschau und
einem ausdrücklichen „Ja“ geschrieben.

### Bedingungen

Trigger können mit Bedingungen kombiniert werden:

```text
Wenn das Küchenfenster geöffnet wird und es nach 18 Uhr ist, schalte das Küchenlicht ein.
Wenn das Küchenfenster geöffnet wird und niemand zuhause ist, schalte das Küchenlicht ein.
Wenn das Küchenfenster geöffnet wird und Samstag ist, schalte das Küchenlicht ein.
```

Die zentrale Struktur dafür ist das `AutomationModel`: ein validierter Syntaxbaum aus Triggern, Bedingungen und Aktionen. Erst der HA-Automation-Generator übersetzt dieses Modell in Home-Assistant-YAML.

Zustandsauslöser und Zustandsbedingungen verwenden denselben semantischen
Predicate-Compiler. Gerätetyp, Zustand und Raum beziehungsweise Etage dürfen
dabei in unterschiedlicher Reihenfolge stehen. Widersprüchliche Zustände oder
nicht erklärte Zusätze werden abgelehnt. Spezialisierte Auslöser wie Uhrzeit,
Sonne, numerische Schwellen und Geräteereignisse bleiben in ihren streng
validierten Fachparsern.

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
In zwei Stunden und 30 Minuten schalte das Küchenlicht ein.
```

Der Countdown beginnt erst nach der Bestätigung mit „Ja“. HomeIntent berechnet dann aus der lokalen Home-Assistant-Zeit einen absoluten Zeitpunkt mit Sekundenpräzision und speichert zusätzlich das vollständige Zieldatum. Minuten-, Stunden- und Tageswechsel sowie Sommerzeitwechsel werden berücksichtigt. Nach der Aktion löscht sich die Automation selbst; vorübergehende Lösch- oder Reloadfehler werden begrenzt erneut versucht.

Das ist **keine täglich wiederkehrende Automation**. Der intern verwendete Uhrzeit-Trigger wird durch eine Datumsbedingung geschützt und nach dem ersten Auslösen entfernt. War Home Assistant beim Zielzeitpunkt ausgeschaltet, wird der verpasste Auftrag beim nächsten Start sicher verworfen, statt am Folgetag eine veraltete Geräteaktion auszuführen.

### Termine in Alltagssprache

HomeIntent versteht zusätzlich kalendarische einmalige Aufträge:

```text
Morgen um 8 Uhr fahre die Rolllade im Büro hoch.
Heute Abend um 20 Uhr schalte das Gartenlicht ein.
Am Samstag um 10 Uhr starte Gute Nacht.
Am 25. August um 18 Uhr schalte das Küchenlicht ein.
Übermorgen früh fahre die Rolllade hoch.
Morgen halb acht schalte das Küchenlicht ein.
Morgen viertel vor neun schalte das Küchenlicht ein.
Nächsten Samstag um 10 Uhr starte Gute Nacht.
```

Der Termin wird erst bei der Bestätigung in der lokalen Home-Assistant-Zeitzone
aufgelöst. Nicht existierende Uhrzeiten bei einem Sommerzeitwechsel und bereits
vergangene Termine werden abgelehnt. Für Tageszeiten ohne Uhrzeit gelten feste,
reproduzierbare Standardwerte; „früh“ bedeutet derzeit 08:00 Uhr.

Bei zustandsbasierten Automationen darf das trennende Komma entfallen, sofern
Trigger und Aktion durch ihre Grammatiken genau eine mögliche Trennstelle haben.
Auch die umgekehrte Satzreihenfolge und wiederkehrende Umgangsformen werden
verstanden:

```text
Wenn das Bürofenster geöffnet wird schalte das Küchenlicht ein.
Schalte das Küchenlicht ein wenn das Bürofenster geöffnet wird.
Jedes Mal wenn das Bürofenster geöffnet wird schalte das Küchenlicht ein.
```

### Eine Automation begrenzt wiederholen

Mit Formulierungen wie „nur dreimal“ kann die Ausführungszahl einer Automation
auf zwei bis zehn Läufe begrenzt werden. HomeIntent zählt erfolgreiche Läufe in
seinen Metadaten und löscht die Automation nach dem letzten Lauf. Die Vorschau
nennt die Begrenzung vor der Bestätigung.

### Automationen verwalten

```text
Welche Automationen gibt es?
Zeige nur HomeIntent-Automationen.
Welche einmaligen Aufträge sind noch geplant?
Wann wird die Rolllade gefahren?
Verschiebe den Auftrag für die Rolllade auf 20 Uhr.
Lösche alle abgelaufenen HomeIntent-Automationen.
Was schaltet das Küchenlicht?
Warum ist das Küchenlicht an?
Deaktiviere die Automation für Küchenlicht.
Aktiviere die Automation für Küchenlicht.
Lösche die Automation für Küchenlicht.
```

Löschen erfordert eine Bestätigung. Aktivieren und Deaktivieren ändern den dauerhaften `initial_state` in `automations.yaml`; die Einstellung bleibt daher auch nach einem Reload oder Neustart erhalten. Beim Verschieben muss genau ein noch geplanter einmaliger Auftrag passen. Bei mehreren Treffern nennt HomeIntent die Kandidaten und bittet um ein eindeutigeres Gerät, statt einen beliebigen Auftrag zu ändern.

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

Für das Anlegen von Terminen muss die gewünschte `calendar.*`-Entität ebenfalls
für Assist beziehungsweise in den HomeIntent-Integrationsoptionen freigegeben
sein. Wurde früher bereits eine feste Entitätsauswahl gespeichert, wird ein
später hinzugefügter Kalender nicht automatisch ergänzt; öffne dann die
Optionen von **HA NLU Engine** und wähle den Kalender dort zusätzlich aus.

## Kategorie „Homeintent“

Alle ab Version 4.20.0 neu durch HomeIntent erzeugten Automationen werden automatisch der Home-Assistant-Automationskategorie **Homeintent** zugeordnet. Das gilt für:

- dauerhafte Automationen,
- einmalige zustandsbasierte Automationen und
- zeitversetzte Einmal-Automationen.

Existiert die Kategorie bereits mit einer anderen Groß-/Kleinschreibung, wird sie wiederverwendet. Beim Start gleicht HomeIntent bekannte eigene Automationen, Metadaten und Kategorien ab. Dadurch werden fehlende Kategoriezuordnungen repariert und verwaiste HomeIntent-Metadaten entfernt.

Die Kategorie dient nur der übersichtlichen Gruppierung in der Automationsansicht. Sie verändert nicht das Ausführungsverhalten.

## Sicherheit und Datenhaltung

### Keine Ausführung bei Mehrdeutigkeit

Wenn mehrere Entitäten gleich gut passen und kein Bereich oder Kontext die Auswahl eindeutig macht, führt HomeIntent nicht einfach die erste gefundene Entität aus.

### Fähigkeiten werden geprüft

Eine Aktion wird nur erzeugt, wenn die Zielentität die erforderliche Funktion unterstützt. Eine Rollladenposition benötigt beispielsweise Positionsunterstützung; eine Farbe wird nur für ein farbfähiges Licht akzeptiert.

### Automationen brauchen eine Bestätigung

Das Erkennen eines Automationssatzes verändert Home Assistant noch nicht. Erst die Bestätigung startet Generator und Executor.

### Transaktionales Schreiben

Beim Erstellen werden `automations.yaml`, der Live-Zustand nach `automation.reload`, die Homeintent-Kategorie und die internen Metadaten aufeinander abgestimmt. Auch Löschen, Aktivieren, Deaktivieren, Verschieben und automatische Bereinigungen verwenden denselben geschützten Ablauf.

Alle Executor-Instanzen einer Home-Assistant-Instanz teilen eine Schreibsperre. Zusätzlich vergleicht HomeIntent unmittelbar vor dem Speichern einen kryptografischen Fingerabdruck der gelesenen Datei. Hat Home Assistant oder ein Benutzer die Datei zwischenzeitlich geändert, wird der Vorgang mit einem Konflikt abgebrochen und die fremde Änderung nicht überschrieben. Ein kleines dauerhaftes Transaktionsjournal erlaubt nach einem Absturz die Wiederherstellung des vorherigen Zustands. Ein Rollback erfolgt nur, wenn die aktuelle Datei noch exakt dem von HomeIntent geschriebenen Stand entspricht.

### Lokal und privat

Die NLU-Verarbeitung läuft innerhalb von Home Assistant. HomeIntent sendet den gesprochenen Text nicht an einen eigenen Cloud-Dienst.

Über die Home-Assistant-Funktion „Diagnoseinformationen herunterladen“ können
Nutzer bei Bedarf bewusst technische Eckdaten erzeugen. Diese Diagnose enthält
weder Gesprächsformulierungen noch Entitäts-IDs oder Zustände. HomeIntent
speichert keine gesprochenen Texte und kein World Model dauerhaft.

## Bekannte Grenzen

- Die mitgelieferten Grammatiken sind derzeit auf Deutsch ausgelegt.
- HomeIntent ist absichtlich kein Chatbot und versteht nur unterstützte Smart-Home-Strukturen.
- Relative Einmal-Befehle unterstützen aktuell Sekunden, Minuten und Stunden bis maximal 59 Stunden sowie Kombinationen aus zwei Zeiteinheiten.
- Kalendarische Formulierungen decken die dokumentierten Muster ab, sind aber noch kein allgemeiner Kalenderparser für beliebige deutsche Datumsangaben.
- Ist Home Assistant beim berechneten Zeitpunkt ausgeschaltet, wird der verpasste Auftrag aus Sicherheitsgründen verworfen. Eine automatische verspätete Ausführung findet bewusst nicht statt.
- Direkte Steuerung neuer Gerätedomänen unterstützt bewusst nur geprüfte Kernaktionen. Erweiterte Klima-, Medien- oder Staubsaugerfunktionen können je nach Gerät noch fehlen.
- Nicht jeder intern modellierbare Trigger, jede Bedingung oder Aktion besitzt bereits eine sichere Home-Assistant-YAML-Abbildung. Nicht unterstützte Strukturen werden abgelehnt, statt angenähert zu werden.
- Kalendertermine können derzeit angelegt, aber noch nicht über HomeIntent verschoben, bearbeitet, aufgelistet oder gelöscht werden. Diese Funktionen hängen zusätzlich von den Fähigkeiten der jeweiligen Kalenderintegration ab.
- Die Qualität der Zielauflösung hängt von sinnvollen Entity-Namen, Bereichen, Geräteklassen, Fähigkeiten und Assist-Freigaben ab.

## Architektur

Die wichtigsten Schichten sind bewusst getrennt:

```text
Conversation Agent
      │
      ├── Router für Direktbefehl, Gerätesteuerung und Abfrage
      │       └── Semantic Frame → Resolver → Validator → Service Mapper
      │
      └── Automation
              └── Zeit-/Trigger-/Condition-/Action-Parser
                  → AutomationModel
                  → AutomationValidator
                  → Vorschau und Bestätigung
                  → HA Automation Generator
                  → AutomationExecutor + Transaktionsjournal
```

Der Parser führt keine Home-Assistant-Dienste direkt aus. Dadurch können Sprachverständnis, Auflösung, Validierung, Vorschau und Ausführung unabhängig getestet werden. Neue Zuständigkeiten sind in eigene Module für Gerätesteuerung, kalendarische Termine, Automationsverwaltung, Ergebnisobjekte und Dateitransaktionen ausgelagert. Die verbleibenden großen Kernmodule werden schrittweise und verhaltensneutral weiter zerlegt.

Weiterführende technische Dokumentation liegt im Verzeichnis [`docs`](docs/).

## Entwicklung und Tests

Die reproduzierbaren Testabhängigkeiten stehen in `requirements-dev.txt`:

```bash
python -m pip install --requirement requirements-dev.txt
```

Danach kann die komplette Testsuite so ausgeführt werden:

```bash
python -m pytest -q
```

Aktueller Entwicklungsstand:

```text
1851 passed, 12 skipped
```

Zusätzlich wird HomeIntent gegen die getrennte, agentenneutrale Suite
`ha-conversation-benchmark-de` geprüft. Der aktuelle öffentliche Korpus enthält
1.139 Fälle aus einer systematischen Gerätematrix und handgeprüften Aufgaben
für freie Wortstellung, Mehrturn-Kontext, Mehrdeutigkeit, Mixed-Intent,
Klima/Medien/Saugroboter/Szenen, zeitgesteuerte Automationen, Kalenderdialoge,
typische STT-Umschriften und sichere Ablehnungen. Der aktuelle Stand besteht
1.139 von 1.139 Fällen in drei identischen Läufen bei null unsicheren
Falschausführungen. Erwartungswerte werden unabhängig vom HomeIntent-Code
festgelegt; eine höhere Quote darf nicht durch das Abschwächen der Sollwerte
entstehen.

Zusätzlich enthält `tests/eval/dialog_cases.json` ein datengetriebenes
Mehrturn-Sprachkorpus. Das separate Sicherheitsgate garantiert, dass negative
und nur lesende Fälle keinen Serviceplan erzeugen:

```bash
./scripts/run_language_eval.sh
```

GitHub Actions prüft zusätzlich Python 3.12 und 3.13, Hassfest, HACS und den Import gegen das aktuelle stabile Home-Assistant-Containerimage.

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

HomeIntent steht unter der [MIT-Lizenz](LICENSE).
