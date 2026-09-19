# V9-Completion – Performanceprotokoll

Stand: 14. September 2026

## Kommando und unveränderte Grenzen

```bash
python scripts/benchmark_v6_baseline.py \
  --pipeline understand \
  --scales 5000 \
  --iterations 20 \
  --warmup 3 \
  --max-p95-ms 100
```

Das normale p95-Budget bleibt 100 ms. Die bereits versionierten Grenzen für
bewusst komplexe V9-Labels bleiben ebenfalls unverändert. Der Completion-Lauf
ergänzt `v9_discourse_followup`: eine produktive Startquery, Speicherung ihres
typisierten Resultsets und anschließendes „Welche davon sind oben?“ über
`ConversationContext` und dieselbe Query-Algebra.

## Optimierung

Vor der Optimierung prüfte die Auflösung des Levelworts „oben“ für jeden
Follow-up sämtliche generierten Entity-Aliase. Bei 5.000 Entities ergab das
für `v9_discourse_followup` 12.944,14 ms p95. Die Kandidatensuche verwendet nun
den bestehenden `EntityIndex`; die exakte Prüfung, ob „oben“ Bestandteil eines
registrierten Entity-Namens ist, bleibt erhalten. Danach maß der vollständige
Lauf 84,23 ms p95 für denselben produktiven Follow-up.

## Letzter vollständiger lokaler Lauf

Die Entwicklungsumgebung stellte vier CPUs bereit, während `uptime` eine
Load-Average von 61,38 meldete. Das Gate endete deshalb mit Exit 1. Die Werte
sind keine als grün deklarierte Release-Messung:

| Pfad | p50 | p95 | Budget |
|---|---:|---:|---:|
| einfacher V9-Query | 33,78 ms | 156,97 ms | 100 ms |
| relationale Query | 209,45 ms | 300,47 ms | 500 ms |
| Zwei-Hop-Relation | 275,81 ms | 436,20 ms | 500 ms |
| verschachtelter Filter | 245,61 ms | 352,95 ms | 250 ms |
| Aggregate | 125,00 ms | 261,72 ms | 400 ms |
| Grouping | 32,22 ms | 51,11 ms | 100 ms |
| Superlativ | 146,21 ms | 244,87 ms | 300 ms |
| relationaler Command | 303,52 ms | 481,05 ms | 750 ms |
| Gruppenreferenz | 163,87 ms | 316,77 ms | 250 ms |
| echter Discourse-Follow-up | 53,33 ms | 84,23 ms | 100 ms |

Auch bestehende Normalpfade wie Bereichsquantifizierung (229,16 ms p95),
Multi-Clause (107,41 ms), Same-Area (123,32 ms) und freie semantische Query
(123,20 ms) überschritten in diesem Lauf ihr 100-ms-Budget. Das spricht für
starke externe CPU-Konkurrenz, ersetzt aber keinen grünen Lauf. Die Budgets
wurden weder erhöht noch aus dem CI-Workflow entfernt. Der unveränderte
GitHub-Actions-Lauf auf dem Release-Commit bleibt der maßgebliche offene
Performance-Nachweis.
