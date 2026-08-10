# v2-Umbau, Phase 11: Command Validator

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Quantifier, Capability,
Command, Validator, ServiceMapper (Phasen 8-13)", Abschnitt "Phase 11 –
Command Validator".
Vorstufe: `docs/architecture-v2-phase10.md` (Semantic Commands).

## Was neu ist

Neue Datei `nlu/validator.py`:

```python
class ValidationError(Enum):
    UNKNOWN_INTENT = auto()
    ENTITY_NOT_FOUND = auto()
    AMBIGUOUS_ENTITY = auto()
    AREA_NOT_FOUND = auto()
    INVALID_DOMAIN = auto()
    UNSUPPORTED_CAPABILITY = auto()
    MISSING_PARAMETER = auto()
    INVALID_PARAMETER = auto()
    INVALID_QUANTIFIER = auto()

def validate_command(command: SemanticCommand) -> ValidationError | None: ...
```

Prüft die 9 vom Plan vorgegebenen Fehlerklassen in der dort genannten
Reihenfolge, gibt den ersten verletzten Fehler zurück (oder `None`, wenn das
Command sicher ausführbar ist).

## Warum dieser Validator jetzt gebaut wird, obwohl er (noch) nichts prüft, was nicht schon geprüft wird

Die drei bestehenden hassil-Parser (`SingleTargetParser`/`QuantifierParser`/
`PercentageParser`) policen sich selbst bereits fast vollständig - sie geben
`None` zurück, *bevor* überhaupt ein Frame/Command entsteht, sobald
Entity-Resolution fehlschlägt, Mehrdeutigkeit auftritt, die Domain falsch
ist, ein Raum nicht auflöst, eine Quantor-Anzahl nicht passt, oder der
Intent nicht registriert ist. Ein `SemanticCommand`, das eine dieser 8
Regeln verletzt, kann der heutige Code faktisch gar nicht erzeugen.

