# v4 – Advanced Natural Language

Referenz: Brain-Knoten "HomeIntent Plan: Status & Mapping auf bestehende
Phasen 01-29" (`c4c42add-46ac-4b8d-bee9-9c85a3d0ef42`) sowie die
Einzelabschnitte des HomeIntent-Plans (`§29-34`/`§43`, "Definition of Done –
v4"). Vorstufe: `docs/architecture-v2-phase28.md` (Natural Quantifiers, der
letzte dokumentierte Schritt des ursprünglichen 01-31-Phasenplans).

Dieses Dokument fasst zusammen, statt jeden Schritt einzeln zu dokumentieren
wie es die `architecture-v2-phaseN.md`-Reihe für die Phasen 1-29 tut - der
HomeIntent-Plan traf ein, nachdem der Umbau bereits bei v3.0.0 stand, und
definierte v4 nicht mehr als nummerierte Einzelphasen, sondern als
Abschnittsliste (V4.1-V4.9). Für Volltext-Details siehe die commit-Historie
(`git log --oneline`, jeder V4.x-Abschnitt ist genau ein Commit) und die
zugehörigen `tests/test_engine_*.py`-Dateien.

## Ausgangspunkt: Vollständige Neubewertung

Bevor V4.1 begann, wurde jeder bereits umgesetzte Abschnitt (V2.1-V2.15,
V3.1-V3.6 im HomeIntent-Plan-Vokabular - deckungsgleich mit den Phasen
01-29 dieses Repos) gegen die neuen, präziseren Plan-Formulierungen
geprüft, statt sie ungeprüft als "bereits erledigt" zu übernehmen. Ergebnis:
drei echte Lücken gefunden und geschlossen, bevor V4.1 begann:

1. **Capability POWER/ENERGY** fehlte im Capability-System (`capabilities.py`)
   für Sensor-Entities mit `device_class` `power`/`energy`.
2. **Query-Grammatik für "Wie viel Strom verbraucht ..."** - eine eigene
   Satzform, die bis dahin nicht abgedeckt war.
