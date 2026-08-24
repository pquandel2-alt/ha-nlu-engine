from __future__ import annotations

import pytest

from ha_nlu.customization import parse_custom_aliases


def test_custom_aliases_are_grouped_by_entity_and_comments_are_ignored():
    assert parse_custom_aliases(
        "# lokale Begriffe\nLeselampe = light.sofa\nSofalicht=light.sofa\n"
    ) == {"light.sofa": ("Leselampe", "Sofalicht")}


@pytest.mark.parametrize(
    "rules",
    (
        "ohne Ziel",
        "Alias = kein_entity_id",
        "Alias = light.one\nalias = light.two",
    ),
)
def test_invalid_or_ambiguous_alias_rules_are_rejected(rules: str):
    with pytest.raises(ValueError):
        parse_custom_aliases(rules)
