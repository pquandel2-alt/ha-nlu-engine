"""Semantic Lexicon: the closed-vocabulary ``hassil`` ``TextSlotList``
definitions shared by ``parsers.py``'s grammars (domains, colors, comparison
operators, temporal expressions, states, ...).

First building block of the planned "Semantic Lexicon" (V6 architecture plan,
V6.3) - a single place for all vocabulary lists instead of them being
scattered across ``parsers.py``. Purely additive/extraction: the lists below
are moved here verbatim (same values, same order, same tuples) from
``parsers.py``, which now imports them from here instead of defining them
itself.

Note this is a deliberate, narrow exception to the "no hassil imports in
nlu/" boundary the rest of this package follows (see nlu/frame.py's
docstring): this module holds only inert vocabulary data, not pipeline
logic, so importing the ``TextSlotList`` container type here doesn't pull
hassil's matching/recognition machinery into the parser-agnostic layers.
"""

from __future__ import annotations

from hassil import TextSlotList

from .primitives import SemanticProperty, SemanticQuantity

# German word -> canonical HA domain, including the "Rolladen" (one l)
# misspelling seen in real user speech.
#
# Plural forms are listed *before* their singular counterpart wherever the
# singular is a literal text prefix of the plural (Licht/Lichter, Lampe/
# Lampen, Steckdose/Steckdosen, Rollo/Rollos, Ventilator/Ventilatoren): hassil
# matches TextSlotList values in declaration order and doesn't require a
# trailing word boundary, so with the singular listed first "Lichter" would
# match as "Licht" + a leftover "er" that silently gets swallowed by the
# {area} wildcard in the same sentence - the bug that broke the {level}
# ("oben"/"unten") sentences in Phase 28 until this reorder.
_DOMAIN_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("Lichter", "light"), ("Licht", "light"), ("Lampen", "light"), ("Lampe", "light"),
        ("Schalter", "switch"), ("Steckdosen", "switch"), ("Steckdose", "switch"),
        ("Rollladen", "cover"), ("Rollläden", "cover"), ("Rolladen", "cover"), ("Rolläden", "cover"),
        ("Rollos", "cover"), ("Rollo", "cover"),
        ("Ventilatoren", "fan"), ("Ventilator", "fan"),
    ],
    name="domain",
)

# Maps straight to "all"/"both" (rather than the raw German word) so
# QuantifierParser can apply the "beide" == exactly 2 hits rule directly.
# "nur" (v2 plan Phase 29, "Natural Quantifiers") also maps to "all" - "nur
# die Wohnzimmerlampen" restricts to a domain/area filter exactly like
# "alle", it just doesn't additionally claim "every matching light in the
# house" the way a bare "alle" does; the engine can't tell the two apart
# once the filter is applied, so there's no separate "only" kind.
_QUANTIFIER_SLOT_LIST = TextSlotList.from_tuples(
    [("alle", "all"), ("beide", "both"), ("beiden", "both"), ("beider", "both"), ("nur", "all")],
    name="quantifier",
)

# "zwei".."zehn" (v2 plan Phase 29) generalizes "beide"'s exact-count rule
# ("beide" == exactly 2) to arbitrary N ("die drei Lichter" == exactly 3).
# Same fixed, closed-vocabulary pattern as the slot lists above - string
# values (cast to int in QuantifierParser.parse()), same precedent
# _COLOR_TEMP_SLOT_LIST already established.
_COUNT_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("zwei", "2"), ("drei", "3"), ("vier", "4"), ("fünf", "5"),
        ("sechs", "6"), ("sieben", "7"), ("acht", "8"), ("neun", "9"), ("zehn", "10"),
    ],
    name="count",
)

# "oben"/"unten" (v2 plan Phase 28, "Hierarchische Orte") - a fixed, closed
# vocabulary like domain/quantifier above, not a {area}-style wildcard: these
# words never take a preposition ("mach alle Lichter oben an", not "... im
# oben an"), so they get their own slot/sentence shape rather than being
# folded into the {area} grammar.
_LEVEL_SLOT_LIST = TextSlotList.from_tuples(
    [("oben", "up"), ("unten", "down")],
    name="level",
)

