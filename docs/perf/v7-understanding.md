# V7 Understanding Pipeline – Performance Check

Stand: 28. August 2026, HomeIntent V7-Release-Stand 4.62.0.

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

### Kontrolle nach dem lokalen JARVIS-Kernausbau (2026-09-02)

Der gemeinsame Resolver verwendet für die entscheidende exakte Namensstufe
jetzt den bereits pro Turn aufgebauten `EntityIndex`. Der Semantic Compiler
überspringt außerdem Registry-Namensscans, wenn Domäne beziehungsweise
Geräteklasse schon eindeutig sind, und löst Räume/Etagen aus den vorhandenen
`WorldModel`-Snapshots statt sie erneut aus 5.000 Entities aufzubauen.

Im finalen isolierten CI-Kommando lagen sechs der sieben p95-Werte zwischen
20,12 und 70,07 ms. Die freie semantische Query lag bei einem Median von
54,56 ms, aber einem p95 von 125,25 ms und überschritt damit weiterhin das
unveränderte 100-ms-Gate. Frühere Wiederholungen desselben Laufs schwankten
für diesen Fall zwischen 98,19 und 327,79 ms. Das Gate und die Baseline wurden
nicht angepasst; die Ausreißer auf der virtualisierten Entwicklungsumgebung
bleiben ein offener Release-Blocker und müssen zusätzlich auf Zielhardware
reproduziert werden.

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

## Kontrolle nach Query- und Property-Autoritätsausbau

Nach der Ausweitung der autoritativen Capability-Matrix zeigte das Gate
zunächst eine reale Regression: Sensor- und freie Zustandsabfragen lagen bei
5.000 Entities bei 425–473 ms p95. Ursache war ein pro Entity neu
kompilierter Wortgrenzen-Regex im eingebetteten Namensscan. Der Resolver
verwendet nun einen semantisch gleichwertigen begrenzten Literalscan; Tests
sichern Treffer an Satzzeichen sowie das Verbot von Teilworttreffern ab.

Kontrolllauf mit 20 Messwerten und drei Warmups auf derselben virtualisierten
x86_64-Entwicklungsumgebung:

| Fall | Mittel | p95 |
|---|---:|---:|
| Licht an | 14,16 ms | 14,53 ms |
| Licht aus | 14,01 ms | 14,22 ms |
| Heizung auf Temperatur | 12,29 ms | 12,40 ms |
| Sensorabfrage | 20,45 ms | 20,63 ms |
| Bereichsgruppe | 35,85 ms | 36,86 ms |
| Cover-Prozentwert | 55,02 ms | 55,57 ms |
| freie semantische Query | 25,35 ms | 25,94 ms |

Damit liegt jeder gemessene 5.000-Entity-p95 wieder unter dem blockierenden
100-ms-Budget. Die offene Pi-4/5-Messung bleibt davon unberührt und wird
nicht durch x86-Werte ersetzt.