Der Grund, trotzdem jetzt schon den vollständigen Validator zu bauen: der
Plan sieht für eine spätere Phase (LLM Adapter, Brain-Knoten "LLM Adapter,
Hybrid-Modus, LLM-Sicherheitsregeln, Phasen 30-31") explizit vor, dass
LLM-Output *immer* untrusted Input ist und vollständig validiert werden
muss. Ein zukünftiger LLM-basierter Parser wird sich nicht wie die
heutigen drei Parser selbst policen - er braucht diesen Validator als
echten Torwächter. Das ist dasselbe "Datenschicht zuerst, Verbraucher
später"-Muster wie schon bei Phase 5→6 (Alias-Feld vor Resolver), 9→11
(Capability-Feld vor diesem Validator) und 10→11 (Command-Struktur vor
diesem Validator).

Die eine Prüfung mit tatsächlich null heutiger Durchsetzung - und damit der
konkret wertvollste Teil dieser Phase - ist `UNSUPPORTED_CAPABILITY`: kein
bestehender Parser liest `EntitySnapshot.capabilities` überhaupt.

## Die 9 Prüfungen im Detail

1. **UNKNOWN_INTENT** - `command.intent` ist weder das uniforme
   `"HassSetPercentage"` noch in `QUERY_INTENTS` noch in `INTENTS`
   registriert.
2. **ENTITY_NOT_FOUND** - `command.entities` ist leer.
3. **AMBIGUOUS_ENTITY** - kein Quantifier (`frame.quantifier is None`), aber
   mehr als eine aufgelöste Entity. Echte Mehrdeutigkeit während der
   Resolution erreicht heute nie ein `SemanticCommand` (`resolve_entity()`
   liefert dafür schon vorher NOT_FOUND) - dies ist die einzige Form, in der
   sich die Invariante an einem fertigen Command noch feststellen lässt.
4. **AREA_NOT_FOUND** - der Nutzer hat einen Raum genannt
   (`frame.area is not None`), aber er hat nie zu einem `AreaSnapshot`
   aufgelöst (`command.area is None`).
5. **INVALID_DOMAIN** - eine Ziel-Entity-Domain ist nicht in den für den
   Intent erlaubten Domains. Da `PERCENT_INTENTS` (anders als `INTENTS`/
   `QUERY_INTENTS`) nach *Domain* statt nach Intent-Name organisiert ist
   (siehe `service_call.py`s eigener Kommentar dazu), sind die "erlaubten
   Domains" für `HassSetPercentage` schlicht `PERCENT_INTENTS.keys()`.
6. **UNSUPPORTED_CAPABILITY** - für Prozent-Commands: die Ziel-Entity muss
   die domain-passende Capability besitzen (`cover` → `POSITION`, `light` →
   `BRIGHTNESS`).
7. **MISSING_PARAMETER** - ein Prozent-Command ohne `"percent"` in
   `command.parameters`.
8. **INVALID_PARAMETER** - der Prozentwert ist kein `int` oder liegt
   außerhalb `0-100` (bei den heutigen Parsern bereits durch
   `RangeSlotList`/den expliziten Guard in `PercentageParser` strukturell
   garantiert - hier eine bewusste Doppelprüfung für einen Validator, der
   auch nicht-selbstpolizierende Aufrufer bedienen soll).
9. **INVALID_QUANTIFIER** - `kind == "both"`, aber nicht genau 2 aufgelöste
   Entities.

## Was bewusst NICHT gemacht wurde

**Kein Verbraucher in `engine.py`/`parsers.py`** - `validate_command()`
wird von keinem Live-Pfad aufgerufen. Laut Plan ist das explizit Aufgabe von
Phase 12 ("ServiceCallPlan wird erst nach erfolgreicher semantischer
Validierung erzeugt", `SemanticCommand → ServiceMapper → ServiceCallPlan`) -
diese Phase liefert nur den Validator selbst, das Threading in die laufende
Pipeline ist der nächste Schritt.

**Kein 10. Fehlercode für "Command sicher ausführbar"** - der Plan listet
diese Frage als 10. Prüfschritt, aber sie hat keine eigene Fehlerklasse
unter den 9 vom Plan genannten `ValidationError`-Werten - sie beschreibt
das Gesamturteil (`None`-Rückgabe), keinen eigenen Fehlerfall.

**Keine Prüfung auf Intent/Domain-Konsistenz jenseits der 3 Registries** -
der Validator kennt nur die bestehenden `INTENTS`/`QUERY_INTENTS`/
`PERCENT_INTENTS`-Strukturen aus `service_call.py`, keine eigene, parallele
Intent-Definition. Eine künftige Domain-Erweiterung (Climate, Farbe, ...)
erweitert diese Registries direkt - der Validator liest sie nur.

## Tests

Neue Datei `tests/test_validator.py` (17 Tests), zwei Gruppen:

- **Reale Matches** (über `engine`/die bestehenden Fixtures) müssen immer
  sauber validieren (`None`) - Regressionsschutz, dass der Validator nichts
  Legitimes ablehnt. Für den Prozent-Fall wird bewusst eine dedizierte
  Entity mit gesetzten Capabilities gebaut statt der geteilten
  `entities`-Fixture, da diese (vor Phase 9 entstanden) keine Capabilities
  trägt - `hass_entities.py` ist der einzige Ort, der sie aus echten HA-
  Attributen befüllt.
- **Synthetische Commands**, ein Test pro Fehlerklasse - da die aktuellen
  Parser keinen davon tatsächlich erzeugen können, werden `SemanticCommand`/
  `SemanticFrame` direkt von Hand gebaut.

**Ergebnis:** 362/362 Tests grün (345 aus Phase 10 + 16 neu + 1 aus Phase
9/10 Zwischenstand), `pytest -q` Laufzeit weiterhin < 2s. `pyflakes` clean.
