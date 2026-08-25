# Sprachverständnis und Dialogmodell

HomeIntent erweitert sein Sprachverständnis weiterhin deterministisch. Ein
Folgesatz wird nur ausgeführt, wenn Eigenschaft, räumlicher Bezug, Zielgerät,
Fähigkeit und Wert aus dem aktuellen und dem vorherigen Turn eindeutig
bestimmt werden können.

## Äußerungs- und Klauselmodell

`nlu/semantic_utterance.py` beschreibt die sprachliche Form vor der
fachlichen Geräteauflösung. Es unterscheidet Sprechakt, Modalität, Polarität
und die Rollen Hauptsatz, Aktion, Auslöser und Bedingung. Das Modell enthält
keine Home-Assistant-Objekte und führt nichts aus.

Die Ausführung bleibt konservativ:

- höfliche oder als Wunsch formulierte eindeutige Befehle sind zulässig,
- hypothetische, unsichere und negierte Befehle werden nicht ausgeführt,
- eine Triggerklausel wird an die Automationspipeline übergeben und
- Informationsfragen bleiben auch dann lesend, wenn sie ein Aktionsverb als
  Beispiel enthalten.

Die Normalisierung in `nlu/normalize.py` vereinheitlicht rein sprachliche
Oberflächenformen. Dazu gehören natürliche Anfragehüllen, trennbare Verben,
Zahlwörter vor Grad/Prozent und Bruchteile. Entity-Namen, Räume und Geräte
werden dort ausdrücklich nicht aufgelöst.

## Gemeinsame Geräte- und Automationssemantik

Direkte Kernbefehle, erweiterte Gerätebefehle und Automationsaktionen teilen
Normalisierung und Sicherheitsklassifikation. Entity-, Raum-, Etagen-,
Gruppen- und Capability-Auflösung bleiben in den vorhandenen gemeinsamen
Resolvern. Der Automationspfad verwendet das Klauselmodell als zusätzliche
Strukturquelle, validiert Trigger und Aktion aber weiterhin mit den
spezialisierten Parsern und dem `AutomationValidator`.

Medien- und Staubsauger-Folgeäußerungen werden als Operation plus genau ein
zuvor aufgelöstes Gerät verstanden. Wortstellung, Pronomen und harmlose
Füllpartikel sind dabei variabel; mehrere oder widersprüchliche Operationen
werden abgelehnt.

## Dialogfokus

Nach einem erfolgreichen Befehl oder einer Abfrage wird ein `DialogFocus`
gebildet. Er enthält:

- die semantische Eigenschaft, etwa Temperatur, Helligkeit oder Position,
- den Scope als Entität, Raum oder Etage,
- die ID dieses Scopes,
- die im letzten Turn gefundenen Kandidaten und
- den Quell-Intent.

Dadurch funktionieren unter anderem „Auf 22 Grad“, „Auf 35 Prozent“, „Zwei
Grad wärmer“ und explizite räumliche Korrekturen. Batterie, Luftfeuchtigkeit,
Leistung und Energie bleiben lesend und dürfen keinen Stellbefehl implizieren.

## Strukturierte Ablehnungen

`UnderstandingFeedback` unterscheidet unter anderem unbekannte Orte,
mehrdeutige Ziele, fehlende Fähigkeiten, ungültige Werte, unvollständige
Anfragen und unsichere Schlussfolgerungen. Die Spracheingabe erhält weiterhin
eine kurze deutsche Antwort; Tests und lokale Diagnose können zusätzlich den
strukturierten Grund prüfen.

## Automationsdialog

Ein vollständiger Auslöser ohne Aktion erzeugt einen kurzlebigen
`PendingAutomationDraft`. Die nächste Äußerung muss eine vollständige,
validierbare Aktion sein. Anschließend gilt derselbe Vorschau- und
Bestätigungsmechanismus wie bei einem einteiligen Automationssatz.

Solange die Vorschau noch nicht bestätigt ist, sind begrenzte Änderungen
möglich:

- Uhrzeit ändern,
- auf eine feste Ausführungszahl begrenzen,
- eine weitere Aktion hinzufügen,
- eine Bedingung hinzufügen oder
- Bedingungen entfernen.

Jede Änderung erzeugt erneut ein `AutomationModel`, durchläuft den Validator
und ersetzt die ausstehende Vorschau. Sie schreibt noch keine YAML-Datei.

## Evaluation und Datenschutz

Das datengetriebene Korpus `tests/eval/dialog_cases.json` enthält Ein- und
Mehrturnfälle. Das Release-Gate verlangt insbesondere null Servicepläne für
negative und rein lesende Fälle. Es lässt sich mit
`scripts/run_language_eval.sh` separat ausführen und läuft zusätzlich in CI.

HomeIntent speichert keine Äußerungen und kein World Model dauerhaft. Die
Home-Assistant-Diagnose wird nur auf ausdrückliche Nutzeraktion erzeugt und
enthält weder Äußerungen noch Entitäts-IDs oder Zustände.

`tests/test_semantic_paraphrase_matrix.py` bildet zusätzlich 1.024
komponierte Paraphrasen aus voneinander unabhängigen Bedeutungsdimensionen.
Der Testkorpus ist strikt von der Produktivlogik getrennt. Neue Sprachregeln
müssen außerdem positive Fälle, Konflikte, Negation, Mehrdeutigkeit und
fehlende Fähigkeiten gemeinsam testen.

## Bewusste Grenze

Das System ist kein offener Chatbot. Ungefähre Zeitangaben wie „morgen gegen
Abend“ werden nicht still auf eine angenommene Uhrzeit gelegt, sondern führen
zu einer Bitte um eine genaue Uhrzeit. Ebenso werden unklare Referenzen und
mehrdeutige Geräte nicht geraten.
