"""Deterministic direct-control router for extended Home Assistant domains."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entities import EntitySnapshot, ResolveStatus, resolve_entity
from .service_call import ServiceCallPlan


@dataclass(frozen=True)
class DeviceControlResult:
    plan: ServiceCallPlan | None
    response_text: str
    requires_confirmation: bool = False


def _clean(text: str) -> str:
    return re.sub(r"[?.!]", "", text).strip()


def _resolve_domain(
    name: str, entities: list[EntitySnapshot], domain: str
) -> EntitySnapshot | None:
    result = resolve_entity(name.strip(), entities)
    if result.status is not ResolveStatus.OK or result.entity is None:
        return None
    return result.entity if result.entity.domain == domain else None


def _result(
    entity: EntitySnapshot,
    service: str,
    response: str,
    data: dict | None = None,
    *,
    confirm: bool = False,
) -> DeviceControlResult:
    return DeviceControlResult(
        ServiceCallPlan(entity.domain, service, entity.entity_id, data or {}),
        response,
        requires_confirmation=confirm,
    )


def match_device_control(
    text: str, entities: list[EntitySnapshot]
) -> DeviceControlResult | None:
    """Match extended device commands; return None for unrelated language."""
    value = _clean(text)

    match = re.fullmatch(
        r"stelle\s+(?:die\s+)?(?:temperatur\s+(?:von|bei)\s+)?(.+?)\s+auf\s+"
        r"(-?\d{1,2}(?:[,.]\d)?)\s*(?:grad|°c?)",
        value,
        re.IGNORECASE,
    )
    if match:
        entity = _resolve_domain(match.group(1), entities, "climate")
        if entity is None:
            return None
        temperature = float(match.group(2).replace(",", "."))
        minimum = float(entity.attributes.get("min_temp", 7))
        maximum = float(entity.attributes.get("max_temp", 35))
        if not minimum <= temperature <= maximum:
            return DeviceControlResult(
                None,
                f"Die Temperatur für {entity.friendly_name} muss zwischen "
                f"{minimum:g} und {maximum:g} Grad liegen.",
            )
        return _result(
            entity,
            "set_temperature",
            f"{entity.friendly_name} auf {temperature:g} Grad gestellt.",
            {"temperature": temperature},
        )

    match = re.fullmatch(
        r"(?:stelle|schalte)\s+(.+?)\s+auf\s+"
        r"(heizbetrieb|kühlbetrieb|kuehlbetrieb|automatik|entfeuchten|lüften|lueften)",
        value,
        re.IGNORECASE,
    )
    if match:
        entity = _resolve_domain(match.group(1), entities, "climate")
        if entity is None:
            return None
        raw_mode = match.group(2).casefold()
        mode = {
            "heizbetrieb": "heat",
            "kühlbetrieb": "cool",
            "kuehlbetrieb": "cool",
            "automatik": "auto",
            "entfeuchten": "dry",
            "lüften": "fan_only",
            "lueften": "fan_only",
        }[raw_mode]
        supported = entity.attributes.get("hvac_modes") or ()
        if mode not in supported:
            return DeviceControlResult(None, f"{entity.friendly_name} unterstützt diesen Betriebsmodus nicht.")
        return _result(
            entity,
            "set_hvac_mode",
            f"{entity.friendly_name} auf {match.group(2)} gestellt.",
            {"hvac_mode": mode},
        )

    match = re.fullmatch(
        r"stelle\s+(?:die\s+)?lautstärke\s+(?:von|am|auf dem)\s+(.+?)\s+auf\s+(\d{1,3})\s*(?:prozent|%)",
        value,
        re.IGNORECASE,
    )
    if match:
        entity = _resolve_domain(match.group(1), entities, "media_player")
        percent = int(match.group(2))
        if entity is None or not 0 <= percent <= 100:
            return None
        return _result(
            entity,
            "volume_set",
            f"Lautstärke von {entity.friendly_name} auf {percent} Prozent gestellt.",
            {"volume_level": percent / 100},
        )

    match = re.fullmatch(
        r"wähle\s+(?:auf|am)\s+(.+?)\s+die\s+quelle\s+(.+)",
        value,
        re.IGNORECASE,
    )
    if match:
        entity = _resolve_domain(match.group(1), entities, "media_player")
        if entity is None:
            return None
        requested = match.group(2).strip()
        sources = entity.attributes.get("source_list") or ()
        source = next(
            (candidate for candidate in sources if str(candidate).casefold() == requested.casefold()),
            None,
        )
        if source is None:
            return DeviceControlResult(None, f"Die Quelle {requested} ist auf {entity.friendly_name} nicht verfügbar.")
        return _result(
            entity,
            "select_source",
            f"Quelle {source} auf {entity.friendly_name} ausgewählt.",
            {"source": source},
        )

    media_patterns = (
        (r"starte\s+(?:die\s+)?wiedergabe\s+(?:auf|am)\s+(.+)", "media_play", "Wiedergabe gestartet."),
        (r"pausiere\s+(?:die\s+)?wiedergabe\s+(?:auf|am)\s+(.+)", "media_pause", "Wiedergabe pausiert."),
        (r"stoppe\s+(?:die\s+)?wiedergabe\s+(?:auf|am)\s+(.+)", "media_stop", "Wiedergabe gestoppt."),
    )
    for pattern, service, response in media_patterns:
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match and (entity := _resolve_domain(match.group(1), entities, "media_player")):
            return _result(entity, service, f"{entity.friendly_name}: {response}")

    vacuum_patterns = (
        (r"starte\s+(?:den\s+)?(.+)", "start", "gestartet"),
        (r"pausiere\s+(?:den\s+)?(.+)", "pause", "pausiert"),
        (r"stoppe\s+(?:den\s+)?(.+)", "stop", "gestoppt"),
        (r"schicke\s+(?:den\s+)?(.+?)\s+(?:zurück\s+)?zur\s+ladestation", "return_to_base", "zur Ladestation geschickt"),
    )
    for pattern, service, spoken in vacuum_patterns:
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match and (entity := _resolve_domain(match.group(1), entities, "vacuum")):
            return _result(entity, service, f"{entity.friendly_name} {spoken}.")

    match = re.fullmatch(r"aktiviere\s+(?:die\s+)?szene\s+(.+)", value, re.IGNORECASE)
    if match and (entity := _resolve_domain(match.group(1), entities, "scene")):
        return _result(entity, "turn_on", f"Szene {entity.friendly_name} aktiviert.")

    lock_patterns = (
        (r"schließe\s+(.+?)\s+ab", "lock", "abschließen"),
        (r"schließe\s+(.+?)\s+auf", "unlock", "aufschließen"),
        (r"verriegle\s+(.+)", "lock", "verriegeln"),
        (r"entriegle\s+(.+)", "unlock", "entriegeln"),
    )
    for pattern, service, spoken in lock_patterns:
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match and (entity := _resolve_domain(match.group(1), entities, "lock")):
            return _result(
                entity,
                service,
                f"{entity.friendly_name} {spoken}.",
                confirm=True,
            )

    match = re.fullmatch(r"(öffne|schließe)\s+(.+)", value, re.IGNORECASE)
    if match and (entity := _resolve_domain(match.group(2), entities, "cover")):
        if (entity.device_class or "").casefold() in {"garage", "garage_door"}:
            opening = match.group(1).casefold() == "öffne"
            return _result(
                entity,
                "open_cover" if opening else "close_cover",
                f"{entity.friendly_name} {'öffnen' if opening else 'schließen'}.",
                confirm=True,
            )
    return None