# German colour words -> HA's native `color_name` service parameter (CSS
# colour names, so HA itself validates/converts them - not RGB triples
# invented here). "Basis-Set" per user decision (v2 plan Phase 14).
_COLOR_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("rot", "red"),
        ("grün", "green"),
        ("blau", "blue"),
        ("gelb", "yellow"),
        ("orange", "orange"),
        ("lila", "purple"),
        ("violett", "purple"),
        ("weiß", "white"),
        ("pink", "pink"),
        ("rosa", "pink"),
        ("türkis", "turquoise"),
        ("cyan", "cyan"),
    ],
    name="color",
)

# String values (cast to int by LightExtendedParser), same pattern as the
# domain/quantifier slot lists above - standard lighting-industry Kelvin
# reference values, not a UX decision requiring user input.
_COLOR_TEMP_SLOT_LIST = TextSlotList.from_tuples(
    [("warmweiß", "2700"), ("kaltweiß", "6500")],
    name="color_temp",
)

# "mindestens"/"höchstens"/"nicht höher als"/"über"/"unter" (HomeIntent plan
# V4.6, "Comparisons") -> Comparison.operator. "nicht höher als" is a
# multi-word text key - hassil's TextSlotList.from_tuples supports this
# (empirically verified against hassil==3.11.0 before this list was written,
# same discipline as _COLOR_TEMP_SLOT_LIST/_DOMAIN_SLOT_LIST). Both
# "höchstens" and "nicht höher als" map to "lte" - two spoken phrasings, one
# operator, same precedent _QUANTIFIER_SLOT_LIST's "nur"->"all" already set.
#
# "heller als"/"dunkler als"/"mehr als"/"weniger als" (V4.2 spec gap #5,
# "Welche Lampen sind heller als 70 Prozent?") map onto the same "gt"/"lt"
# operators "über"/"unter" already use - "heller"/"dunkler" are brightness-
# specific synonyms for "more"/"less" that read naturally in a percent
# comparison, not a new comparison semantic. engine.py's
# _COMPARISON_QUERY_RE requires "welche" + one of these literal phrases
# together, checked before _LIGHT_EXTENDED_RE, so "heller als" here can't
# collide with the plain "heller" (no "als") LightExtendedParser keyword.
_COMPARATOR_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("mindestens", "gte"),
        ("höchstens", "lte"),
        ("nicht höher als", "lte"),
        ("über", "gt"),
        ("unter", "lt"),
        ("heller als", "gt"),
        ("mehr als", "gt"),
        ("dunkler als", "lt"),
        ("weniger als", "lt"),
    ],
    name="comparator",
)

# Dedicated {domain} vocabulary for ComparisonQueryParser's grammar only -
# not merged into _DOMAIN_SLOT_LIST (shared by QuantifierParser/
# ReferenceParser for every other command), since "Heizung"/"Raum" as
# synonyms for the climate domain only make sense in a comparison-query
# context ("welche Räume sind unter 20 Grad") and adding them to the shared
# list would silently enable "mach alle Räume an" etc. elsewhere - out of
# V4.6's scope. Plural before singular, same reordering reason
# _DOMAIN_SLOT_LIST's docstring documents.
_COMPARISON_DOMAIN_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("Lichter", "light"), ("Licht", "light"), ("Lampen", "light"), ("Lampe", "light"),
        ("Rollläden", "cover"), ("Rollladen", "cover"), ("Rolladen", "cover"), ("Rolläden", "cover"),
        ("Rollos", "cover"), ("Rollo", "cover"),
        ("Heizungen", "climate"), ("Heizung", "climate"),
        ("Thermostate", "climate"), ("Thermostat", "climate"),
        ("Räume", "climate"), ("Raum", "climate"),
    ],
    name="domain",
)

