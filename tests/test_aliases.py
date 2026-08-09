"""Phase 6 (v2 plan): Alias-System. EntityAlias/generate_aliases are pure and
hass-free; resolve_entity must now also find entities via generated aliases
(entity_id, humanized entity_name, configured HA aliases), not just
friendly_name."""

from __future__ import annotations

from ha_nlu.entities import (
    EntityAlias,
    EntitySnapshot,
    ResolveStatus,
    generate_aliases,
    resolve_entity,
)


def test_generate_aliases_includes_entity_id_and_humanized_name():
    entity = EntitySnapshot("light.wohnzimmer_decke", "Wohnzimmer Deckenlicht", "light", "off")
    aliases = generate_aliases(entity)
    texts = {a.text for a in aliases}
    assert "light.wohnzimmer_decke" in texts
    assert "Wohnzimmer Decke" in texts


def test_generate_aliases_includes_configured_aliases():
    entity = EntitySnapshot(
        "light.wohnzimmer_decke",
        "Wohnzimmer Deckenlicht",
        "light",
        "off",
        aliases=("Deckenlampe", "Lampe Wohnzimmer"),
    )
    aliases = generate_aliases(entity)
    configured = {a.text: a.source for a in aliases if a.source == "configured"}
    assert configured == {"Deckenlampe": "configured", "Lampe Wohnzimmer": "configured"}


def test_generate_aliases_dedupes_against_friendly_name_case_insensitive():
    # object_id "wohnzimmer" humanizes to "Wohnzimmer", identical to the
    # friendly_name - must not appear twice / as a redundant alias.
    entity = EntitySnapshot("light.wohnzimmer", "wohnzimmer", "light", "off")
    aliases = generate_aliases(entity)
    texts = [a.text for a in aliases]
    assert "Wohnzimmer" not in texts
    # entity_id itself ("light.wohnzimmer") is still a distinct, useful alias.
    assert "light.wohnzimmer" in texts


def test_generate_aliases_returns_entity_alias_instances():
    entity = EntitySnapshot("switch.garagentor", "Garagentor", "switch", "off")
    aliases = generate_aliases(entity)
    assert all(isinstance(a, EntityAlias) for a in aliases)
    assert all(a.entity_id == "switch.garagentor" for a in aliases)


def test_resolve_entity_finds_via_configured_alias():
    entities = [
        EntitySnapshot(
            "light.wohnzimmer_decke",
            "Wohnzimmer Deckenlicht",
            "light",
            "off",
            aliases=("Deckenlampe",),
        )
    ]
    result = resolve_entity("Deckenlampe", entities)
    assert result.status is ResolveStatus.OK
    assert result.entity.entity_id == "light.wohnzimmer_decke"


def test_resolve_entity_finds_via_humanized_entity_id():
    entities = [EntitySnapshot("light.dachgeschoss_licht", "Dachgeschosslicht", "light", "off")]
    result = resolve_entity("Dachgeschoss Licht", entities)
    assert result.status is ResolveStatus.OK
    assert result.entity.entity_id == "light.dachgeschoss_licht"


def test_resolve_entity_alias_collision_is_ambiguous():
    # Two entities that configured the same alias must not silently pick one.
    entities = [
        EntitySnapshot("light.a", "A", "light", "off", aliases=("Lieblingslicht",)),
        EntitySnapshot("light.b", "B", "light", "off", aliases=("Lieblingslicht",)),
    ]
    result = resolve_entity("Lieblingslicht", entities)
    assert result.status is ResolveStatus.AMBIGUOUS
    assert len(result.candidates) == 2
