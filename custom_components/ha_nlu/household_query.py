"""Read-only household knowledge composed from the current HA snapshot."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Mapping, cast

from .device_control import DeviceControlResult
from .entities import EntitySnapshot, normalize_for_compare
from .nlu.domain_operations import DOMAIN_WORDS
from .nlu.language_frontend import LanguageDocument
from .nlu.normalize import normalize
from .nlu.semantic_utterance import SpeechAct
from .query_target import list_attribute_values, mentioned_entities, resolve_query_targets


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


def _target_for_capability_query(
    text: str, entities: list[EntitySnapshot]
) -> tuple[EntitySnapshot, ...]:
    return resolve_query_targets(text, entities, frozenset(_CAPABILITY_LABELS))


def _numeric_state(entity: EntitySnapshot) -> float | None:
    try:
        return float(str(entity.state).replace(",", "."))
    except (TypeError, ValueError):
        return None


def match_household_query(
    text: str,
    entities: list[EntitySnapshot],
    now: datetime,
    document: LanguageDocument | None = None,
) -> DeviceControlResult | None:
    """Answer deterministic household questions without creating a plan."""
    if document is not None and document.utterance.speech_act is not SpeechAct.QUERY:
        return None
    value = document.normalized_text if document is not None else normalize(text)
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
        people = mentioned_entities(value, [e for e in entities if e.domain == "person"])
        if len(people) == 1:
            person = people[0]
            return _read_only(
                f"{person.friendly_name} ist laut Home Assistant "
                f"{'zuhause' if person.state == 'home' else 'nicht zuhause'}."
            )
        if len(people) > 1:
            return _read_only("Welche Person meinst du?")

    if re.search(r"\b(?:gibt\s+es\s+)?(?:probleme|stoerungen|fehler)\s+(?:im|zu\s+hause|daheim)\b", key):
        unavailable = [
            entity.friendly_name for entity in entities
            if normalize_for_compare(entity.state) in {"unknown", "unavailable"}
        ]
        weak_batteries = [
            f"{entity.friendly_name} ({value:g} Prozent)"
            for entity in entities
            if entity.domain == "sensor" and entity.device_class == "battery"
            and (value := _numeric_state(entity)) is not None and value < 20
        ]
        if not unavailable and not weak_batteries:
            return _read_only("Ich sehe derzeit keine nicht verfügbaren Geräte oder schwachen Batterien.")
        parts: list[str] = []
        if unavailable:
            parts.append("Nicht verfügbar: " + ", ".join(unavailable[:8]))
        if weak_batteries:
            parts.append("Schwache Batterien: " + ", ".join(weak_batteries[:8]))
        return _read_only(". ".join(parts) + ".")

    battery_limit = re.search(
        r"\b(?:welche|zeige|gibt\s+es).*\bbatter(?:ie|ien)\b.*?"
        r"(?:unter|kleiner\s+als|weniger\s+als)\s*(\d{1,3})\s*(?:prozent|%)",
        key,
    )
    if battery_limit is not None:
        limit = min(100, int(battery_limit.group(1)))
        matches = [
            (entity, value) for entity in entities
            if entity.domain == "sensor" and entity.device_class == "battery"
            and (value := _numeric_state(entity)) is not None and value < limit
        ]
        if not matches:
            return _read_only(f"Keine bekannte Batterie liegt unter {limit} Prozent.")
        return _read_only(
            f"Unter {limit} Prozent: " + ", ".join(
                f"{entity.friendly_name} mit {value:g} Prozent"
                for entity, value in sorted(matches, key=lambda item: item[1])
            ) + "."
        )

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

    # A specifically named outdoor measurement belongs to HassGetState,
    # not to the broader weather summary below. Prefer the live temperature
    # sensor when one is available; the engine then uses the stated property
    # to distinguish it from battery/humidity/link-quality siblings.
    if "aussentemperatur" in key and any(
        entity.domain == "sensor" and entity.device_class == "temperature"
        for entity in entities
    ):
        return None

    if re.search(
        r"\b(?:wie\s+ist\s+das\s+wetter|welches\s+wetter|aussen(?:temperatur)?|"
        r"wie\s+(?:warm|kalt)\s+ist\s+es\s+(?:draussen|aussen))\b",
        key,
    ):
        weather_entities = [e for e in entities if e.domain == "weather"]
        mentioned = mentioned_entities(value, weather_entities)
        choices = list(mentioned) or weather_entities
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

    if re.search(r"\b(?:wie\s+wird|wetter|vorhersage)\b.*\b(?:morgen|uebermorgen)\b", key):
        weather_entities = [e for e in entities if e.domain == "weather"]
        if len(weather_entities) != 1:
            return _read_only("Welche Wetter-Entität meinst du?") if weather_entities else None
        forecast = weather_entities[0].attributes.get("forecast")
        if not isinstance(forecast, (list, tuple)) or not forecast:
            return _read_only("Die Wetter-Entität stellt aktuell keine Vorhersage bereit.")
        day_offset = 2 if "uebermorgen" in key else 1
        target_date = now.date() + timedelta(days=day_offset)
        forecast_values = cast(list[object] | tuple[object, ...], forecast)
        rows = [
            cast(Mapping[str, object], item)
            for item in forecast_values if isinstance(item, dict)
        ]
        row = next((
            item for item in rows
            if str(item.get("datetime", "")).startswith(target_date.isoformat())
        ), None)
        if row is None:
            return _read_only("Für diesen Tag ist keine Wettervorhersage verfügbar.")
        condition = _WEATHER_DE.get(str(row.get("condition", "")), str(row.get("condition", "")))
        temperatures: list[str] = []
        if row.get("temperature") is not None:
            temperatures.append(f"bis {row['temperature']} Grad")
        if row.get("templow") is not None:
            temperatures.append(f"mindestens {row['templow']} Grad")
        label = "übermorgen" if day_offset == 2 else "morgen"
        return _read_only(
            f"{label.capitalize()} wird es {condition}"
            + ((", " + ", ".join(temperatures)) if temperatures else "") + "."
        )

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
        options = list_attribute_values(entity, attribute_keys)
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
