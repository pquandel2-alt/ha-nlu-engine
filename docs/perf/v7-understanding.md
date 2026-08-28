# V7 Understanding Pipeline – Performance Check

Stand: 27. August 2026, HomeIntent V7-Release-Stand 4.60.0.

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
