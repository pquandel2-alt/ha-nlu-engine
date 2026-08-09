# v2-Umbau, Phase 8: Quantifier-System generalisieren

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Quantifier, Capability,
Command, Validator, ServiceMapper (Phasen 8-13)", Abschnitt "Phase 8 –
Quantifier-System".
Vorstufe: `docs/architecture-v2-phase7.md` (Area Resolver 2.0).

## Was neu ist

Der bisherige Roh-String ("all"/"both"), den `QuantifierParser` in
`SemanticFrame.parameters["quantifier"]` ablegte, wird durch einen
strukturierten Typ in `nlu/frame.py` ersetzt - dieselbe Idee wie
`TargetReference`/`AreaReference`, ein eigenes Feld statt ein generischer
Parameter:

```python
@dataclass(frozen=True)
class Quantifier:
    kind: str
    value: int | None = None

@dataclass(frozen=True)
class SemanticFrame:
    intent: str
    target: TargetReference | None
    area: AreaReference | None
    quantifier: Quantifier | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""
```

`QuantifierParser` (parsers.py) setzt jetzt `quantifier=Quantifier(kind=quantifier)`
statt `parameters={"quantifier": quantifier}`. `value` bleibt für "alle"/"beide"
immer `None` - es ist laut Plan für spätere v3-Quantor-Arten reserviert (z.B.
"die drei Lampen" -> `kind="count", value=3`), die dieses Upgrade nicht baut.

Die eigentliche Matching-Logik (`{domain}`/`{area}`/`{quantifier}`-Grammatik,
"beide" erzwingt exakt 2 Treffer, "alle" wählt alle passenden Entities,
Raumbezug optional) war bereits aus dem v1.1-Upgrade vorhanden und
unverändert korrekt - dieser Schritt ist eine reine Typ-Formalisierung,
keine Verhaltensänderung.

## Was bewusst NICHT gemacht wurde

**Keine neuen Quantor-Formen** ("die drei Lampen", "die ersten zwei", "nur
die Lampen", "alle außer ...") - der Plan nennt diese explizit als "später"
(v3, siehe Brain-Knoten "hierarchische Locations, natürliche Quantifier,
relative Referenzen"). `Quantifier.value` existiert bereits strukturell
dafür, wird aber von keinem Parser befüllt.

**Kein Downstream-Verbraucher von `frame.quantifier`** - wie schon der alte
`parameters["quantifier"]`-Wert wird das Feld nirgends außerhalb des Frames
ausgewertet (`service_call.py`/`engine.py` bauen den ServiceCallPlan weiterhin
allein aus der bereits aufgelösten Entity-Liste). Das ist unverändert zum
Vorzustand, keine Regression.

## Tests

Keine neue Testdatei - `Quantifier` folgt demselben Muster wie
`TargetReference`/`AreaReference` und wird über deren bestehende Abdeckung in
`tests/test_semantic_frame.py` mitgeprüft (2 Assertions dort umgestellt:
`result.frame.quantifier == Quantifier(kind=...)` statt
`result.frame.parameters == {"quantifier": ...}`).

**Ergebnis:** 328/328 Tests grün (keine neuen Tests, 2 bestehende Assertions
angepasst), `pytest -q` Laufzeit weiterhin < 1s. `pyflakes` clean.
