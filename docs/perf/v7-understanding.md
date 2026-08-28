# V7 Understanding Pipeline – Performance Check

Stand: 28. August 2026, HomeIntent V7-Release-Stand 4.61.0.

Gemessen wurde `NluEngine.understand()` einschließlich verlustarmem
Sprach-Frontend, Kandidatenmodell, zentralem Sicherheitsgate und bestehender
validierter Payload-Erzeugung. Wie bei der V6-Baseline endet die Messung vor
dem echten Home-Assistant-Serviceaufruf. Hardware: virtualisierte x86_64-
Entwicklungsumgebung, nicht Raspberry Pi; die Werte sind daher vor allem für
relative Vergleiche geeignet.

Kommando:

```bash
python scripts/benchmark_v6_baseline.py \
  --pipeline understand --scales 5000 --iterations 3 --warmup 1
```

## Ergebnis bei 5.000 synthetischen Entities

| Fall | Mittel | p95 |
|---|---:|---:|
| Licht an | 44,60 ms | 45,62 ms |
| Licht aus | 43,18 ms | 43,40 ms |
| Heizung auf Temperatur | 42,67 ms | 43,98 ms |
| Sensorabfrage | 11,50 ms | 11,59 ms |
| Bereichsgruppe | 22,27 ms | 23,44 ms |
| Cover-Prozentwert | 46,66 ms | 53,51 ms |
| freie semantische Query | 17,50 ms | 17,64 ms |

Zum Vergleich lag der Legacy-`match()`-Pfad desselben Laufs für die
namensbasierten Fälle bei rund 40–42 ms. Der V7-Overhead ist nach der
Optimierung damit klein gegenüber der bereits vorhandenen linearen
Namensauflösung. Bei 100 Entities lag der Durchschnitt über die sieben Fälle
bei rund 3,7 ms.

## Durchgeführte Optimierungen

- Phonetische Entity-Korrektur läuft nicht mehr bei jedem erfolgreichen Turn,
  sondern weiterhin nur im bestätigungspflichtigen No-Match-Pfad.
- Bei einem bereits validierten Ergebnis erzeugt der Interpreter Kandidaten,
  ohne dieselbe Entity-Auflösung oder denselben Compiler ein zweites Mal
  auszuführen.
- Registry-Compound-Varianten werden nur bei einem echten Ortscue gebildet.
- Semantisch bereits erkannte Wörter durchlaufen keine Edit-Distanz-Suche.
- Dynamische Registry-Namensprüfung wird erst nach allen billigen
  Diskursbedingungen ausgeführt.

## Verbleibende Grenze

Die namensbasierten Fälle skalieren weiterhin mit der bestehenden
Legacy-Auflösung. Der V7-Semantic-Compiler nutzt den `WorldModel.entity_index`
bereits; vollständig flache Skalierung setzt voraus, dass auch die letzten
Legacy-Parser auf den gemeinsamen indexierten Resolver migriert oder entfernt
werden. Vor einem finalen V7-Release bleibt ein Lauf auf echter Pi-4/5-
Hardware erforderlich.

## Kontrolle nach dem Entity-Candidate-Ausbau

Nach Einführung von `EntityCandidateSet`, Herkunftsscores und bounded fuzzy
matching wurde erneut mit 100 und 5.000 Entities gemessen. Fuzzy-Distanzen
laufen in einem zweiten Pass ausschließlich dann, wenn kein exakter, Alias-
oder Teiltreffer existiert. Erfolgreiche Standardbefehle bezahlen daher
keinen Edit-Distanz-Vollscan.

Bei zwei Messwiederholungen auf derselben virtualisierten
Entwicklungsumgebung lagen die 5.000-Entity-p95-Werte zwischen 19,35 ms für
die Sensorabfrage und 60,26 ms für den langsamsten Namensfall. Diese kurze
Kontrollmessung ist ein Regressionsindikator, ersetzt aber weiterhin nicht
das Release-Gate auf echter Pi-Hardware.

## Kontrolle nach der ersten V7-Autoritätsumschaltung

Für Licht Ein/Aus läuft der Semantic Interpreter nun vor Legacy. Ein erster
naiver Versuch mit zusätzlichem vollständigem Registry-Evidence-Scan wurde
verworfen: er lag bei 5.000 Entities zwischen rund 0,8 und 1,1 Sekunden und
war damit nicht releasefähig. Im aktiven Pfad übernimmt der Compiler bereits
die autoritative Target-Auflösung; der redundante All-Mentions-Scan bleibt
daher dem expliziten Shadow-Modus vorbehalten. Exakte eingebettete Namen
werden außerdem über begrenzte N-Gramme im vorhandenen `EntityIndex`
gefunden, wobei Friendly-Name-/Alias-Gleichstände unverändert erhalten
bleiben.

Kontrolllauf auf derselben virtualisierten x86_64-Umgebung, drei Iterationen
und ein Warmup bei 5.000 synthetischen Entities:

| Fall | Mittel | p95 |
|---|---:|---:|
| Licht an, V7 autoritativ | 21,12 ms | 21,32 ms |
| Licht aus, V7 autoritativ | 20,88 ms | 21,24 ms |
| Heizung auf Temperatur, Legacy-Fallback | 61,78 ms | 62,84 ms |
| Sensorabfrage | 18,43 ms | 18,50 ms |
| Bereichsgruppe | 45,17 ms | 54,46 ms |
| Cover-Prozentwert | 63,04 ms | 63,17 ms |
| freie semantische Query | 23,79 ms | 24,05 ms |

Das lokale 100-ms-Budget bleibt eingehalten. Diese Werte sind kein Ersatz für
die weiterhin offene Messung auf echter Pi-4/5-Hardware; ohne Zugriff auf
solche Hardware wird kein Zielhardware-Ergebnis behauptet.

Das CI-Budget verwendet 20 Messwerte nach drei Warmups. Mit nur drei
Messwerten wäre der ausgewiesene p95 praktisch der einzelne Maximalwert und
damit als blockierendes Gate zu empfindlich gegenüber Runner-Jitter. Im
20er-Kontrolllauf lagen alle p95-Werte unter 87 ms; das Budget bleibt 100 ms.
