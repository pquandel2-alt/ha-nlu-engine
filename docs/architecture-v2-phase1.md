# v2-Umbau, Phase 1: SemanticFrame eingeführt

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Baseline bis Area Resolver 2.0
(Phasen 0-7)", Abschnitt "Phase 1 – SemanticFrame einführen". Baseline vor
diesem Schritt: `docs/architecture-v1.md`.

## Was neu ist

Neues Paket `custom_components/ha_nlu/nlu/` (bewusst frei von
Home-Assistant- und hassil-Importen, damit es von jeder künftigen
Parser-Implementierung wiederverwendet werden kann — siehe Phase 2,
Intent Parser Registry):

- `nlu/frame.py` — `TargetReference`, `AreaReference`, `SemanticFrame`
  (Felder wie im Plan vorgegeben: `intent`, `target`, `area`, `parameters`,
  `source_text`).

`engine.py`s `MatchResult` hat ein neues, drittes Feld `frame:
SemanticFrame | None = None`. Alle drei Match-Pfade (`_match_single`,
`_match_quantifier`, `_match_percentage`) bauen nach erfolgreicher
Entity-/Area-Auflösung zusätzlich einen `SemanticFrame` und hängen ihn an
das `MatchResult` an:

- `_match_single`: `target` = aufgelöste Entity (Text + entity_id + domain),
  `area` = `None` (v1 kennt hier keinen separaten Raumbezug).
- `_match_percentage`: wie `_match_single`, zusätzlich
  `parameters={"percent": <wert>}`.
- `_match_quantifier`: `target` referenziert die Domain (kein einzelnes
  Gerät), `area` nur gesetzt wenn ein Raum erkannt wurde,
  `parameters={"quantifier": "all"|"both"}`.

## Was bewusst NICHT geändert wurde

Wie in Phase 1 des Plans vorgegeben ("Parser darf zunächst nur ein Frame
erzeugen... Noch kein ServiceCall"): der `SemanticFrame` wird gebaut, aber
nirgendwo zur ServiceCall-Erzeugung verwendet — `spec.build(...)` (aus
`INTENTS`/`PERCENT_INTENTS`/`QUERY_INTENTS`) bleibt exakt wie in v1 die
einzige Quelle für `ServiceCallPlan`. Die Intent-Dispatch-Logik
(drei getrennte hassil-`Intents`-Grammatiken, Regex-Vorrouting) ist
unverändert; ihre Vereinheitlichung hinter einer `IntentParser`-Registry
ist Phase 2, nicht Teil dieses Schritts.

`conversation.py` liest weiterhin nur `result.plan`/`result.response_text`
— das neue `frame`-Feld hat noch keinen Konsumenten außerhalb der Tests.

## Tests

Neue Datei `tests/test_semantic_frame.py` (6 Tests) pinnt Intent, Target,
Area und Parameters des gebauten Frames für alle drei Match-Pfade sowie den
No-Match-Fall fest. Bestehende Tests unverändert grün.

**Ergebnis:** 288/288 Tests grün (282 Baseline + 6 neu), `pytest -q`
Laufzeit weiterhin < 1s.