# "in"/"für" (HomeIntent plan V4.7, "Temporal Expressions") -> which of the
# two numeric temporal kinds a sentence expresses. Both share the same
# {amount}/{unit} slots ("in fünf Minuten" vs. "für eine Stunde" only differ
# in this one preposition), so capturing it as its own closed-vocabulary slot
# - rather than duplicating the sentence per kind - avoids the YAML
# combinatorics V4.1's own filler-word decision already argued against.
_TEMPORAL_KIND_SLOT_LIST = TextSlotList.from_tuples([("in", "delay"), ("für", "duration")], name="temporal_kind")

# "Minute(n)"/"Stunde(n)" -> TemporalParser converts to minutes uniformly
# (Stunden * 60) rather than storing the raw unit, so every consumer of
# TemporalExpression.minutes only ever has to deal with one unit.
_TEMPORAL_UNIT_SLOT_LIST = TextSlotList.from_tuples(
    [("Minuten", "minutes"), ("Minute", "minutes"), ("Stunden", "hours"), ("Stunde", "hours")],
    name="unit",
)

# "morgen früh"/"heute Abend" (the plan's own two examples) plus their
# "heute früh"/"morgen Abend" mirror images - the 2x2 cross product of the
# exact two day-words and two day-part-words the plan text gives, nothing
# beyond that invented. Multi-word TextSlotList keys, same as
# _COMPARATOR_SLOT_LIST's "nicht höher als" (verified there already).
_TEMPORAL_RELATIVE_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("morgen früh", "tomorrow_morning"),
        ("morgen abend", "tomorrow_evening"),
        ("heute abend", "today_evening"),
        ("heute früh", "today_morning"),
    ],
    name="relative",
)

# {device_class} vocabulary for StateQueryParser's grammar (HomeIntent V4.2)
# - values are "domain:device_class" composite strings, not a plain domain or
# device_class alone: resolving "welche Fenster" needs both together
# (binary_sensor + window), and hassil TextSlotList values must be plain
# strings, so a second, separate {device_class}-only slot can't be cross-
# referenced against {domain} the way _COMPARISON_DOMAIN_SLOT_LIST's
# domain-only vocabulary can get away with. The literal string "None" means
# "no device_class filter, the domain alone is the target" (light/switch/
# cover) - StateQueryParser splits on ":" and treats that literal as "no
# filter", never as HA's real ``device_class is None`` case (already covered
# structurally: an entity with no device_class simply never matches a filter
# that isn't "None"). Plural before singular wherever the singular is a
# literal prefix of the plural (Tür/Türen, Garagentor/Garagentore), same
# reordering reason _DOMAIN_SLOT_LIST's own docstring documents - "Fenster"
# is identical in singular and plural German, so no ordering concern there.
_DEVICE_CLASS_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("Fenster", "binary_sensor:window"),
        ("Türen", "binary_sensor:door"), ("Tür", "binary_sensor:door"),
        ("Garagentore", "binary_sensor:garage_door"), ("Garagentor", "binary_sensor:garage_door"),
        ("Lichter", "light:None"), ("Licht", "light:None"), ("Lampen", "light:None"), ("Lampe", "light:None"),
        ("Schalter", "switch:None"), ("Steckdosen", "switch:None"), ("Steckdose", "switch:None"),
        ("Rollläden", "cover:None"), ("Rollladen", "cover:None"), ("Rolladen", "cover:None"), ("Rolläden", "cover:None"),
        ("Rollos", "cover:None"), ("Rollo", "cover:None"),
        ("Bewegungsmelder", "binary_sensor:motion"), ("Bewegungssensoren", "binary_sensor:motion"),
        ("Bewegungssensor", "binary_sensor:motion"),
    ],
    name="device_class",
)