3. **"die anderen"-Komplementreferenz** - `match_reference()` konnte bis
   dahin nur auf explizit genannte vorherige Entities verweisen ("es", "die
   andere"), nicht auf "alle außer den bereits genannten" innerhalb derselben
   Area.

Diese drei Fixes plus die V4.1-V4.9-Commits bilden zusammen 12 Commits
(`b583a3f`, `ef66357`, `ee934de`, `1ad736a`, `0df1f61`, `4eb8839`, `dc6e8b4`,
`38818bf`, `2a66c4d`, `9b64c5f`, `be7605e`, `f69f88b`).

## V4.1 – Advanced German Language (Sprachbausteine statt YAML-Kombinatorik)

Zusätzliche Verben ("dreh", "lass" neben "mach"/"schalte") und Füllwörter
("bitte", "doch", "mal", ...) wurden **zentral in `normalize()`** gestrippt/
normalisiert, statt für jede Kombination eine eigene YAML-Satzvariante
anzulegen. Der Plan warnte explizit vor "YAML-Kombinatorik" - jede neue
Verb/Füllwort-Kombination hätte sonst die Grammatik-Dateien multiplikativ
wachsen lassen. 765 Tests grün.

## V4.2 – Number Normalization

`normalize()` erweitert um das "°"-Symbol (Alias für "Grad") und nackte
Prozentzahlen ohne "Prozent"-Wort ("auf 50" im Kontext eines
Helligkeits-/Temperatur-Befehls). 776 Tests.

## V4.3 – Implicit Targets

"oben"/"unten" ohne explizite Area ("Mach oben die Lichter aus") routen über
`resolve_floor_by_level_keyword()` auf eine Etage statt auf einen Raum -
Etagenzuordnung kommt aus den `EntitySnapshot.floor_id`/`floor_level`-Feldern
der Home-Assistant-Registry, nie geraten. Zusätzlich: verb-first "dort"
("Mach dort die Rollläden runter." statt nur "Die Rollläden dort runter.").
**Bewusst zurückgestellt:** "hier" (aktueller Geräte-/Satelliten-Standort) -
braucht eine device_id→Area-Auflösung, die nirgendwo in der bestehenden
Datenquelle existiert; würde geraten statt aufgelöst. 782 Tests.

## V4.4 – Relative Locations

"im selben Raum" als weiteres Synonym für die bereits bestehende
"dort"-Area-Verankerung (`_resolve_area_anchored()`, seit Phase 27/28) -
gleicher Auflösungspfad, nur zusätzliches Vokabular. **Bewusst
zurückgestellt:** "nebenan" (Nachbarraum-Adjazenz) - Home Assistant liefert
keine Area-Adjazenzdaten; eine Nachbarschaftsrelation zu erfinden würde raten
statt auflösen. 785 Tests.

## V4.5 – Advanced Quantifiers (Rest)

Die vom HomeIntent-Plan zusätzlich geforderten Ordinal-Selektoren ("die
ersten beiden", "die letzten zwei") wurden geprüft und **bewusst
zurückgestellt**: `EntitySnapshot` hat kein Ordnungs-/Positionsfeld (keine
stabile, vom Nutzer nachvollziehbare Reihenfolge existiert in der
Datenquelle) - jede Sortierung wäre erfunden statt aus echten Daten
abgeleitet. Stattdessen zwei Ambiguitäts-Regressionstests ergänzt, die
pinnen, dass solche Sätze weiterhin sauber mit "nicht verstanden" statt
einer geratenen Teilmenge enden. 786 Tests.

## V4.6 – Comparisons

Nutzerentscheidung (explizit erfragt): "Mindestens 50 Prozent" muss **sowohl**
als Setpoint-Synonym ("stell auf mindestens 50%" - interpretiert als exakter
Zielwert) **als auch** als Query-Filter ("welche Lichter sind heller als 50%"
- interpretiert als Vergleichsbedingung über den aktuellen Zustand) verfügbar
sein, nicht nur eine der beiden Lesarten. Neue `Comparison`-Dataclass in
`nlu/frame.py` (`operator`: `at_least`/`at_most`/`more_than`/`less_than`,
`value`). 9. separat kompilierte hassil-Grammatik: `ComparisonQueryParser`
(`intents/de/comparison_query/`). 804 Tests. Commit `2a66c4d`.

## V4.7 – Temporal Expressions

Neue `TemporalExpression`-Dataclass (`nlu/frame.py`): `kind` ∈
`delay`/`duration`/`relative_time`/`absolute_time`, plus `minutes`/
`relative`/`hour`-Felder je nach `kind`. Beispiele: "in fünf Minuten"
(delay), "für eine Stunde" (duration, Stunden→Minuten normalisiert), "morgen
früh"/"heute Abend" (relative_time), "um 20 Uhr" (absolute_time). Der Plan
selbst grenzt den Scope explizit ein: *"Zunächst nur parsen und validieren -
tatsächliche HA-Ausführung erst in einer späteren Execution-Schicht"* - der
resultierende `ServiceCallPlan` ist deshalb byte-identisch zu einem
gewöhnlichen Sofort-Befehl (reuse von `HassTurnOn`/`HassTurnOff`); nur
`frame.parameters["temporal"]` unterscheidet sich. 10. hassil-Grammatik:
`TemporalParser` (`intents/de/temporal/`). 814 Tests. Commit `9b64c5f`.

## V4.8 – Multi-Step Commands

Beispiel: "Mach das Licht an und fahr die Rollläden hoch." → 2 unabhängige
Befehle in einem Satz. Bewusst **ohne eigene hassil-Grammatik** umgesetzt:
`NluEngine.match()` splittet den Eingabetext zuerst auf `\s+und\s+`
(`_AND_SPLIT_RE` - vorab per grep verifiziert, dass kein bestehender
YAML-Satz das Wort "und" enthält, also kollisionsfrei) und ruft bei 2+
Segmenten sich selbst **rekursiv** auf jedes Segment auf. Jedes Segment
durchläuft dadurch die volle bestehende Single-Command-Pipeline
unverändert (eigene Parser-Auswahl, eigene Entity-Resolution, eigene
Validierung). Ketten mit 3+ "und" funktionieren dadurch automatisch, ohne
Sonderfall-Code.

Neue `CommandPlan(commands: tuple[MatchResult, ...])`-Dataclass. Sie wird
**nur** gebaut, wenn jedes Segment erfolgreich matcht (kein `None`, keine
Rückfrage, `plan is not None`) - ein einziges scheiterndes/mehrdeutiges
Segment lässt den gesamten Satz scheitern (`match()` gibt `None` zurück,
niemals einen Teil-`CommandPlan`). Das setzt die Plan-Vorgabe *"validate
entire plan first → execute only if complete plan is valid"* rein
strukturell um, ohne separaten Rollback-Mechanismus.

Bewusster Scope-Cut: Query-Segmente (`plan=None`, z.B. "wie warm ist es")
sind kein gültiges Multi-Step-Glied - das Plan-Beispiel ist rein
aktionsbasiert, eine Query hat kein offensichtliches "execute"-Äquivalent
in einer Sequenz.

`conversation.py` führt bei einem `CommandPlan` jeden Sub-Plan-Service-Call
sequenziell aus und verkettet die Antworttexte; bricht beim ersten
HA-seitigen Laufzeitfehler ab (kein Rollback bereits ausgeführter Calls - HA
Service-Calls sind nicht transaktional, nur die Parse-/Validierungsphase ist
garantiert atomar). Conversation-Context wird nach einem Multi-Step-Turn
nicht übernommen (mehrdeutig, welches Sub-Command ein Folgesatz meinen
würde). 821 Tests grün. Commit `be7605e`.

## V4.9 – Cross-Sentence References

Beispiel: "Wie warm ist es im Wohnzimmer?" → "Und in der Küche?" → "Und
oben?" - Domain/`device_class` werden aus dem vorherigen Turn übernommen,
nie erneut ausgesprochen.

**Design-Erkenntnis vor der Umsetzung:** Das Plan-eigene Beispiel "Wie warm
ist es im Wohnzimmer?" passt auf keine bestehende Grammatik - `query.yaml`
verlangt immer ein `{name}` (`"ist [die|der|das] {name}"`), nie "ist es im
{area}". V4.9 brauchte deshalb zwei neue, separat kompilierte
hassil-Grammatiken, nicht nur einen Folgesatz-Mechanismus auf einem
bereits funktionierenden Erstsatz:

1. **`AreaQueryParser`** (`intents/de/area_query/`, 11. Grammatik): `"wie
   [warm|kalt] ist es [in der|in dem|im|am|beim] {area}"` - reine
   Area-Query ohne Entity-Namen. Filtert auf `domain="sensor"` +
   `device_class="temperature"` in der aufgelösten Area; verlangt genau
   1 Treffer (nie raten). Nutzt weiterhin den bestehenden Intent-Namen
   `"HassGetState"`, läuft dadurch unverändert durch
   `QUERY_INTENTS`/`_build_match_result` - keine Änderung an
   `service_call.py` nötig.

2. **`QueryFollowupParser`** (`intents/de/query_followup/`, 12. Grammatik) +
   `NluEngine.match_query_followup()`: `"und (in der|in dem|im|am|beim)
   {area}"` / `"und {level}"`. Domain/`device_class` werden von
   `context.last_entities[0]` übernommen: bei `domain == "light"` nur die
   Domain (Lichter haben keine `device_class`), sonst Domain **und**
   `device_class` - spiegelt dieselbe Domain-zuerst/`device_class`-danach-
   Präzedenz, die `nlu/query.py`s `derive_query_type()` bereits etabliert
   hat. `match_query_followup()` selbst gated vorab auf
   `context.last_command.intent == "HassGetState"`, bevor der Parser
   überhaupt aufgerufen wird - `QueryFollowupParser` selbst bleibt dadurch
   frei von `ConversationContext`/`SemanticCommand`-Importen, dasselbe
   Muster, das `match_followup()`/`ContextFollowupParser` bereits nutzt.
   Eingebunden in `conversation.py`s Try-Chain nach `match_reference`, vor
   `match`.

**Hassil-Grammatik-Bug gefunden und gefixt:** Die `{area}`-Präposition in
`query_followup.yaml` musste von optional (`[in der|in dem|im|am|beim]`) auf
**zwingend** (`(in der|in dem|im|am|beim)`) geändert werden. Mit optionaler
Präposition matchte "und oben" strukturell auch die `{area}`-Wildcard-Regel
(0 vorangehende Wörter reichen), die laut hassil-Deklarationsreihenfolge
zuerst kam und die dedizierte "und {level}"-Regel dadurch nie zum Zug kommen
ließ. Jede andere `{area}`-Grammatik in diesem Projekt ist mit optionaler
Präposition sicher, weil `{area}` dort immer zwischen zwei festen Wörtern
steht (Verb/Domain davor, "an"/"aus"/"hoch"/... danach) - hier ist "und" das
einzige feste Wort für beide Satzformen, sodass nur die zwingende Form beide
Formen unterscheidbar hält. Empirisch verifiziert (`Intents.from_dict()` +
`recognize()`) vor dem Fix; ausführlich in `query_followup.yaml` selbst
dokumentiert.

13 neue Tests in `tests/test_engine_query_followup.py`. 834 Tests grün.
Commit `f69f88b`.

## Offene, bewusst zurückgestellte Lücken

Sammelposten für spätere Phasen (v5 oder auf explizite Nutzeranfrage) - alle
wurden geprüft und bewusst nicht umgesetzt, weil eine Lösung ohne echte
Datenquelle nur geraten hätte:

- **"hier"** (aktueller Geräte-/Satelliten-Standort, V4.3) - braucht
  device_id→Area-Auflösung, die nirgendwo existiert.
- **"nebenan"** (Nachbarraum-Adjazenz, V4.4) - braucht Area-Adjazenzdaten,
  die Home Assistant nicht nativ bereitstellt.
- **"die ersten beiden"/"die letzten zwei"** (Ordinal-Auswahl, V4.5) -
  braucht ein Ordnungs-/Positionsfeld auf `EntitySnapshot`, das nirgendwo
  existiert.
- **Query-Segmente in Multi-Step-Sätzen** (V4.8) - kein "execute"-Äquivalent
  für eine Query in einer Sequenz definiert, aktuell hart ausgeschlossen
  statt geraten.

## Definition of Done – v4 (§43 des Plans)

Alle Kriterien erfüllt: natürliche deutsche Varianten erweitert (V4.1),
Zahlen normalisiert (V4.2), implizite Targets (V4.3), relative Locations
(V4.4), komplexe Quantifier (V4.5), Vergleichsoperatoren (V4.6), temporale
Ausdrücke (V4.7), Multi-Step Commands (V4.8), Cross-Sentence References
(V4.9) - alle neuen Funktionen jeweils in eigenen `tests/test_engine_*.py`-
Dateien umfangreich getestet, volle Suite (834 Tests) grün vor jedem Commit.
