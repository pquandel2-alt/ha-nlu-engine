"""Read-only household knowledge composed from the current HA snapshot."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .device_control import DeviceControlResult
from .entities import EntitySnapshot, normalize_for_compare
from .entity_scope import resolve_entity_scope
from .nlu.domain_operations import DOMAIN_WORDS
from .nlu.normalize import normalize


_WEEKDAYS_DE = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"
)
_MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)
_WEATHER_DE = {
    "clear-night": "klar", "cloudy": "bewölkt", "exceptional": "außergewöhnlich",
    "fog": "neblig", "hail": "Hagel", "lightning": "Gewitter",
    "lightning-rainy": "Gewitter mit Regen", "partlycloudy": "teilweise bewölkt",
    "pouring": "starker Regen", "rainy": "regnerisch", "snowy": "Schnee",
    "snowy-rainy": "Schneeregen", "sunny": "sonnig", "windy": "windig",
    "windy-variant": "windig und bewölkt",
}

_CAPABILITY_LABELS = {
    "light": "ein- und ausschalten sowie – falls gemeldet – Helligkeit und Farbe einstellen",
    "switch": "ein-, aus- und umschalten",
    "cover": "öffnen, schließen und positionieren",
    "fan": "ein-, ausschalten und Geschwindigkeit oder Preset einstellen",
    "climate": "ein-, ausschalten sowie Temperatur und angebotene Modi einstellen",
    "media_player": "Wiedergabe steuern sowie Lautstärke und angebotene Quellen wählen",
    "vacuum": "starten, pausieren, stoppen und zur Ladestation schicken",
    "scene": "aktivieren",
    "script": "starten",
    "humidifier": "ein-, ausschalten sowie Zielfeuchte und Modus einstellen",
    "water_heater": "Temperatur und angebotenen Betriebsmodus einstellen",
    "number": "einen Wert innerhalb der gemeldeten Grenzen einstellen",
    "input_number": "einen Wert innerhalb der gemeldeten Grenzen einstellen",
    "input_boolean": "ein-, aus- und umschalten",
    "select": "eine der angebotenen Optionen auswählen",
    "valve": "nach Bestätigung öffnen, schließen oder positionieren",
    "lawn_mower": "starten, pausieren und zur Ladestation schicken",
    "camera": "auf einem Medienplayer anzeigen",
    "lock": "verriegeln und nach Bestätigung entriegeln",
    "button": "nach Bestätigung drücken",
}


def _read_only(text: str) -> DeviceControlResult:
    return DeviceControlResult(None, text, is_query=True)


def _format_datetime(value: object, now: datetime) -> str | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None and now.tzinfo is not None:
        value = value.astimezone(now.tzinfo)
    day = "heute" if value.date() == now.date() else (
        "morgen" if value.date() == now.date() + timedelta(days=1)
        else f"am {value.day}. {_MONTHS_DE[value.month - 1]}"
    )
    return f"{day} um {value:%H:%M} Uhr"


def _mentioned(text: str, entities: list[EntitySnapshot]) -> list[EntitySnapshot]:
    normalized = normalize_for_compare(text)
    found: list[tuple[int, EntitySnapshot]] = []
    for entity in entities:
        score = max(
            (
                len(key)
                for name in (entity.friendly_name, *entity.aliases)
                if (key := normalize_for_compare(name))
                and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", normalized)
            ),
            default=0,
        )
        if score:
            found.append((score, entity))
    if not found:
        return []
    best = max(score for score, _ in found)
    return [entity for score, entity in found if score == best]


def _target_for_capability_query(
    text: str, entities: list[EntitySnapshot]
) -> tuple[EntitySnapshot, ...]:
    mentioned = _mentioned(text, entities)
    if mentioned:
        return tuple(mentioned)
    scope = resolve_entity_scope(text, entities, frozenset(_CAPABILITY_LABELS))
    if scope is not None:
        return tuple(scope.entities)
    normalized = normalize_for_compare(text)
    spoken_domains = {
        domain
        for domain, words in DOMAIN_WORDS.items()
        if domain in _CAPABILITY_LABELS
        and any(
            re.search(
                rf"(?<!\w){re.escape(normalize_for_compare(word))}(?!\w)",
                normalized,
            )
            for word in words
        )
    }
    candidates = [entity for entity in entities if entity.domain in spoken_domains]
    spoken_areas = {
        entity.area_id
        for entity in candidates
        if entity.area_id
        and any(
            area
            and re.search(
                rf"(?<!\w){re.escape(normalize_for_compare(area))}(?!\w)",
                normalized,
            )
            for area in (entity.area_name, *entity.area_aliases)
        )
    }
    if spoken_areas:
        candidates = [entity for entity in candidates if entity.area_id in spoken_areas]
    return tuple(candidates)


def _list_values(entity: EntitySnapshot, keys: tuple[str, ...]) -> tuple[str, ...]:
    for key in keys:
        raw = entity.attributes.get(key)
        if isinstance(raw, (list, tuple)):
            return tuple(str(value) for value in raw if str(value).strip())
    return ()


def match_household_query(
    text: str, entities: list[EntitySnapshot], now: datetime
) -> DeviceControlResult | None:
    """Answer deterministic household questions without creating a plan."""
    value = normalize(text)
    key = normalize_for_compare(value)

    if re.search(r"\b(?:wie\s+spaet|wieviel\s+uhr|welche\s+uhrzeit)\b", key):
        return _read_only(f"Es ist {now:%H:%M} Uhr.")
    if re.search(r"\b(?:welches\s+datum|welcher\s+tag|was\s+haben\s+wir\s+heute)\b", key):
        return _read_only(
            f"Heute ist {_WEEKDAYS_DE[now.weekday()]}, der {now.day}. {_MONTHS_DE[now.month - 1]} {now.year}."
        )

    if re.search(r"\bwas\s+kannst\s+du\b", key):
        return _read_only(
            "Ich kann Geräte steuern und abfragen, Automationen und Erinnerungen erstellen, "
            "Kalender, Aufgabenlisten und Timer verwalten sowie Zustände, Verlauf, "
            "Anwesenheit, Wetter und Gerätefähigkeiten erklären."
        )

    if re.search(r"\bwer\s+ist\s+(?:zu\s*hause|daheim|anwesend)\b", key):
        people = [
            entity.friendly_name for entity in entities
            if entity.domain == "person" and entity.state == "home"
        ]
        if not people:
            return _read_only("Laut Home Assistant ist derzeit niemand zuhause.")
        return _read_only("Zuhause: " + ", ".join(people) + ".")

    presence = re.search(r"\bist\s+(.+?)\s+(?:zu\s*hause|daheim|anwesend)\b", key)
    if presence is not None:
        people = _mentioned(value, [e for e in entities if e.domain == "person"])
        if len(people) == 1:
            person = people[0]
            return _read_only(
                f"{person.friendly_name} ist laut Home Assistant "
                f"{'zuhause' if person.state == 'home' else 'nicht zuhause'}."
            )
        if len(people) > 1:
            return _read_only("Welche Person meinst du?")

    if re.search(r"\bwann\s+geht\s+die\s+sonne\s+(?:auf|unter)\b", key):
        sun = next((entity for entity in entities if entity.entity_id == "sun.sun"), None)
        if sun is None:
            return _read_only("Ich finde in Home Assistant keine Sonneninformationen.")
        rising = re.search(r"\bauf\b", key) is not None
        rendered = _format_datetime(
            sun.attributes.get("next_rising" if rising else "next_setting"), now
        )
        if rendered is None:
            return _read_only("Die nächste Sonnenzeit ist derzeit nicht verfügbar.")
        return _read_only(f"Die Sonne geht {rendered} {'auf' if rising else 'unter'}.")

    if re.search(
        r"\b(?:wie\s+ist\s+das\s+wetter|welches\s+wetter|aussen(?:temperatur)?|"
        r"wie\s+(?:warm|kalt)\s+ist\s+es\s+(?:draussen|aussen))\b",
        key,
    ):
        weather_entities = [e for e in entities if e.domain == "weather"]
        mentioned = _mentioned(value, weather_entities)
        choices = mentioned or weather_entities
        if len(choices) > 1:
            return _read_only("Welche Wetter-Entität meinst du?")
        if not choices:
            return _read_only("Ich finde in Home Assistant keine Wetter-Entität.")
        weather = choices[0]
        condition = _WEATHER_DE.get(weather.state, weather.state)
        temperature = weather.attributes.get("temperature")
        humidity = weather.attributes.get("humidity")
        details = [condition]
        if temperature is not None:
            details.append(f"{temperature} Grad")
        if humidity is not None:
            details.append(f"{humidity} Prozent Luftfeuchtigkeit")
        return _read_only(f"{weather.friendly_name}: " + ", ".join(details) + ".")

    catalogue = re.search(r"\bwelche\s+(szenen|skripte)\s+(?:gibt\s+es|sind\s+verfuegbar)\b", key)
    if catalogue is not None:
        domain = "scene" if catalogue.group(1) == "szenen" else "script"
        names = sorted(e.friendly_name for e in entities if e.domain == domain)
        if not names:
            return _read_only(f"Es sind keine {'Szenen' if domain == 'scene' else 'Skripte'} verfügbar.")
        return _read_only(
            f"Verfügbare {'Szenen' if domain == 'scene' else 'Skripte'}: "
            + ", ".join(names[:12])
            + (f" und {len(names) - 12} weitere" if len(names) > 12 else "")
            + "."
        )

    option_query = re.search(
        r"\bwelche\s+(quellen|optionen|modi|betriebsarten|presets|stufen)\b", key
    )
    if option_query is not None:
        # Query nouns such as "Modi" are also legitimate entity nouns for
        # helpers. Remove the requested property before resolving the target
        # so "Modi der Heizung" cannot create a fake input_boolean domain.
        target_text = re.sub(
            r"\bwelche\s+(?:quellen|optionen|modi|betriebsarten|presets|stufen)\b",
            "",
            value,
            flags=re.I,
        )
        targets = _target_for_capability_query(target_text, entities)
        if len(targets) != 1:
            return _read_only("Welches Gerät meinst du?") if targets else None
        entity = targets[0]
        attribute_keys = {
            "quellen": ("source_list",),
            "optionen": ("options",),
            "modi": ("hvac_modes", "available_modes", "operation_list"),
            "betriebsarten": ("hvac_modes", "operation_list"),
            "presets": ("preset_modes",),
            "stufen": ("fan_speed_list", "preset_modes"),
        }[option_query.group(1)]
        options = _list_values(entity, attribute_keys)
        if not options:
            return _read_only(f"{entity.friendly_name} meldet dafür keine Auswahlmöglichkeiten.")
        return _read_only(f"{entity.friendly_name} bietet: " + ", ".join(options) + ".")

    if re.search(r"\bwas\s+kann\b", key):
        targets = _target_for_capability_query(value, entities)
        if len(targets) > 1:
            return _read_only("Welches Gerät meinst du?")
        if len(targets) == 1:
            entity = targets[0]
            label = _CAPABILITY_LABELS.get(entity.domain)
            if label is not None:
                return _read_only(f"{entity.friendly_name} kann ich {label}.")

    return None


QUERYABLE_HOUSEHOLD_DOMAINS = frozenset(DOMAIN_WORDS) | frozenset({
    "person", "weather", "sun", "scene", "script",
})