# Predicate-position state words ("die Fenster sind {state}") -> the
# SemanticState member *name* (a plain string, cast back to the enum member
# via _STATE_NAME_TO_SEMANTIC in parsers.py - hassil TextSlotList values must
# be strings, same constraint _COMPARATOR_SLOT_LIST's operator strings work
# around).
_STATE_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("geöffnet", "OPEN"), ("offen", "OPEN"),
        ("geschlossen", "CLOSED"), ("zu", "CLOSED"),
        ("eingeschaltet", "ON"), ("angeschaltet", "ON"), ("an", "ON"),
        ("ausgeschaltet", "OFF"), ("aus", "OFF"),
    ],
    name="state",
)

# Attributive-position state words ("gibt es {state_adj} Fenster") - German
# inflects the adjective here (offen -> offene), a different word than the
# predicate form above, so this is its own slot rather than reusing {state}.
_STATE_ADJ_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("geöffnete", "OPEN"), ("offene", "OPEN"),
        ("geschlossene", "CLOSED"),
        ("eingeschaltete", "ON"), ("angeschaltete", "ON"),
        ("ausgeschaltete", "OFF"),
    ],
    name="state_adj",
)


# --- Semantic candidate mapping (V6.3, second half) -------------------------
#
# The slot lists above are hassil's raw grammar vocabulary (word -> match
# value). The mappings below add a second, semantic layer on top: normalized
# German word -> semantic PRIMITIVE CANDIDATE (see nlu/primitives.py). They
# are candidates only, not decisions - final interpretation still requires
# the Semantic Composer + Reasoning Engine (V6.4+) combining these with
# context/World Model/capabilities, per the plan's own "liefert Kandidaten,
# entscheidet nicht allein" rule (V6.3, Brain node
# 52ae9a3a-c380-4a26-9a49-ce8b1db94367).
#
# Deliberately incomplete: only two of SemanticAction/SemanticProperty/
# SemanticDirection/SemanticQuantity/SemanticDegree have real, already-listed
# vocabulary in this module to derive candidates from without guessing.
# SemanticAction ("mach"/"schalte"/"an"/"aus") and SemanticDirection
# ("heller"/"dunkler") are carried today as literal words in the hassil YAML
# sentence templates (custom_components/ha_nlu/intents/de/**/*.yaml) and in
# parsers.py's own regexes (e.g. _LIGHT_EXTENDED_RE), not as a TextSlotList
# vocabulary constant here - building their candidate mapping means first
# inventorying those YAML/regex literals, which is real, separate work left
# for Wave 2b (Semantic Composer) rather than invented here ahead of it.
# SemanticDegree has no lexicon entry at all yet (see primitives.py's own
# docstring - "etwas"/"ein bisschen" are stripped as filler before any parser
# sees them), so no candidate mapping is possible for it today.

# _COLOR_SLOT_LIST's keys all indicate the same property regardless of which
# colour word was said; _COLOR_TEMP_SLOT_LIST's keys indicate the sibling
# property. Every value is the SAME candidate per list on purpose - the word
# only tells you *that* a colour/colour-temperature is being set, not which
# property-free reading would make sense otherwise.
SEMANTIC_PROPERTY_CANDIDATES: dict[str, SemanticProperty] = {
    **{v.text_in.text: SemanticProperty.COLOR for v in _COLOR_SLOT_LIST.values},
    **{v.text_in.text: SemanticProperty.COLOR_TEMPERATURE for v in _COLOR_TEMP_SLOT_LIST.values},
}

# _QUANTIFIER_SLOT_LIST's "all"/"both" and _COUNT_SLOT_LIST's "2".."10"
# already carry the exact values SemanticQuantity's classmethods take -
# reuse them 1:1 instead of re-encoding the same words differently here.
SEMANTIC_QUANTITY_CANDIDATES: dict[str, SemanticQuantity] = {
    **{
        v.text_in.text: (SemanticQuantity.all() if v.value_out == "all" else SemanticQuantity.exactly(2))
        for v in _QUANTIFIER_SLOT_LIST.values
    },
    **{v.text_in.text: SemanticQuantity.exactly(int(v.value_out)) for v in _COUNT_SLOT_LIST.values},
}
