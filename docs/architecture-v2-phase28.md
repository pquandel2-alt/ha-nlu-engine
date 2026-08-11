# v2-Umbau, Phase 29: Natural Quantifiers

Referenz: Brain-Knoten "ha-nlu-engine v3 Plan: ..." (Phase 29, "Natural
Quantifiers"), Beispielsätze aus dem Plan: *"die beiden Lampen, die drei
Lichter, alle außer der Küchenlampe, nur die Wohnzimmerlampen. Sollte auf
dem bestehenden Quantifier-System (Phase 8) aufbauen."* Vorstufe:
`docs/architecture-v2-phase27.md` (Hierarchische Orte).

## Ziel

Der bestehende Quantor-Mechanismus (`{quantifier}` -> "all"/"both", Phase 8)
kannte nur die zwei starren Formen "alle"/"beide[n/r]". Vier natürlichere
Ausdrucksformen kommen dazu, alle auf demselben `QuantifierParser`
aufbauend statt einer neuen Grammatik:

1. **"die beiden Lampen"** - der bestehende "both"-Quantor, jetzt mit einem
   vorangestellten "die" erreichbar.
2. **"die drei Lichter"** - ein neuer `{count}`-Slot, der "beide"s
   exakte-Trefferzahl-Regel (== 2) auf eine beliebige Zahl N verallgemeinert.
3. **"alle außer der Küchenlampe"** - eine Ausschluss-Klausel: ein
   hartkodiertes "alle" in der YAML (nicht der `{quantifier}`-Slot) plus ein
   neuer `{name}`-Slot für die ausgeschlossene Entity.
4. **"nur die Wohnzimmerlampen"** - "nur" als drittes Wort im
   `_QUANTIFIER_SLOT_LIST`-Vokabular, mappt auf denselben Wert wie "alle".

## Drei Formen, wie ein Satz "wie viele" ausdrückt

`QuantifierParser.parse()` prüft nach `{quantifier}`- und `{count}`-Slot,
gegenseitig ausschließend über die Satzvorlage (ein Satz nutzt höchstens
einen der beiden):

```python
if quantifier_slot is not None:
    quantifier = str(quantifier_slot.value)          # "all" / "both"
elif count_slot is not None:
    quantifier = "count"
    quantifier_value = int(count_slot.value)
else:
    quantifier = "all"   # Ausschluss-Sätze: hartkodiertes "alle"-Literal
```

`_COUNT_SLOT_LIST` (`parsers.py`) ist ein weiteres festes, geschlossenes
Vokabular wie `_DOMAIN_SLOT_LIST`/`_QUANTIFIER_SLOT_LIST`/`_LEVEL_SLOT_LIST`:
`"zwei"->"2"`, ..., `"zehn"->"10"`. Kein Freitext-Zahlenparsing - nur
ausgeschriebene Zahlwörter, dieselbe Vokabular-Grenze wie überall sonst in
diesem Modul.

## Ausschluss-Klausel: `{name}` + Mitgliedschafts-Check

Die "außer"-Sätze verwenden ein hartkodiertes "alle" statt des
`{quantifier}`-Slots, damit "außer ..." direkt danach folgen kann, ohne mit
der Quantor-Grammatik zu kollidieren. Das `{name}`-Ziel wird mit demselben
`resolve_entity()` aufgelöst, das auch `SingleTargetParser` nutzt - und muss
danach bereits Teil der Domain/Area-gefilterten `matches`-Liste sein:

```python
name_slot = result.entities.get("name")
if name_slot is not None:
    exclude_name = _strip_locative_prepositions(str(name_slot.value))
    excluded = resolve_entity(exclude_name, context.entities)
    if excluded.status is not ResolveStatus.OK or excluded.entity is None:
        return None  # nicht eindeutig auflösbar - nie raten
    if excluded.entity not in matches:
        return None  # nicht Teil der gefilterten Trefferliste - ablehnen statt stillschweigend zu ignorieren
    matches = [e for e in matches if e.entity_id != excluded.entity.entity_id]
```

Zwei bewusste "nie raten"-Fälle: ein Name, der nicht eindeutig auflöst
(NOT_FOUND/AMBIGUOUS), bricht den ganzen Befehl ab statt ihn ohne Ausschluss
auszuführen. Ein Name, der auflöst, aber zur falschen Domain/außerhalb des
Raums gehört (z.B. "... außer der Küchenrollladen" bei einem Lichter-Befehl),
wird ebenfalls abgelehnt - sonst würde der Befehl fälschlich behaupten,
etwas ausgeschlossen zu haben, das nie im Treffer-Set war.

## Wortstellung: zwei optionale "die", nicht eins

Erste Version hatte nur `[die] {quantifier} {domain}` (ein optionales "die"
*vor* dem Quantor) - deckt "die beiden Lampen" ab, aber nicht "nur die
Lampen": bei "nur" steht "die" *nach* dem Quantor-Wort, nicht davor ("nur
die Lampen", nicht "die nur Lampen"). Fix: ein zweites optionales "die"
zwischen `{quantifier}` und `{domain}`:

```
[die] {quantifier} [die] {domain}
```

Deckt beide Wortstellungen ab (und erlaubt permissiv auch grammatisch
unübliche Kombinationen wie "die alle Lampen" - harmlos, da nur zusätzliche
Eingaben akzeptiert werden, keine bestehende Bedeutung verändert wird).

## Bewusster Scope-Cut: "nur die Wohnzimmerlampen" als Kompositum

Der Plan-Beispielsatz "nur die Wohnzimmerlampen" ist ein deutsches Kompositum
(Raum + Domain in einem Wort verschmolzen). Dieses Modul zerlegt keine
Komposita - `{domain}` ist ein festes Vokabular exakter Wörter
(`_DOMAIN_SLOT_LIST`), kein Wortstamm-Matching. Getestet wird stattdessen die
äquivalente, nicht-komponierte Form "nur die Lampen im Wohnzimmer" - gleicher
Auflösungspfad (Quantor "nur" -> "all", `{area}`-Filter), ohne
Komposita-Parsing zu benötigen. Kompositum-Zerlegung wäre ein eigener,
deutlich größerer Scope (Wörterbuch oder Heuristik für Wortgrenzen in
zusammengesetzten Nomen) und explizit nicht Teil dieser Phase.

## `validator.py`: Check #9 um `kind == "count"` erweitert

```python
if frame.quantifier is not None:
    if frame.quantifier.kind == "both" and len(command.entities) != 2:
        return ValidationError.INVALID_QUANTIFIER
    if frame.quantifier.kind == "count" and len(command.entities) != frame.quantifier.value:
        return ValidationError.INVALID_QUANTIFIER
```

Dieselbe "nie raten"-Regel wie bei "beide": bei falscher Trefferzahl kein
Teilerfolg, kein Raten welche N gemeint sind - kompletter Fehlschlag.

## `engine.py`: Routing-Regex um "nur"/Zahlwörter erweitert

`_QUANTIFIER_RE` matchte bisher nur `alle|beide[nr]?` - "nur"-only- oder
count-only-Sätze ("nur die Wohnzimmerlampen an", "mach die drei Lichter an")
enthalten keins von beidem und wären nie beim `QuantifierParser` gelandet:

```python
_QUANTIFIER_RE = re.compile(
    r"\b(alle|beide[nr]?|nur|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\b", re.IGNORECASE
)
```

Die Ausschluss-Sätze ("alle ... außer ...") brauchten keine Regex-Änderung -
sie enthalten immer das Wort "alle" (hartkodiertes Literal in der YAML), das
schon vorher gematcht hat.

## `Quantifier.value`: kein neues Feld nötig

`nlu/frame.py`s `Quantifier`-Dataclass hatte bereits `value: int | None =
None` seit Phase 8/9, mit einem Docstring-Kommentar, der genau diesen Fall
("kind='count', value=3") als zukünftige Erweiterung ankündigte - Phase 29
füllt dieses bereits vorbereitete Feld erstmals, keine Strukturänderung
nötig. `nlu/command.py`s `build_semantic_command()` bleibt unverändert (der
Wert läuft transparent über `frame.source_frame` durch, wie bei jedem
anderen Parameter).

## Tests

`tests/test_engine_quantifiers.py` um 7 neue Fälle erweitert, alle vier
Plan-Beispiele (in nicht-komponierter Form für Fall 4) abgedeckt: "die
beiden Lampen" (both mit die-Präfix), "die drei Lichter" (count, plus ein
Negativ-Test für falsche Trefferzahl), "alle ... außer der Küchenlampe"
(Ausschluss, plus zwei Negativ-Tests: Ziel außerhalb des Treffer-Sets, Ziel
nicht auflösbar), "nur die Lampen im Wohnzimmer" (nur + Area-Filter). Volle
Suite: 656/656 grün, pyflakes clean.

**Fallstrick beim Testen:** kurze Test-Entity-IDs wie `light.a`/`light.b`
erzeugen über `generate_aliases()`s `_humanize_object_id()` einen
einbuchstabigen Alias ("A"/"B"), der über die "reverse contains"-Scoring-Stufe
(`_SCORE_REVERSE_CONTAINS`) fast jedes gesprochene Wort trifft, das diesen
Buchstaben enthält - führte zu einem falschen Ausschluss-Test-Fehlschlag, bis
auf realistische, mehrsilbige Entity-IDs umgestellt wurde (wie im Rest des
Testcorpus üblich).
