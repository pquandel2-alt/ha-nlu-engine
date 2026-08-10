# v2-Umbau, Phase 18: Query Engine

Referenz: Brain-Knoten "ha-nlu-engine v2 Plan: Domain-Erweiterungen
Light/Cover/Fan/Climate/Query & Response (Phasen 14-19)", Abschnitt "Phase
18 - Query Engine". Vorstufe: `docs/architecture-v2-phase16.md` (Climate-NLU).

## Ausgangslage: das meiste war schon da, nur `light`-Helligkeit fehlte

`HassGetState` (Sensor-Zustandsabfragen, "wie hoch ist die
Außentemperatur?") existiert bereits seit dem ursprünglichen Prozent/
Quantoren/Query-Upgrade (`QUERY_INTENTS` in `service_call.py`,
`_speak_state()` mit `_UNIT_SPOKEN_DE`). Der Plan nennt für Phase 18 sieben
Query-Typen (STATE, TEMPERATURE, HUMIDITY, BRIGHTNESS, POWER, ENERGY,
BATTERY) als Vokabular der "Query Engine". Sechs davon werden bereits
korrekt beantwortet - `_speak_state()` liest `state` + `unit` roh und
spricht sie, unabhängig vom `device_class`, das war schon immer
"typ-agnostisch richtig". Nur **BRIGHTNESS** war strukturell neu: ein Licht
meldet Helligkeit nicht über `state` (das ist nur "on"/"off"), sondern über
das rohe HA-Attribut `attributes["brightness"]` (0-255) - und `light` war
bislang gar nicht in `QUERY_INTENTS["HassGetState"].allowed_domains`
enthalten ("wie hell ist die Wohnzimmer Decke?" lief bisher ins Leere).

## Was neu ist

Neues Modul `nlu/query.py`: `QueryType`-Enum (die sieben Plan-Typen) plus
`derive_query_type(entity) -> QueryType`, deterministisch aus
`domain`/`device_class` abgeleitet - dieselbe "das reale Signal lesen, nie
aus dem Satz/Intent-Namen raten"-Regel, die `nlu/capabilities.py` für
`Capability` schon durchsetzt:

```python
def derive_query_type(entity: EntitySnapshot) -> QueryType:
    if entity.domain == "light":
        return QueryType.BRIGHTNESS
    return _DEVICE_CLASS_QUERY_TYPE.get(entity.device_class or "", QueryType.STATE)
```

`service_call.py` bekommt `_speak_brightness()` (state "off" → "aus.";
state "on" ohne `brightness`-Attribut, z.B. reine Ein/Aus-Lampen → "an.";
sonst `brightness/255` in Prozent gerundet gesprochen) und einen
`_speak_query()`-Dispatcher, der bei `QueryType.BRIGHTNESS` auf
`_speak_brightness()` verzweigt und sonst unverändert `_speak_state()`
aufruft. `QUERY_INTENTS["HassGetState"].allowed_domains` wird um `"light"`
erweitert, `.response` zeigt jetzt auf `_speak_query` statt direkt auf
`_speak_state`.

`intents/de/query.yaml`: "hell" zur bestehenden Adjektiv-Alternation
hinzugefügt ("wie [hoch|warm|kalt|hell] ist ..."). Keine neue Grammatik,
keine neue Routing-Regex nötig - dieselbe generische `{name}`-Wildcard-
Grammatik im bereits geladenen `self._intents`-Objekt deckt jetzt auch
Licht-Helligkeit ab, exakt wie beim ursprünglichen Query-Entwurf
vorgesehen ("kein Kollisionsrisiko, da Abfrage-Sätze mit 'wie ...'
beginnen, das in keinem Aktions-Satz vorkommt").

## Kein neuer hassil-Bug, keine neue Routing-Kollision

Geprüft, dass `\bhell\b` (neu in `query.yaml`) nicht versehentlich in
`heller`/`dunkler` matcht (die `_LIGHT_EXTENDED_RE`-Schlüsselwörter aus
Phase 14/`light_extended`): Wortgrenzen-Semantik von `\b` verhindert das
strukturell, `heller` enthält `hell` nicht als eigenes Wort. Da `query.yaml`
ohnehin nur im generischen `self._intents`-Pfad landet (kein eigener
Regex-Dispatch-Zweig wie bei den separat kompilierten Grammatiken), gibt es
hier auch keine neue Reihenfolge-Frage zu klären.

## Bewusste Entwurfsentscheidung: kein eigenes `QueryCommand`

Der Plan illustriert Phase 18 mit einer eigenen `QueryCommand`-Struktur
(`query_type`, `entities`, `parameters`) parallel zu `SemanticCommand`. Das
wurde bewusst **nicht** umgesetzt: der Plan selbst verlangt an derselben
Stelle, dass "Queries dieselbe semantische Pipeline verwenden müssen wie
Commands" - und das ist mit der bestehenden `SemanticCommand`/
`MatchResult`-Pipeline (mit `plan=None` für reine Lese-Abfragen, seit dem
ursprünglichen Query-Entwurf etabliert) bereits erfüllt, ganz ohne
Parallelstruktur. `nlu/query.py`s `QueryType` ist bewusst schlank gehalten
- keine Command-Variante, sondern nur eine Klassifikation, die ausschließlich
an der Antwort-Formulierungsstelle (`_speak_query`) gelesen wird.

## Was bewusst NICHT gemacht wurde

**Keine neuen Antworttexte für TEMPERATURE/HUMIDITY/POWER/ENERGY/BATTERY** -
diese fünf Typen wurden schon vor Phase 18 korrekt durch die
`device_class`-agnostische `_speak_state()`-Logik (state + Einheit)
abgedeckt; `QueryType` existiert für sie heute nur als Klassifikation ohne
eigenen Verzweigungspfad, nicht weil sie fehlten, sondern weil sie schon
funktionierten. Sollte ein späterer Response-System-Schritt (Phase 19)
typspezifische Formulierungen brauchen, ist die Stelle zum Verzweigen
bereits vorbereitet (`_speak_query`).

**Kein `{name}`-freies "wie warm ist es hier"-Muster** - unverändert aus dem
ursprünglichen Query-Entwurf übernommen: ein solcher Satz würde `{name}`
mit Freitext statt einem Entity-Namen füllen und liefe strukturell nur
sauber ins NOT_FOUND, ohne Mehrwert.

## Tests

`tests/test_engine_query.py` um drei neue Fälle erweitert (lokale
Licht-Fixtures, kein Rückgriff auf `conftest.py` - analog zum bereits
etablierten Muster für domain-spezifische Tests in diesem Projekt):

- `DIMMED_LIGHT` (`brightness=128`, state "on") → "50 Prozent." (128/255
  gerundet)
- `ONOFF_LIGHT` (kein `brightness`-Attribut, state "on") → "an." (reine
  Ein/Aus-Lampe ohne Dimm-Fähigkeit, kein erfundener Wert)
- `OFF_LIGHT` (state "off", aber mit einem stale `brightness=255`-Attribut)
  → "aus." - pinnt, dass `state` immer Vorrang vor einem möglicherweise
  veralteten `brightness`-Attribut hat

Die fünf bereits bestehenden Sensor-Query-Tests (Außentemperatur,
Luftfeuchtigkeit Bad, unbekannte Entity, falsche Domain, Groß-/
Kleinschreibung) blieben unverändert grün - reines Regressions-Sicherheitsnetz
für die Erweiterung von `allowed_domains`.

**Ergebnis:** 411/411 Tests grün (408 aus Phase 17 + 3 neu), `pytest -q`
weiterhin < 2s. `pyflakes` clean.
