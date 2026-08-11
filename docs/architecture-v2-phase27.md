# v2-Umbau, Phase 28: Hierarchische Orte

Referenz: Brain-Knoten "ha-nlu-engine v3 Plan: ..." (Phase 28, "Hierarchical
Locations"), Beispielsatz aus dem Plan: *"Haus > Erdgeschoss (Wohnzimmer,
Küche) / Obergeschoss (Büro, Schlafzimmer). Dann 'alle Lichter oben'
möglich."* Vorstufe: `docs/architecture-v2-phase26.md` (Pronomen und
Referenzen).

## Ziel

Quantor-Befehle sollen sich nicht nur auf einen Raum (`{area}`), sondern auf
eine ganze Etage beziehen können - entweder namentlich ("alle Lichter im
Erdgeschoss") oder relativ ("alle Lichter oben"/"alle Lichter unten"). "Oben"
und "unten" haben keine feste, global angenommene Bedeutung (ein Haus mit
drei Etagen, ein Bungalow mit nur einer Etage) - sie werden ausschließlich
gegen die Etagen aufgelöst, die unter den tatsächlich übergebenen Entities
vorkommen, nie gegen ein angenommenes Gebäudelayout.

## `floors.py`: neues Modul, spiegelt `areas.py` 1:1

`FloorResolveStatus`/`FloorResolveResult`, `FloorSnapshot(floor_id, name,
level)`, `FloorResolutionStatus`/`FloorResolutionResult` und die 4-Tier-
Scoring-Konstanten (exact=100, normalisiert-exact=85, contains=50,
reverse-contains=40, `_AMBIGUITY_MARGIN=5`) sind wortwörtlich dieselbe
Struktur wie `areas.py` - hass-frei, baut die bekannten Etagen aus der
übergebenen `EntitySnapshot`-Liste (`e.floor_id`/`e.floor_name`), kein
zusätzlicher Live-Registry-Zugriff nötig.

Neu, ohne Pendant in `areas.py`: `resolve_floor_by_level_keyword(keyword,
entities)`. Löst `"up"`/`"down"` auf die Etage mit dem höchsten/niedrigsten
`level`-Wert unter den Etagen auf, die tatsächlich in `entities` vorkommen:

```python
floors = [f for f in _floor_snapshots(entities) if f.level is not None]
if not floors:
    return FloorResolveResult(status=FloorResolveStatus.NOT_FOUND)
extreme = max(f.level for f in floors) if keyword == "up" else min(...)
matching = [f for f in floors if f.level == extreme]
if len(matching) > 1:
    return FloorResolveResult(status=FloorResolveStatus.AMBIGUOUS, ...)
return FloorResolveResult(status=FloorResolveStatus.OK, floor_id=matching[0].floor_id)
```

Etagen ohne `level`-Wert werden ignoriert (nicht fälschlich als Extremwert
behandelt). Bei einem Unentschieden (zwei Etagen mit demselben Extremwert,
z.B. "Obergeschoss West"/"Obergeschoss Ost" beide `level=1`): `AMBIGUOUS`,
nie raten, welche gemeint ist.

## `entities.py`: drei neue optionale Felder + `floor_id`-Filter

`EntitySnapshot` bekommt `floor_id`/`floor_name`/`floor_level` (alle
`None`-Default, direkt hinter `area_name`) - additiv, keine bestehenden
positionalen Aufrufe brechen. `resolve_entities_by_domain()` bekommt einen
zusätzlichen optionalen `floor_id`-Parameter, UND-verknüpft mit `area_id`,
falls beide gesetzt sind.

## `QuantifierParser`: `{level}`-Slot + Area→Floor-Fallback-Kette

`_LEVEL_SLOT_LIST` (`parsers.py`) ist wie `_DOMAIN_SLOT_LIST`/
`_QUANTIFIER_SLOT_LIST` ein festes, geschlossenes Vokabular
(`"oben"→"up"`, `"unten"→"down"`) statt eines `{area}`-artigen Wildcards -
diese Wörter nehmen nie eine Präposition ("... oben an", nie "... im oben
an"), brauchen also keine `[in der|...]`-Gruppe.

Auflösungsreihenfolge in `QuantifierParser.parse()`:

1. `{area}`-Slot gefüllt → erst `resolve_area_name()`. `NOT_FOUND` → Fallback
   auf `resolve_floor_name()` (derselbe Slot deckt sowohl Raum- als auch
   Etagennamen ab, z.B. "im Erdgeschoss" ist kein Raum, aber eine Etage -
   keine eigene `{floor}`-Satzgruppe nötig). `AMBIGUOUS` wird **nie** als
   Etage weiterversucht - das würde eine echte Mehrdeutigkeit maskieren.
2. `{level}`-Slot gefüllt → `resolve_floor_by_level_keyword()`.
3. `resolve_entities_by_domain(domain, entities, area_id=area_id,
   floor_id=floor_id)`.

## Der eigentliche Bug: `{domain}`-Präfix-Kollision mit `{area}`-Wildcard

Die `{level}`-Sätze matchten in der echten Grammatik zunächst gar nicht -
"mach alle Lichter oben an" ergab `area: 'er oben'` statt `level: 'up'`.
Ursache, verifiziert direkt gegen `hassil.recognize()` mit der echten
YAML-Datei:

1. `hassil`s `TextSlotList`-Matching erzwingt **keine** Wortgrenze am Ende
   eines Werts (`match_start()` in `string_matcher.py` prüft nur, ob der
   Resttext mit dem Wert *beginnt*). "Licht" ist ein reiner Textpräfix von
   "Lichter" - stand "Licht" vor "Lichter" in `_DOMAIN_SLOT_LIST`, matchte
   es zuerst und ließ "er" als Rest stehen.
2. `recognize()` liefert das **erste** vollständige Match aus
   `recognize_all()` - Reihenfolge = Intent-/Satz-Deklarationsreihenfolge,
   und innerhalb eines `{domain}`-Slots die Deklarationsreihenfolge der
   Werte. Die `{area}`-Wildcard-Sätze standen vor den `{level}`-Sätzen in
   der YAML.
3. Kombiniert: für "Lichter oben" matchte "Licht" (Präfix), der Rest
   "er oben" fiel in die `{area}`-Wildcard-Erfassung des *vorher*
   deklarierten `{area}`-Satzes - ein strukturell gültiges, aber
   semantisch falsches Match, bevor der korrekte `{level}`-Satz je versucht
   wurde. `resolve_area_name("er oben", ...)` und der Floor-Fallback
   scheiterten beide (kein Raum/keine Etage heißt "er oben") →  `None`.

**Fix, zwei Teile:**

- `_DOMAIN_SLOT_LIST`: Pluralform vor Singularform bei jedem Wortpaar, bei
  dem die Singularform ein echter Textpräfix der Pluralform ist
  (Licht/Lichter, Lampe/Lampen, Steckdose/Steckdosen, Rollo/Rollos,
  Ventilator/Ventilatoren). Verhindert das Präfix-Matching an der Wurzel,
  nicht nur für den `{level}`-Fall.
- Satzreihenfolge in `light_switch_all.yaml`/`cover_all.yaml`: `{level}`-
  Sätze stehen jetzt vor den `{area}`-Wildcard-Sätzen, damit ein
  `{level}`-Wort nie in eine `{area}`-Erfassung durchrutschen kann, selbst
  wenn beide Sätze strukturell auf denselben Text passen könnten.

**Lehre für künftige Grammatik-Erweiterungen:** eine isolierte
Verifikationsfrage gegen einen vereinfachten/verkürzten Testgraph (wie in
diesem Fall zuerst gemacht) reicht nicht - sie muss gegen die **komplette**
reale YAML-Datei laufen, inklusive aller bereits bestehenden Sätze im
selben `Intents`-Objekt, um genau solche Satz-zu-Satz-Kollisionen zu
erkennen.

## `hass_entities.py`: Floor Registry (ungetestet, wie bei `area_id`/`unit`)

`_floor_info(hass, area_id)` liest `AreaEntry.floor_id` und darüber
`FloorRegistry.async_get_floor(floor_id)` (`FloorEntry.name`/`.level`) -
derselbe Fallback-Stil wie `_area_info()`. Bleibt wie der gesamte
`hass_entities.py`-Teil ohne automatisierten Test (kein `hass`-Mocking im
Repo) - manuelle Verifikation gegen die echte HA-Instanz nötig.

## Tests

`tests/test_floor_resolution.py` (13 Tests, hass-frei, spiegelt
`test_area_resolution.py`) und `tests/test_engine_floors.py` (8 Tests,
End-zu-Ende über `NluEngine.match()`, inkl. des Plan-Beispielsatzes "alle
Lichter oben" wortwörtlich). Volle Suite: 649/649 grün, pyflakes clean.
