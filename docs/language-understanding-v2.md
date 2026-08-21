# Sprachverständnis und Dialogmodell

HomeIntent erweitert sein Sprachverständnis weiterhin deterministisch. Ein
Folgesatz wird nur ausgeführt, wenn Eigenschaft, räumlicher Bezug, Zielgerät,
Fähigkeit und Wert aus dem aktuellen und dem vorherigen Turn eindeutig
bestimmt werden können.

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

## Bewusste Grenze

Das System ist kein offener Chatbot. Ungefähre Zeitangaben wie „morgen gegen
Abend“ werden nicht still auf eine angenommene Uhrzeit gelegt, sondern führen
zu einer Bitte um eine genaue Uhrzeit. Ebenso werden unklare Referenzen und
mehrdeutige Geräte nicht geraten.
