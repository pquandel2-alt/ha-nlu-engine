"""v2 plan Phase 28 ("Hierarchical Locations"): 'alle Lichter oben'/'alle
Lichter im Erdgeschoss' - quantifier commands scoped to a floor instead of
(or as a fallback from) a room. End-to-end through ``NluEngine.match()``,
mirroring test_engine_quantifiers.py's style.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

TWO_FLOOR_HOUSE = [
    EntitySnapshot(
        "light.wohnzimmer", "Wohnzimmerlicht", "light", "off",
        area_id="wohnzimmer", area_name="Wohnzimmer",
        floor_id="erdgeschoss", floor_name="Erdgeschoss", floor_level=0,
    ),
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "off",
        area_id="kueche", area_name="Küche",
        floor_id="erdgeschoss", floor_name="Erdgeschoss", floor_level=0,
    ),
    EntitySnapshot(
        "light.buero", "Bürolicht", "light", "off",
        area_id="buero", area_name="Büro",
        floor_id="obergeschoss", floor_name="Obergeschoss", floor_level=1,
    ),
    EntitySnapshot(
        "light.schlafzimmer", "Schlafzimmerlicht", "light", "off",
        area_id="schlafzimmer", area_name="Schlafzimmer",
        floor_id="obergeschoss", floor_name="Obergeschoss", floor_level=1,
    ),
]


def test_alle_lichter_oben(engine):
    # The plan's own literal example ("Dann 'alle Lichter oben' möglich.").
    result = engine.match("mach alle Lichter oben an", TWO_FLOOR_HOUSE)
    assert result is not None
    assert result.plan.domain == "homeassistant"
    assert result.plan.service == "turn_on"
    assert sorted(result.plan.entity_id) == ["light.buero", "light.schlafzimmer"]


def test_alle_lichter_unten(engine):
    result = engine.match("mach alle Lichter unten aus", TWO_FLOOR_HOUSE)
    assert result is not None
    assert result.plan.service == "turn_off"
    assert sorted(result.plan.entity_id) == ["light.kueche", "light.wohnzimmer"]


def test_alle_lichter_im_erdgeschoss_floor_name_fallback(engine):
    # "Erdgeschoss" is not a room, so area resolution falls through to the
    # floor resolver - same {area} slot, no separate grammar needed.
    result = engine.match("mach alle Lichter im Erdgeschoss aus", TWO_FLOOR_HOUSE)
    assert result is not None
    assert sorted(result.plan.entity_id) == ["light.kueche", "light.wohnzimmer"]


def test_oben_without_any_floor_data_returns_none(engine, entities):
    # None of the standard `entities` fixture carries floor data - "oben"
    # has nothing to resolve against, so this must stay a clean non-match.
    result = engine.match("mach alle Lichter oben an", entities)
    assert result is None


def test_oben_with_single_floor_house_resolves_that_floor(engine):
    single_floor = [
        EntitySnapshot(
            "light.a", "A", "light", "off",
            area_id="wohnzimmer", area_name="Wohnzimmer",
            floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
        ),
    ]
    result = engine.match("mach alle Lichter oben an", single_floor)
    assert result is not None
    assert result.plan.entity_id == "light.a"


def test_oben_tie_between_floors_returns_none(engine):
    tied = [
        EntitySnapshot(
            "light.a", "A", "light", "off",
            floor_id="og_west", floor_name="Obergeschoss West", floor_level=1,
        ),
        EntitySnapshot(
            "light.b", "B", "light", "off",
            floor_id="og_ost", floor_name="Obergeschoss Ost", floor_level=1,
        ),
    ]
    result = engine.match("mach alle Lichter oben an", tied)
    assert result is None


def test_unknown_area_and_unknown_floor_returns_none(engine):
    result = engine.match("mach alle Lichter im Bunker aus", TWO_FLOOR_HOUSE)
    assert result is None


def test_floor_with_no_matching_domain_returns_none(engine):
    result = engine.match("fahre alle Rollläden im Erdgeschoss hoch", TWO_FLOOR_HOUSE)
    assert result is None


def test_mach_oben_die_lichter_aus_without_quantifier_word(engine):
    # HomeIntent plan V4.3 ("Implicit Targets"): the plan's own literal
    # example has no alle/beide/nur - just verb + {level} + {domain}. Same
    # resolve_floor_by_level_keyword() resolution as "alle Lichter oben",
    # QuantifierParser.parse() already defaults to quantifier="all" when
    # neither {quantifier} nor {count} is present.
    result = engine.match("Mach oben die Lichter aus", TWO_FLOOR_HOUSE)
    assert result is not None
    assert result.plan.service == "turn_off"
    assert sorted(result.plan.entity_id) == ["light.buero", "light.schlafzimmer"]


def test_schalte_unten_die_lichter_ein_without_quantifier_word(engine):
    result = engine.match("schalte unten die Lichter ein", TWO_FLOOR_HOUSE)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert sorted(result.plan.entity_id) == ["light.kueche", "light.wohnzimmer"]


def test_kannst_du_oben_die_lichter_anmachen_without_quantifier_word(engine):
    result = engine.match("kannst du oben die Lichter anmachen", TWO_FLOOR_HOUSE)
    assert result is not None
    assert sorted(result.plan.entity_id) == ["light.buero", "light.schlafzimmer"]


def test_oben_without_quantifier_word_and_without_floor_data_returns_none(engine, entities):
    # Same "never guess" rule as the pre-existing quantifier-word form.
    assert engine.match("mach oben die Lichter aus", entities) is None
