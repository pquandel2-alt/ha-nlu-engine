"""Deterministic direct-control router for extended Home Assistant domains."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entities import EntitySnapshot, ResolveStatus, normalize_for_compare, resolve_entity
from .nlu.context import ConversationContext
from .nlu.normalize import normalize
from .nlu.semantic_utterance import SpeechAct, analyse_utterance
from .service_call import ServiceCallPlan
from .risk import requires_confirmation


@dataclass(frozen=True)
class DeviceControlResult:
    plan: ServiceCallPlan | None
    response_text: str
    requires_confirmation: bool = False
    entity: EntitySnapshot | None = None
    entities: tuple[EntitySnapshot, ...] = ()
    is_query: bool = False

    @property
    def resolved_entities(self) -> tuple[EntitySnapshot, ...]:
        """Return every exact target while preserving singular compatibility."""
        if self.entities:
            return self.entities
        return (self.entity,) if self.entity is not None else ()


def _clean(text: str) -> str:
    return re.sub(r"[?.!]", "", normalize(text)).strip()


def _resolve_domain(
    name: str, entities: list[EntitySnapshot], domain: str
) -> EntitySnapshot | None:
    result = resolve_entity(
        name.strip(), [entity for entity in entities if entity.domain == domain]
    )
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
        (plan := ServiceCallPlan(entity.domain, service, entity.entity_id, data or {})),
        response,
        requires_confirmation=confirm or requires_confirmation(plan, [entity]),
        entity=entity,
        entities=(entity,),
    )


def _mentioned_entity(
    text: str,
    entities: list[EntitySnapshot],
    domains: frozenset[str],
) -> EntitySnapshot | None:
    """Resolve one explicitly mentioned registry name independent of order."""
    normalized = normalize_for_compare(text)
    ranked: list[tuple[int, EntitySnapshot]] = []
    for entity in entities:
        if entity.domain not in domains:
            continue
        names = (entity.friendly_name, *entity.aliases)
        best = max(
            (
                len(candidate_norm)
                for name in names
                if (candidate_norm := normalize_for_compare(name))
                and re.search(rf"(?<!\w){re.escape(candidate_norm)}(?!\w)", normalized)
            ),
            default=0,
        )
        if best:
            ranked.append((best, entity))
    if not ranked:
        return None
    top = max(score for score, _ in ranked)
    matches = [entity for score, entity in ranked if score == top]
    return matches[0] if len(matches) == 1 else None


def _match_compositional(
    text: str, entities: list[EntitySnapshot]
) -> DeviceControlResult | None:
    """Compose extended-domain controls from target, action and value.

    This fallback deliberately scans independent meaning components rather
    than enumerating their sentence order. An exact registry-name mention,
    one supported operation and all required values are mandatory.
    """
    value = _clean(text)
    if re.search(r"\b(?:nicht|kein\w*|ohne|vielleicht|normalerweise|gestern)\b", value, re.I):
        return None

    climate = _mentioned_entity(value, entities, frozenset({"climate"}))
    temperature = re.search(
        r"\bauf\s+(-?\d{1,2}(?:[,.]\d)?)\s*(?:grad|°c?)\b", value, re.I
    )
    if (
        climate is not None
        and temperature is not None
        and re.search(r"\b(?:stell\w*|setz\w*|regel\w*|aender\w*|änder\w*)\b", value, re.I)
    ):
        requested = float(temperature.group(1).replace(",", "."))
        minimum = float(climate.attributes.get("min_temp", 7))
        maximum = float(climate.attributes.get("max_temp", 35))
        if not minimum <= requested <= maximum:
            return DeviceControlResult(
                None,
                f"Die Temperatur für {climate.friendly_name} muss zwischen "
                f"{minimum:g} und {maximum:g} Grad liegen.",
            )
        return _result(
            climate,
            "set_temperature",
            f"{climate.friendly_name} auf {requested:g} Grad gestellt.",
            {"temperature": requested},
        )

    if climate is not None:
        climate_options = (
            ("preset_modes", "preset", "set_preset_mode", "preset_mode"),
            ("fan_modes", "lüftermodus", "set_fan_mode", "fan_mode"),
            ("swing_modes", "schwenkmodus", "set_swing_mode", "swing_mode"),
        )
        option_matches: list[tuple[str, str, str]] = []
        normalized_value = normalize_for_compare(value)
        for attribute, spoken_kind, service, data_key in climate_options:
            for option in climate.attributes.get(attribute, ()) or ():
                option_text = normalize_for_compare(str(option))
                if option_text and re.search(
                    rf"(?<!\w){re.escape(option_text)}(?!\w)", normalized_value
                ):
                    option_matches.append((service, data_key, str(option)))
        if len(option_matches) == 1 and re.search(
            r"\b(?:stell\w*|setz\w*|wähl\w*|waehl\w*|aktivier\w*)\b", value, re.I
        ):
            service, data_key, option = option_matches[0]
            return _result(
                climate,
                service,
                f"{climate.friendly_name} auf {option} gestellt.",
                {data_key: option},
            )

    player = _mentioned_entity(value, entities, frozenset({"media_player"}))
    if player is not None:
        volume = re.search(r"\b(100|[1-9]?\d)\s*(?:prozent|%)\b", value, re.I)
        if (
            volume is not None
            and re.search(r"\blautstärke\b", value, re.I)
            and re.search(r"\b(?:stell\w*|setz\w*|mach\w*|regel\w*)\b", value, re.I)
        ):
            percent = int(volume.group(1))
            return _result(
                player,
                "volume_set",
                f"Lautstärke von {player.friendly_name} auf {percent} Prozent gestellt.",
                {"volume_level": percent / 100},
            )
        if re.search(r"\bquelle\b", value, re.I) and re.search(
            r"\b(?:aus)?(?:wähl\w*|waehl\w*)\b", value, re.I
        ):
            sources = player.attributes.get("source_list") or ()
            selected = [
                source for source in sources
                if re.search(
                    rf"(?<!\w){re.escape(normalize_for_compare(str(source)))}(?!\w)",
                    normalize_for_compare(value),
                )
            ]
            if len(selected) == 1:
                return _result(
                    player,
                    "select_source",
                    f"Quelle {selected[0]} auf {player.friendly_name} ausgewählt.",
                    {"source": selected[0]},
                )
        if re.search(r"\bwiedergabe\b", value, re.I):
            operations = [
                (pattern, service, speech)
                for pattern, service, speech in (
                    (r"\b(?:start\w*|spiel\w*)\b", "media_play", "Wiedergabe gestartet."),
                    (r"\bpaus\w*\b", "media_pause", "Wiedergabe pausiert."),
                    (r"\bstopp\w*\b", "media_stop", "Wiedergabe gestoppt."),
                )
                if re.search(pattern, value, re.I)
            ]
            if len(operations) == 1:
                _, service, speech = operations[0]
                return _result(player, service, f"{player.friendly_name}: {speech}")

    fan = _mentioned_entity(value, entities, frozenset({"fan"}))
    if fan is not None:
        normalized_value = normalize_for_compare(value)
        presets = [
            str(option) for option in fan.attributes.get("preset_modes", ()) or ()
            if (key := normalize_for_compare(str(option)))
            and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", normalized_value)
        ]
        if len(presets) == 1 and re.search(r"\b(?:preset|modus|stell\w*|wähl\w*|waehl\w*)\b", value, re.I):
            return _result(
                fan, "set_preset_mode", f"{fan.friendly_name} auf {presets[0]} gestellt.",
                {"preset_mode": presets[0]},
            )
        oscillation = re.search(r"\b(?:oszillier\w*|schwenk\w*)\b", value, re.I)
        if oscillation:
            on = re.search(r"\b(?:an|ein|aktivier\w*|einschalt\w*)\b", value, re.I)
            off = re.search(r"\b(?:aus|deaktivier\w*|ausschalt\w*)\b", value, re.I)
            if bool(on) != bool(off):
                return _result(
                    fan, "oscillate",
                    f"Oszillation von {fan.friendly_name} {'eingeschaltet' if on else 'ausgeschaltet'}.",
                    {"oscillating": bool(on)},
                )
        direction = re.search(r"\b(?:vorwärts|vorwaerts|rückwärts|rueckwaerts|forward|reverse)\b", value, re.I)
        if direction and re.search(r"\b(?:richtung|stell\w*|setz\w*)\b", value, re.I):
            forward = direction.group(0).casefold() in {"vorwärts", "vorwaerts", "forward"}
            return _result(
                fan, "set_direction", f"Richtung von {fan.friendly_name} eingestellt.",
                {"direction": "forward" if forward else "reverse"},
            )

    cover = _mentioned_entity(value, entities, frozenset({"cover"}))
    if cover is not None:
        tilt = re.search(r"\b(100|[1-9]?\d)\s*(?:prozent|%)\b", value, re.I)
        if tilt and re.search(r"\b(?:lamellen|neigung|winkel|kippposition)\b", value, re.I):
            percent = int(tilt.group(1))
            return _result(
                cover, "set_cover_tilt_position",
                f"Lamellen von {cover.friendly_name} auf {percent} Prozent gestellt.",
                {"tilt_position": percent},
            )

    vacuum = _mentioned_entity(value, entities, frozenset({"vacuum"}))
    if vacuum is not None:
        normalized_value = normalize_for_compare(value)
        speeds = [
            str(option) for option in vacuum.attributes.get("fan_speed_list", ()) or ()
            if (key := normalize_for_compare(str(option)))
            and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", normalized_value)
        ]
        if len(speeds) == 1 and re.search(r"\b(?:saugstärke|saugstaerke|leistung|modus|stell\w*)\b", value, re.I):
            return _result(
                vacuum, "set_fan_speed",
                f"Saugstärke von {vacuum.friendly_name} auf {speeds[0]} gestellt.",
                {"fan_speed": speeds[0]},
            )
        if (
            re.search(r"\bladestation\b", value, re.I)
            and re.search(r"\b(?:schick\w*|fahr\w*|soll\w*)\b", value, re.I)
        ):
            return _result(
                vacuum, "return_to_base",
                f"{vacuum.friendly_name} zur Ladestation geschickt.",
            )
        operations = [
            (pattern, service, word)
            for pattern, service, word in (
                (r"\bstart\w*\b", "start", "gestartet"),
                (r"\bpaus\w*\b", "pause", "pausiert"),
                (r"\bstopp\w*\b", "stop", "gestoppt"),
            )
            if re.search(pattern, value, re.I)
        ]
        if len(operations) == 1:
            _, service, word = operations[0]
            return _result(vacuum, service, f"{vacuum.friendly_name} {word}.")

    scene = _mentioned_entity(value, entities, frozenset({"scene"}))
    if scene is not None and re.search(r"\b(?:aktivier\w*|einschalt\w*)\b", value, re.I):
        return _result(scene, "turn_on", f"Szene {scene.friendly_name} aktiviert.")

    group = _mentioned_entity(value, entities, frozenset({"group"}))
    if group is not None:
        if re.search(r"\b(?:einschalt|aktivier|mach\w*\s+an)\w*\b", value, re.I):
            return DeviceControlResult(
                ServiceCallPlan("homeassistant", "turn_on", group.entity_id, {}),
                f"Gruppe {group.friendly_name} eingeschaltet.",
                requires_confirmation=True, entity=group,
            )
        if re.search(r"\b(?:ausschalt|deaktivier|mach\w*\s+aus)\w*\b", value, re.I):
            return DeviceControlResult(
                ServiceCallPlan("homeassistant", "turn_off", group.entity_id, {}),
                f"Gruppe {group.friendly_name} ausgeschaltet.",
                requires_confirmation=True, entity=group,
            )
    return None


def match_device_control_followup(
    text: str,
    context: ConversationContext | None,
    entities: list[EntitySnapshot] | None = None,
) -> DeviceControlResult | None:
    """Resolve a safe, target-elliptical operation against prior focus.

    The existing device parser remains the single source of operation and
    capability semantics.  This function supplies only one exact previous
    target.  Longer utterances require an explicit anaphoric cue; this keeps
    an unknown new device name from being redirected to the previous device.
    """
    if context is None or len(context.last_entities) != 1:
        return None
    entity = context.last_entities[0]
    value = _clean(text)
    utterance = analyse_utterance(value)
    if utterance.speech_act in {SpeechAct.AUTOMATION, SpeechAct.QUERY} or (
        utterance.speech_act is SpeechAct.COMMAND
        and not utterance.safe_to_execute_directly
    ):
        return None
    words = re.findall(r"\b\w+\b", value, re.UNICODE)
    has_reference = re.search(
        r"\b(?:und|es|ihn|sie|das|dies(?:e|er|es)?|dort|auch|weiter|wieder)\b",
        value,
        re.I,
    ) is not None
    if len(words) > 4 and not has_reference:
        return None

    # Do not steal a turn that names another known entity.  The ordinary
    # router has already had its chance, but an unsupported operation on a
    # newly named device must still fail rather than affect old context.
    if entities is not None:
        named = _mentioned_entity(
            value,
            entities,
            frozenset(entity.domain for entity in entities),
        )
        if named is not None and named.entity_id != entity.entity_id:
            return None
    if entity.domain == "media_player":
        operations = [
            (service, speech)
            for pattern, service, speech in (
                (r"\bpaus\w*\b", "media_pause", "Wiedergabe pausiert."),
                (r"\b(?:spiel\w*|weiterspiel\w*|start\w*|fortsetz\w*)\b", "media_play", "Wiedergabe fortgesetzt."),
                (r"\bstopp\w*\b", "media_stop", "Wiedergabe gestoppt."),
            )
            if re.search(pattern, value, re.I)
        ]
        if len(operations) == 1:
            service, speech = operations[0]
            return _result(entity, service, f"{entity.friendly_name}: {speech}")
    if entity.domain == "vacuum":
        operations = [
            (service, speech)
            for matched, service, speech in (
                (re.search(r"\bpaus\w*\b", value, re.I), "pause", "pausiert"),
                (re.search(r"\bstopp\w*\b", value, re.I), "stop", "gestoppt"),
                (re.search(r"\bstart\w*\b|\bweitermach\w*\b", value, re.I), "start", "gestartet"),
                (re.search(r"\b(?:lade)?station\b|\bdock\w*\b", value, re.I), "return_to_base", "zur Ladestation geschickt"),
            )
            if matched is not None
        ]
        if len(operations) == 1:
            service, speech = operations[0]
            return _result(entity, service, f"{entity.friendly_name} {speech}.")

    # Reuse the complete capability-driven router by adding the exact prior
    # registry name, never by guessing an entity from free text.  "stelle"
    # supplies the omitted command marker for terse value/option follow-ups;
    # operation-specific parsers still have to prove a unique valid action.
    contextual_text = f"stelle {entity.friendly_name} {value}"
    return match_device_control(contextual_text, [entity])
    return None


def match_device_control(
    text: str, entities: list[EntitySnapshot]
) -> DeviceControlResult | None:
    """Match extended device commands; return None for unrelated language."""
    value = _clean(text)
    utterance = analyse_utterance(value)
    if utterance.speech_act in {SpeechAct.AUTOMATION, SpeechAct.QUERY} or (
        utterance.speech_act is SpeechAct.COMMAND
        and not utterance.safe_to_execute_directly
    ):
        return None
    if re.search(r"\b(?:nicht|kein\w*|ohne|vielleicht|normalerweise|gestern)\b", value, re.I):
        return None

    climate = _mentioned_entity(value, entities, frozenset({"climate"}))
    mode_match = re.search(
        r"\b(heizbetrieb|kühlbetrieb|kuehlbetrieb|automatik|entfeuchten|lüften|lueften)\b",
        value,
        re.I,
    )
    if climate is not None and mode_match is not None and re.search(
        r"\b(?:stell\w*|schalt\w*|setz\w*)\b", value, re.I
    ):
        raw_mode = mode_match.group(1).casefold()
        mode = {
            "heizbetrieb": "heat", "kühlbetrieb": "cool", "kuehlbetrieb": "cool",
            "automatik": "auto", "entfeuchten": "dry", "lüften": "fan_only",
            "lueften": "fan_only",
        }[raw_mode]
        if mode not in (climate.attributes.get("hvac_modes") or ()):
            return DeviceControlResult(
                None, f"{climate.friendly_name} unterstützt diesen Betriebsmodus nicht."
            )
        return _result(
            climate,
            "set_hvac_mode",
            f"{climate.friendly_name} auf {mode_match.group(1)} gestellt.",
            {"hvac_mode": mode},
        )

    match = re.fullmatch(
        r"stelle\s+(?:die\s+)?(?:temperatur\s+(?:von|bei)\s+)?(.+?)\s+auf\s+"
        r"(-?\d{1,2}(?:[,.]\d)?)\s*(?:grad|°c?)",
        value,
        re.IGNORECASE,
    )
    if match and (entity := _resolve_domain(match.group(1), entities, "climate")):
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
    compositional = _match_compositional(value, entities)
    if compositional is not None:
        return compositional
    # Imported lazily to keep the shared resolver/result helpers in this
    # established module without creating an import cycle.
    from .extended_device_control import match_extended_device_control

    return match_extended_device_control(value, entities, _mentioned_entity, _result)
