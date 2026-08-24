"""Validated, explicit HomeIntent-only entity aliases."""

from __future__ import annotations

from collections import defaultdict


def parse_custom_aliases(value: object) -> dict[str, tuple[str, ...]]:
    """Parse ``spoken alias = entity.id`` lines; reject ambiguous mappings."""
    if value in (None, ""):
        return {}
    if not isinstance(value, str):
        raise ValueError("Aliasregeln müssen Textzeilen sein.")
    by_entity: dict[str, list[str]] = defaultdict(list)
    owners: dict[str, str] = {}
    for number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Aliaszeile {number} benötigt ein Gleichheitszeichen.")
        alias, entity_id = (part.strip() for part in line.split("=", 1))
        if not alias or "." not in entity_id or any(char.isspace() for char in entity_id):
            raise ValueError(f"Aliaszeile {number} ist ungültig.")
        alias_key = alias.casefold()
        previous = owners.get(alias_key)
        if previous is not None and previous != entity_id:
            raise ValueError(f"Der Alias „{alias}“ hat mehrere Ziele.")
        owners[alias_key] = entity_id
        if alias not in by_entity[entity_id]:
            by_entity[entity_id].append(alias)
    return {entity_id: tuple(aliases) for entity_id, aliases in by_entity.items()}
