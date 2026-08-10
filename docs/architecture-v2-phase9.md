# v2-Umbau, Phase 9: Capability System

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Quantifier, Capability,
Command, Validator, ServiceMapper (Phasen 8-13)", Abschnitt "Phase 9 –
Capability System" - laut Plan der wichtigste v2-Schritt.
Vorstufe: `docs/architecture-v2-phase8.md` (Quantifier-System).

## Was neu ist

Neue Datei `nlu/capabilities.py`:

```python
class Capability(Enum):
    TURN_ON = auto()
    TURN_OFF = auto()
    BRIGHTNESS = auto()
    COLOR = auto()
    COLOR_TEMPERATURE = auto()
    POSITION = auto()
    TEMPERATURE = auto()
    HUMIDITY = auto()
    FAN_SPEED = auto()

def derive_capabilities(domain, device_class, attributes) -> frozenset[Capability]: ...
```

Jede Capability wird von einem konkreten HA-Signal abgeleitet, nie vom
Domain-Namen allein geraten:

- `light`/`switch`/`fan`: `TURN_ON`/`TURN_OFF` (HA-Basisvertrag dieser
  Domains).
- `light`: `supported_color_modes`-Attribut entscheidet granular -
  `brightness`/`hs`/`rgb`/`rgbw`/`rgbww`/`xy` → `BRIGHTNESS`, die
  Farb-Modi zusätzlich → `COLOR`, `color_temp` zusätzlich →
  `COLOR_TEMPERATURE`. Eine Lampe mit nur `["brightness"]` bekommt also
  `BRIGHTNESS`, aber nicht `COLOR` - genau der im Plan genannte
  Beispielfall ("Mach Lampe y blau" auf einer Nur-Helligkeit-Lampe).
- `cover`: `current_position`-Attribut vorhanden → `POSITION`.
- `fan`: `percentage`-Attribut vorhanden → `FAN_SPEED`.
- `sensor`: `device_class == "temperature"` → `TEMPERATURE`,
  `device_class == "humidity"` → `HUMIDITY`.

`derive_capabilities()` nimmt bewusst `domain`/`device_class`/`attributes`
als einzelne Werte statt eines vollen `EntitySnapshot` entgegen - dieselbe
"Eingaben vorbereiten, einmal konstruieren"-Form, die `hass_entities.py`
bereits für Aliase/Area nutzt (`_entity_aliases`/`_area_info`). Das
vermeidet eine Zwei-Schritt-Konstruktion, da das `capabilities`-Feld direkt
in den bereits vorhandenen lokalen `domain`/`device_class`/`state.attributes`-
Werten berechnet werden kann, bevor `EntitySnapshot(...)` einmal aufgerufen
wird.

`hass_entities.py`s `build_entity_snapshots()` befüllt jetzt das seit Phase
5 vorhandene, bis hierhin leere `EntitySnapshot.capabilities`-Feld (Typ
bleibt `frozenset[str]`, um `entities.py` frei von einem Import aus dem
`nlu`-Package zu halten - sonst Zirkelimport, da `nlu/capabilities.py`
bereits `EntitySnapshot`-Datenformen referenziert): `capabilities=frozenset(
c.name for c in derive_capabilities(domain, device_class, state.attributes))`.

## Was bewusst NICHT gemacht wurde

**Kein `climate`/`humidifier`-Support** - `TEMPERATURE`/`HUMIDITY` werden nur
für `sensor`-Entities mit passendem `device_class` abgeleitet (lesbarer
Zustand), nicht für ein Ziel-Temperatur-/Zielfeuchte-Setzen auf `climate`/
`humidifier`-Domains. Diese Domains existieren im Projekt noch nicht (siehe
Brain-Knoten "Domain-Erweiterungen Light/Cover/Fan/Climate", Phasen 14-19,
zukünftig) - Capabilities für sie jetzt zu raten wäre keine Ableitung aus
echten Daten, sondern eine Vorwegnahme nicht existierender Funktionalität.

**Kein Verbraucher des neuen Felds** - der Command Validator, der
`Capability`-Prüfungen tatsächlich durchsetzt (`UNSUPPORTED_CAPABILITY`),
ist Phase 11 (nächste Phase). Bis dahin wird `EntitySnapshot.capabilities`
zwar korrekt befüllt, aber von keinem Parser/Intent-Spec gelesen - reine
Datengrundlage, wie bei den entsprechenden Vorstufen üblich (z.B. Phase 5s
Alias-Feld vor Phase 6s Resolver).

## Tests

Neue Datei `tests/test_capabilities.py` (12 Tests): pinnt jede
Domain/Signal-Kombination einzeln (Licht ohne Farbmodi, nur Helligkeit, Farbe,
Farbtemperatur, Schalter, Rollladen mit/ohne Position, Ventilator mit/ohne
Stufe, Sensor mit Temperatur-/Feuchte-Device-Class, Sensor ohne passende
Device-Class).

**Ergebnis:** 340/340 Tests grün (328 aus Phase 8 + 12 neu),
`pytest -q` Laufzeit weiterhin < 1s. `pyflakes` clean.
