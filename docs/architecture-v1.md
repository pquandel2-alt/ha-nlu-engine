# Architektur v1 (Baseline vor v2→v3-Umbau)

Stand: 2026-08-09, Commit `b9a02eb` (Tag `v2.0.0` der HACS-Manifest-Version — nicht zu
verwechseln mit dem "v1"/"v2"/"v3" dieses Dokuments, das sich auf die *NLU-Architektur*
bezieht, siehe Abkürzung unten). 282 Tests grün (`pytest -q`, Laufzeit < 1s).

Dieses Dokument ist die in Phase 0 des Entwicklungsplans "ha-nlu-engine v2 → v3"
(siehe Brain-Knoten "ha-nlu-engine Plan: Implementierungsreihenfolge (01-31) &
Ausführungsprotokoll") geforderte Baseline-Dokumentation. Es beschreibt den Zustand
**vor** jeder SemanticFrame-/Resolver-2.0-/Capability-Umstellung, als Referenz und
Regressionsschutz für den anschließenden Umbau.

**Begriffsklärung:** "v1" hier meint die aktuelle, primär hassil-YAML-Pattern-basierte
Architektur (Text → hassil-Match → Entity-Resolve → ServiceCall). Das ist unabhängig von
der HACS-Manifest-Version (aktuell `2.0.0`) und von der Plan-Terminologie "v2"/"v3", die
sich auf die künftige SemanticFrame-Pipeline bezieht.

## 1. Datenfluss (aktuell)

```
HA Assist Chat-UI
        │
        ▼
NluConversationEntity._async_handle_message()   (conversation.py)
        │
        ├─ build_entity_snapshots(hass, entry)  (hass_entities.py)
        │      → list[EntitySnapshot]  (frischer Snapshot pro Anfrage)
        │
        ▼
NluEngine.match(text, entities)                 (engine.py)
        │
        ├─ 1. _normalize_percent_symbol(text)    ("30%" → "30 Prozent")
        ├─ 2. Router (Regex-Vorcheck, keine Scoring-Logik):
        │       "prozent" im Text?     → _match_percentage()
        │       "alle|beide[nr]?"?     → _match_quantifier()
        │       sonst                  → _match_single()
        │
        ▼
MatchResult(plan: ServiceCallPlan | None, response_text: str)  |  None
        │
        ▼
conversation.py: falls plan is not None → hass.services.async_call(...)
                 immer                  → response.async_set_speech(response_text)
```

Es gibt **keine** Zwischenrepräsentation zwischen hassil-Match und ServiceCall (kein
SemanticFrame, kein SemanticCommand) — das matched Ergebnis wird direkt in einen
`ServiceCallPlan` übersetzt. Genau das soll der v2-Umbau ändern (Phase 1: SemanticFrame).

## 2. Öffentliche Klassen/Funktionen je Modul

### `entities.py`
- `EntitySnapshot` (frozen dataclass): `entity_id`, `friendly_name`, `domain`, `state`,
  `area_id: str | None = None`, `area_name: str | None = None`, `unit: str | None = None`.
  Kein `device_class`, kein `capabilities`-Feld, keine `aliases` — Entity-Modell ist
  bewusst minimal (nur was aktuell gebraucht wird).
- `ResolveStatus` (Enum): `OK`, `AMBIGUOUS`, `NOT_FOUND`.
- `ResolveResult` (frozen dataclass): `status`, `entity: EntitySnapshot | None`,
  `candidates: tuple[EntitySnapshot, ...]`.
- `build_name_map(entities) -> dict[str, list[EntitySnapshot]]` — lowercased
  friendly_name → Liste (Duplikate werden nicht kollabiert, sondern bleiben als
  AMBIGUOUS-Kandidaten sichtbar).
- `resolve_entity(name, entities) -> ResolveResult` — siehe Abschnitt 4.
- `resolve_entities_by_domain(domain, entities, area_id=None) -> list[EntitySnapshot]` —
  kein Ambiguity-Konzept, liefert alle Treffer sortiert nach `entity_id`.

### `areas.py`
- `AreaResolveStatus` (Enum): `OK`, `AMBIGUOUS`, `NOT_FOUND`.
- `AreaResolveResult` (frozen dataclass): `status`, `area_id: str | None`,
  `candidates: tuple[str, ...]`.
- `resolve_area_name(name, entities) -> AreaResolveResult` — spiegelt den
  `resolve_entity`-Algorithmus 1:1, aber auf `area_name`/`area_id` von
  `EntitySnapshot` statt auf Entity-Namen. Kein separater Registry-Zugriff, baut
  ausschließlich auf den bereits übergebenen Snapshots auf (bleibt hass-frei).

### `engine.py`
- `MatchResult` (frozen dataclass): `plan: ServiceCallPlan | None`,
  `response_text: str`. `plan is None` bedeutet reine Sprachausgabe ohne
  Service-Call (aktuell nur für `HassGetState`-Sensor-Abfragen genutzt).
- `NluEngine`:
  - `__init__` lädt beim Setup **drei getrennte** `hassil.Intents`-Objekte aus drei
    Verzeichnissen (`intents/de/*.yaml`, `intents/de/quantifiers/*.yaml`,
    `intents/de/percentage/*.yaml`) — je ein `FileNotFoundError`-Guard bei leerem Glob.
  - `match(text, entities) -> MatchResult | None` — öffentlicher Einstiegspunkt,
    normalisiert zuerst das `%`-Zeichen, dann reiner Router (keine Matching-Logik
    selbst), delegiert an eine der drei `_match_*`-Methoden.
  - `_match_single(text, entities)` — Standardfall: `{name}`-Wildcard-Match gegen
    `self._intents`, Namen-Resolution, Domain-Guard gegen `INTENTS`/`QUERY_INTENTS`.
  - `_match_quantifier(text, entities)` — `{domain}`/`{area}`/`{quantifier}`-Slots
    gegen `self._quantifier_intents`, Area-Resolution optional, "beide" erzwingt
    genau 2 Treffer.
  - `_match_percentage(text, entities)` — `{name}`/`{percent}`-Slots (RangeSlotList,
    `RangeType.PERCENTAGE`) gegen `self._percentage_intents`, Domain wird **nach**
    der Namensauflösung aus der tatsächlich aufgelösten Entity bestimmt (nicht aus
    dem Intent-Namen — siehe `PERCENT_INTENTS`-Doku in `service_call.py`).
- Modul-Level-Helfer: `_normalize_percent_symbol`, `_strip_locative_prepositions`,
  zwei `TextSlotList`-Konstanten (`_DOMAIN_SLOT_LIST`, `_QUANTIFIER_SLOT_LIST`), drei
  Router-Regexe (`_PERCENT_RE`, `_PERCENT_SYMBOL_RE`, `_QUANTIFIER_RE`).

### `service_call.py`
- `ServiceCallPlan` (frozen dataclass): `domain`, `service`,
  `entity_id: str | list[str]`, `data: dict = {}`.
- `IntentSpec` (frozen dataclass): `allowed_domains: frozenset[str]`,
  `build: Callable[[list[EntitySnapshot]], ServiceCallPlan]`,
  `response: Callable[[list[EntitySnapshot]], str]`.
- `INTENTS: dict[str, IntentSpec]` — 5 Einträge: `HassTurnOn`, `HassTurnOff`,
  `HassToggle` (Domains `light`/`switch`/`fan`, Service `homeassistant.turn_on/off/toggle`),
  `HassOpenCover`, `HassCloseCover` (Domain `cover`, Service `cover.open_cover`/`close_cover`).
- `PercentIntentSpec` (frozen dataclass): eigene Signatur mit zusätzlichem
  `int`-Parameter (`build`/`response` nehmen `(entities, percent)`).
- `PERCENT_INTENTS: dict[str, PercentIntentSpec]` — **Schlüssel ist die Domain**
  (`"cover"`, `"light"`), nicht ein Intent-Name (siehe Abschnitt 5).
- `QueryIntentSpec` (frozen dataclass): `allowed_domains`,
  `response: Callable[[list[EntitySnapshot]], str]` — kein `build`, Queries erzeugen
  nie einen ServiceCallPlan.
- `QUERY_INTENTS: dict[str, QueryIntentSpec]` — 1 Eintrag: `HassGetState`
  (Domain `sensor`, spricht `state + Einheit`).
- Helfer: `_entity_id_field` (String bei 1 Entity, Liste bei mehreren),
  `_plural_response` (TTS-freundliche Kurzantwort bei Mehrfachtreffern),
  `_speak_state`/`_UNIT_SPOKEN_DE` (Einheiten-Aussprache, unbekannte Einheiten roh
  gesprochen statt Crash).

### `conversation.py`
- `NluConversationEntity(conversation.ConversationEntity, conversation.AbstractConversationAgent)`
  — `_attr_supported_features = ConversationEntityFeature.CONTROL` (nötig, damit HA den
  "kann dein Zuhause nicht steuern"-Banner nicht anzeigt). `supported_languages` fest
  `["de"]`. `_async_handle_message`: baut pro Anfrage frische `EntitySnapshot`-Liste,
  ruft `engine.match()`, führt bei `plan is not None` genau einen `services.async_call`
  aus (blocking, mit try/except → `FAILED_TO_HANDLE` bei HA-seitigem Fehler), spricht
  immer `response_text`.

### `config_flow.py` / `__init__.py` / `const.py`
- `HaNluConfigFlow`/`HaNluOptionsFlow`: Single-Instance, keine Pflichtfelder beim
  Setup; Options-Flow erlaubt explizite Entity-Auswahl (`EntitySelector`,
  `domain=SELECTABLE_DOMAINS`), Default = alle für Assist exponierten Entities dieser
  Domains.
- `SELECTABLE_DOMAINS = ("light", "switch", "fan", "cover", "sensor")`.
- `NOT_UNDERSTOOD_TEXT = "Das habe ich nicht verstanden."` — einzige Fehlermeldung im
  gesamten System, unabhängig vom Fehlergrund (kein Fehlerklassen-Konzept, das kommt
  erst mit Phase 11/Validator).

### `hass_entities.py`
- `default_exposed_entities(hass)` — alle `SELECTABLE_DOMAINS`-Entities, die
  `async_should_expose` für die `conversation`-Domain bejaht.
- `get_selected_entity_ids(hass, entry)` — explizite Options-Auswahl gewinnt, sonst
  Fallback auf `default_exposed_entities`.
- `_area_info(hass, entity_id)` — Standard-Fallback-Kette Entity-Registry →
  Device-Registry → Area-Registry.
- `build_entity_snapshots(hass, entry) -> list[EntitySnapshot]` — einziger Ort, an dem
  `EntitySnapshot` mit echten HA-Daten befüllt wird; **kein Caching**, wird bei jeder
  einzelnen Conversation-Anfrage neu aus `hass.states`/Registries aufgebaut (siehe
  Einschränkung Performance in Abschnitt 6 — genau der Punkt, den Plan-Phase 23
  adressieren soll).

## 3. Intent-Grammatiken (hassil YAML)

Drei komplett getrennt kompilierte `hassil.Intents`-Objekte, weil dieselbe
`{name}`-Wildcard sonst mehrdeutig gegen mehrere Grammatiken matchen würde
(siehe Docstring in `engine.py`):

| Verzeichnis | Datei(en) | Intents | Slots |
|---|---|---|---|
| `intents/de/` | `cover.yaml`, `light_switch.yaml`, `query.yaml` | `HassOpenCover`, `HassCloseCover`, `HassTurnOn`, `HassTurnOff`, `HassToggle`, `HassGetState` | `{name}` (WildcardSlotList) |
| `intents/de/quantifiers/` | `cover_all.yaml`, `light_switch_all.yaml` | dieselben 5 Aktions-Intents, quantor-Variante | `{domain}` (TextSlotList), `{area}` (WildcardSlotList), `{quantifier}` (TextSlotList) |
| `intents/de/percentage/` | `position_brightness.yaml` | `HassSetPercentage` (ein generischer Intent für Cover-Position **und** Licht-Helligkeit) | `{name}` (WildcardSlotList), `{percent}` (RangeSlotList, 0-100) |

Wichtige Grammatik-Details:
- `[a|b]` in hassil ist **optional** (`is_optional=True`), `(a|b)` ist **erforderlich**.
  Diese Unterscheidung war Ursache eines realen Bugs (siehe Abschnitt 6/Git-Historie:
  Commit `b9a02eb`) — bei neuen YAMLs immer bewusst wählen.
- Präpositionen vor `{area}`/`{name}` (`in der|in dem|im|am|beim`) werden in den
  Sentence-Templates mitgefangen und danach in Python per
  `_strip_locative_prepositions()` entfernt — hassil selbst trennt sie nicht ab.
- "auf" vor `{percent}` ist in allen Percentage-Templates ein **Pflicht-Literal**,
  nie optional — sonst verschluckt die `{name}`-Wildcard führende Ziffern (siehe
  Abschnitt 6, Wildcard-Bug).

## 4. Entity Resolution (aktueller Algorithmus)

`resolve_entity(name, entities)` in `entities.py`, portiert aus `xiaozhi_entity_mcp`:

1. Exakter Match auf lowercased `friendly_name`. Mehrere Entities mit demselben
   Namen → `AMBIGUOUS` (kein "first/last wins").
2. Sonst case-insensitiver Contains-Match, **in beide Richtungen** geprüft:
   gesprochener Name als Substring des Friendly Name (z.B. "Büro" matcht
   "Rolllade Büro") ODER Friendly Name als Substring des gesprochenen Namens
   (z.B. "Rollladen Wohnzimmer" matcht eine Entity, die nur "Wohnzimmer" heißt).
   Auch hier: mehrdeutig → `AMBIGUOUS`, kein Treffer → `NOT_FOUND`.
3. Kein Scoring, kein Ranking, keine Gewichtung nach Länge/Ähnlichkeit — jeder Treffer
   zählt gleich, Mehrdeutigkeit wird nie zugunsten eines "wahrscheinlicheren"
   Kandidaten aufgelöst. Das ist exakt der Zustand, den Plan-Phase 6 ("Entity
   Resolver 2.0" mit Scoring/Context-Filtering) ablösen soll.

`resolve_area_name(name, entities)` in `areas.py` ist strukturell identisch, nur auf
`area_name`/`area_id` statt `friendly_name`/`entity_id`.

## 5. ServiceCall-Erzeugung

Kein separater Mapper: `IntentSpec.build`/`PercentIntentSpec.build`/
`QueryIntentSpec.response` sind Lambdas direkt im `INTENTS`/`PERCENT_INTENTS`/
`QUERY_INTENTS`-Dict in `service_call.py`, aufgerufen unmittelbar nachdem
`engine.py` eine Entity (oder Entity-Liste) aufgelöst hat. Domain-Validierung
(„ist diese Entity-Domain für diesen Intent erlaubt?") passiert als einfacher
`in spec.allowed_domains`-Check, kein Capability-Konzept (z.B. "hat dieses Licht
überhaupt eine Farbfunktion?" wird nicht geprüft — es gibt aktuell auch keine
Licht-Farbsteuerung).

Besonderheit Prozent-Dispatch: `PERCENT_INTENTS` ist nach der **aufgelösten
Entity-Domain** geschlüsselt, nicht nach dem gematchten hassil-Intent-Namen — weil
generische deutsche Verben ("stelle", "setze") sowohl für Rollladen-Position als
auch Licht-Helligkeit verwendet werden und ein Verb-basierter Split entweder gültige
Formulierungen ablehnt oder (schlimmer) leise falsch routet. Damit ist "Domain
bestimmt Service" ein Vorgriff auf das, was Plan-Phase 13 (Service Mapper) generell
für alle Intents einführen soll.

## 6. Bekannte Einschränkungen (Stand v1, vor v2-Umbau)

- **Keine Zwischenrepräsentation** zwischen Match und ServiceCall (kein
  SemanticFrame/SemanticCommand) — Grund für Plan-Phase 1/2.
- **Kein Scoring/Ranking bei Entity Resolution**, nur exact/contains/ambiguous —
  Grund für Plan-Phase 6 (Entity Resolver 2.0).
- **Kein Alias-System** — nur `friendly_name` (aus `state.attributes.friendly_name`
  oder `entity_id`-Fallback), keine konfigurierbaren Zusatznamen — Grund für
  Plan-Phase 5.
- **Kein Capability-Konzept** — Domain-Zugehörigkeit ist die einzige Prüfung, es gibt
  keine Prüfung einzelner Fähigkeiten (Farbe, Farbtemperatur, Fan-Stufen, Climate) —
  Grund für Plan-Phase 9. Entsprechend fehlt Licht-Farbsteuerung, Fan-Steuerung,
  Climate-Steuerung komplett (nur `light`/`switch`/`fan`(nur an/aus)/`cover` An-Aus
  und `cover`/`light`-Prozent sind implementiert; Fan hat aktuell **keine**
  Geschwindigkeitsstufen-Unterstützung trotz Domain-Zulassung in `INTENTS`).
- **Keine Rückfragen/Conversation Context** — bei `AMBIGUOUS` oder `NOT_FOUND` wird
  immer sofort und ausschließlich `NOT_UNDERSTOOD_TEXT` gesprochen, es gibt keinen
  Dialog-Turn, der die Mehrdeutigkeit klärt — Grund für Plan-Phasen 20-22.
  Ebenso keine Pronomen-/Referenzauflösung ("mach es aus").
- **Kein hierarchisches Location-Modell** — nur direkte HA-Areas, kein
  Haus/Etage/Raum — Grund für Plan-Phase 28 (v3).
- **Quantifier nur "alle"/"beide"** (fest verdrahtet, kein generisches
  `Quantifier(kind, value)`-Modell) — Grund für Plan-Phase 8.
- **Keine Performance-Vorkehrungen**: `build_entity_snapshots()` baut bei **jeder**
  einzelnen Conversation-Anfrage die komplette Snapshot-Liste inkl. Area-Registry-
  Lookups pro Entity neu auf; es gibt kein Indexing (normalized_name→entities,
  area→entities, ...) — bislang unproblematisch (Reaktionszeit laut Nutzer
  "geradezu sofort" bei realistischer Entity-Anzahl), aber nicht O(1)/indiziert.
  Grund für Plan-Phase 23.
- **Kein Debug-Modus** — keine strukturierte Logging-Ausgabe des Matching-Pfads
  (Candidates/Scores/Resolution/Validation) — Grund für Plan-Phase 22.
- **Keine Golden-Test-Sammlung** — Tests sind Unit-Tests pro Modul/Feature
  (`tests/test_engine_*.py`, `tests/test_*_resolution.py`), keine kuratierte
  Sammlung realer Sprachbefehle mit erwarteten strukturierten Ergebnissen — Grund
  für Plan-Phase 20 (Golden Tests).
- **`hass_entities.py` bleibt ungetestet** (kein Mocking-Setup für eine echte `hass`-
  Instanz im Repo) — muss weiterhin manuell gegen die reale HA-Instanz verifiziert
  werden; dieser Zustand ändert sich durch den v2-Umbau nicht automatisch.
- **Nur Deutsch** (`supported_languages` fest `["de"]`), nur eine Sensor-Query-Form
  ("wie hoch/warm/kalt ist ..."), keine Ja/Nein-Zustandsabfragen ("ist die Tür
  offen?").

## 7. Testabdeckung (Baseline)

```
tests/conftest.py               – Fixtures (ALL_ENTITIES, QUANTIFIER_ENTITIES, SENSOR_ENTITIES, engine/entities-Fixtures)
tests/test_entity_resolution.py – resolve_entity() (exact/contains/ambiguous/not_found/domain-filter)
tests/test_area_resolution.py   – resolve_area_name() (gleiches Muster für Areas)
tests/test_engine_lights.py     – HassTurnOn/Off/Toggle gegen light/switch/fan
tests/test_engine_covers.py     – HassOpenCover/CloseCover
tests/test_engine_quantifiers.py– "alle"/"beide", Area-Filter, Zählregel für "beide"
tests/test_engine_percentage.py– HassSetPercentage (Cover-Position, Licht-Helligkeit, %-Symbol, Domain-Routing)
tests/test_engine_query.py      – HassGetState (Sensor-Zustandsabfrage)

282 Tests total, 0 failures, Laufzeit < 1s (pytest -q).
```

Dies ist der Testbestand, der laut Plan-Regel 1 ("Bestehende Tests niemals ohne
Begründung löschen") und Akzeptanzkriterium von Phase 0 als Referenzpunkt für alle
folgenden Phasen dient — nach jeder Phase muss diese Zahl (oder mehr, bei
begründeten Ersetzungen) weiterhin grün sein.
