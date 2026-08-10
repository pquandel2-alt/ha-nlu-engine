# v2-Umbau, Phase 21: Negative Tests

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Golden/Negative Tests,
Debug-Modus, Performance (Phasen 23-27, 29-30)", Abschnitt "28. Negative
Tests". Vorstufe: `docs/architecture-v2-phase19.md` (Golden Tests).

## Ausgangslage

Der Plan nennt Negative Tests als "mindestens genauso wichtig" wie die
Golden Tests aus Phase 20 - mit fünf konkreten Beispielsätzen: Kauderwelsch
("Mach irgendwas."), ein unvollständiger Satz ("Mach das Licht."), eine
abgelehnte Capability ("Mach die Lampe blau." bei fehlender Farbunterstützung),
ein Prozentwert außerhalb des Bereichs ("Stell die Rolllade auf 200
Prozent."), und ein `"beide"`-Quantor bei nur einem passenden Treffer
("Mach beide Lichter an." bei nur einem Licht). Erwartung durchgehend: kein
`ServiceCall`.

## Bereits vorhandene Abdeckung aus Phase 20

`tests/golden/negative.json` (Teil der Golden-Tests-Infrastruktur aus Phase
20) deckte vier der fünf Plan-Beispiele bereits ab, mit denselben
`GOLDEN_ENTITIES`:

- Kauderwelsch: `"blubb schnarch wuppdi"`, `"Mach irgendwas."`
- Unvollständiger Satz: `"Mach das Licht."`
- Abgelehnte Capability: `"Mach die Küchenlampe blau"` (`light.kueche` hat
  keine `COLOR`-Capability)
- Prozent außerhalb 0-100: `"stelle den Rollladen Büro auf 200 Prozent"`,
  `"mach das Licht auf 150 Prozent"`

Was fehlte: der fünfte Fall - `"beide"` bei nur einem Treffer statt bei drei
(der bereits vorhandene Fall `"mach beide Lichter an"` hat mit den drei
Wohnzimmer-/Küchen-/Flur-Lichtern zu *viele* Treffer, nicht zu *wenige* -
`QuantifierParser`s `len(matches) != 2`-Prüfung deckt zwar rechnerisch
beide Richtungen ab, aber der Plan nennt explizit den "nur ein Treffer"-Fall
als eigenes Beispiel).

## Ergänzung

Zwei neue Fälle in `negative.json` (per `scripts/generate_golden_tests.py`
neu generiert, gleicher Golden/Snapshot-Ansatz wie in Phase 20 - der
Generator prüft `assert result is None`, kein Hand-Rechnen):

- `"mach beide Ventilatoren an"` - `fan.venti` ist die einzige
  `fan`-Entity in `GOLDEN_ENTITIES`, exakt der vom Plan genannte
  "nur ein passendes Gerät"-Fall.
- `"schalte beide Schalter aus"` - dieselbe Regel, `switch`-Domain
  (ebenfalls nur eine Entity).

`tests/golden/negative.json` enthält jetzt 17 Fälle (vorher 15), alle über
den bestehenden `tests/test_golden.py`-Replay abgedeckt - keine neue
Testdatei nötig, da die Negative Tests strukturell bereits Teil derselben
Golden-Infrastruktur sind.

## Bewusst NICHT dupliziert

Die breitere Testmatrix aus Abschnitt 26 des Plans (Entity Resolution:
exact/normalized/alias/substring/ambiguous/not-found; Parameter-Grenzwerte
0/1/50/100/-1/101) ist zum Großteil bereits an anderer Stelle abgedeckt und
wird hier nicht erneut aufgebaut:

- Entity-Resolution-Randfälle (exact/normalized/alias/substring/ambiguous)
  hat `tests/test_entity_resolution.py` (Phase 7) bereits dediziert, mit
  demselben `resolve_entity()`, den auch die Golden Tests durchlaufen -
  eine Duplikation in JSON-Form hätte keinen zusätzlichen Erkenntniswert.
- Parametergrenzen 0/50/100 sind in `percentage.json` (Phase 20) als
  Positiv-Fälle vertreten, 150/200 als Negativ-Fälle hier. `-1` (negatives
  Prozent) ist keine natürliche deutsche Sprachäußerung (würde "minus eins
  Prozent" erfordern, kein Bestandteil der `RangeSlotList`-Grammatik) und
  wurde deshalb nicht ergänzt - ein handgetippter negativer Zahlenstring
  ohne gesprochenes Äquivalent wäre ein synthetischer, kein Regressionstest
  für echte Nutzereingaben.

Die Conversation-Randfälle (follow-up, pronoun, clarification, context
expiration) aus Abschnitt 26 gehören inhaltlich zu den späteren Phasen 25-27
(Clarification/Context/Pronomen) - es gibt heute noch keinen
`ConversationContext`, den man dafür testen könnte.

## Tests

**Ergebnis:** 579/579 Tests grün (577 aus Phase 20 + 2 neue Negativ-Fälle),
`pytest -q` weiterhin < 2s. `pyflakes` clean (inkl. `scripts/`).
