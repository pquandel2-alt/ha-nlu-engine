"""Automation Preview (HomeIntent V5 Teil 7/10, V5.23-V5.24): the first
spoken German rendering of an ``AutomationModel`` meant for a human to
actually confirm ("Automation erkannt: Wenn ..., dann ... Soll diese
Automation erstellt werden?") - distinct from ``automation_model.py``'s/
``condition_model.py``'s/``action_model.py``'s ``render_automation_tree()``/
``render_condition_tree()``/``render_action_step()``, which are all
explicitly documented in their own docstrings as debug-only, never a spoken
preview. Follows ``automation_validator.py``'s precedent of a dedicated
module combining all three semantic-model packages (Regel 6, not folded
into any one of them - would reopen the same import-cycle problem those
three modules already avoid via ``TYPE_CHECKING``/function-local imports).

Never invents information the model doesn't actually carry (Regel 4): where
an upstream parser structurally cannot distinguish two outcomes (e.g.
``TriggerType.PRESENCE`` never records arrival vs. departure - see
``automation_trigger_parser.py``'s ``_parse_presence_trigger`` docstring),
this module renders the truthful, direction-neutral phrasing rather than
guessing "Ankunft" or "Verlassen". Every lookup (entity friendly name, area
name, color word) falls back to the raw stored value instead of raising -
same "never crash on an unrecognized value" posture ``service_call.py``'s
own spoken-response helpers already take.
"""

from __future__ import annotations

from ..entities import EntitySnapshot
from .action_model import ActionGroup, ActionModel, ActionType, ExecutionMode
from .automation_model import AutomationModel, NumericComparator, SunEvent, TriggerModel, TriggerTarget, TriggerType
from .condition_model import ConditionModel, ConditionNode, ConditionType, LogicalOperator, TimeComparator
from .semantic_state import SemanticState

_STATE_SPOKEN_DE = {
    SemanticState.OPEN: "geöffnet",
    SemanticState.CLOSED: "geschlossen",
    SemanticState.ON: "eingeschaltet",
    SemanticState.OFF: "ausgeschaltet",
    SemanticState.UNKNOWN: "in unbekanntem Zustand",
}

_DOMAIN_NOUN_DE = {
    "light": "Licht", "switch": "Schalter", "fan": "Ventilator", "cover": "Rollladen",
    "climate": "Heizung", "binary_sensor": "Sensor", "sensor": "Sensor", "person": "Person",
}
_DEVICE_CLASS_NOUN_DE = {
    "window": "Fenster", "door": "Tür", "garage_door": "Garagentor", "opening": "Öffnung",
    "motion": "Bewegungsmelder", "occupancy": "Anwesenheitssensor",
}
_WEEKDAY_SPOKEN_DE = {
    "mon": "Montag", "tue": "Dienstag", "wed": "Mittwoch", "thu": "Donnerstag",
    "fri": "Freitag", "sat": "Samstag", "sun": "Sonntag",
}
_PRESENCE_RAW_STATE_SPOKEN_DE = {"home": "zuhause", "not_home": "nicht zuhause"}
# Mirrors service_call.py's _COLOR_SPOKEN_DE/_COLOR_TEMP_SPOKEN_DE verbatim
# (Regel 6, same vocabulary) - duplicated rather than imported, same
# nlu/-stays-hass-free layering ``service_call.py`` itself sits outside of.
_COLOR_SPOKEN_DE = {
    "red": "rot", "green": "grün", "blue": "blau", "yellow": "gelb", "orange": "orange",
    "purple": "lila", "white": "weiß", "pink": "pink", "turquoise": "türkis", "cyan": "cyan",
}
_COLOR_TEMP_SPOKEN_DE = {2700: "warmweiß", 6500: "kaltweiß"}


def _entity_lookup(entities: list[EntitySnapshot]) -> dict[str, EntitySnapshot]:
    return {e.entity_id: e for e in entities}


def _area_name_lookup(entities: list[EntitySnapshot]) -> dict[str, str]:
    return {e.area_id: e.area_name for e in entities if e.area_id and e.area_name}


def _format_number(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else str(value)


def _format_delay(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    if seconds % 3600 == 0 and seconds != 0:
        hours = seconds // 3600
        return "1 Stunde" if hours == 1 else f"{hours} Stunden"
    if seconds % 60 == 0 and seconds != 0:
        minutes = seconds // 60
        return "1 Minute" if minutes == 1 else f"{minutes} Minuten"
    return f"{seconds} Sekunden"


def _speak_target(
    target: TriggerTarget | None, entity_by_id: dict[str, EntitySnapshot], area_name_by_id: dict[str, str]
) -> str:
    if target is None:
        return "unbekanntes Gerät"
    if target.entity_id is not None:
        entity = entity_by_id.get(target.entity_id)
        name = entity.friendly_name if entity is not None else target.entity_id
    else:
        noun = _DEVICE_CLASS_NOUN_DE.get(target.device_class) if target.device_class else None
        if noun is None:
            noun = _DOMAIN_NOUN_DE.get(target.domain, "Gerät")
        if target.quantifier == "all":
            name = f"alle {noun}"
        elif target.quantifier == "both":
            name = f"beide {noun}"
        elif target.quantifier == "count" and target.quantifier_count is not None:
            name = f"die {target.quantifier_count} {noun}"
        else:
            name = noun
        if target.area_id is not None:
            area_name = area_name_by_id.get(target.area_id, target.area_id)
            name = f"{name} im Bereich {area_name}"
        elif target.floor_id is not None:
            floor_name = next(
                (
                    entity.floor_name
                    for entity in entity_by_id.values()
                    if entity.floor_id == target.floor_id and entity.floor_name
                ),
                target.floor_id,
            )
            name = f"{name} auf der Etage {floor_name}"
    if target.exclude_entity_ids:
        excluded = ", ".join(
            entity_by_id[eid].friendly_name if eid in entity_by_id else eid for eid in target.exclude_entity_ids
        )
        name = f"{name} (außer {excluded})"
    return name


def _speak_trigger(
    trigger: TriggerModel, entity_by_id: dict[str, EntitySnapshot], area_name_by_id: dict[str, str]
) -> str:
    if trigger.type is TriggerType.STATE:
        target = _speak_target(trigger.target, entity_by_id, area_name_by_id)
        state = _STATE_SPOKEN_DE.get(trigger.state, "verändert") if trigger.state is not None else "verändert"
        text = f"{target} wird {state}"
    elif trigger.type is TriggerType.NUMERIC_STATE:
        target = _speak_target(trigger.target, entity_by_id, area_name_by_id)
        comparator = "über" if trigger.comparator is NumericComparator.ABOVE else "unter"
        text = f"{target} {comparator} {_format_number(trigger.threshold)} liegt"
    elif trigger.type is TriggerType.DEVICE:
        text = f"das Geräteereignis „{trigger.device_trigger_type}“ eintritt"
    elif trigger.type is TriggerType.PRESENCE:
        # Deliberately direction-neutral - TriggerModel never records
        # arrive/leave (see module docstring), so this must not guess it.
        who = _speak_target(trigger.target, entity_by_id, area_name_by_id) if trigger.target is not None else "jemand"
        text = f"sich der Anwesenheitsstatus von {who} ändert"
    elif trigger.type is TriggerType.SUN:
        event = "Sonnenaufgang" if trigger.sun_event is SunEvent.SUNRISE else "Sonnenuntergang"
        if trigger.offset_minutes:
            direction = "nach" if trigger.offset_minutes > 0 else "vor"
            text = f"es {abs(trigger.offset_minutes)} Minuten {direction} dem {event} ist"
        else:
            text = f"es {event} ist"
    elif trigger.type is TriggerType.TIME:
        clock = f"{trigger.time_hour:02d}:{(trigger.time_minute or 0):02d}"
        if trigger.time_second is not None:
            clock = f"{clock}:{trigger.time_second:02d}"
        text = f"es {clock} Uhr ist"
    elif trigger.type is TriggerType.RELATIVE_TIME:
        text = f"{_format_delay(trigger.relative_offset_seconds)} vergangen sind"
    elif trigger.type is TriggerType.CALENDAR_TIME:
        text = "der bestätigte Kalenderzeitpunkt erreicht ist"
    elif trigger.type is TriggerType.WEEKDAY:
        text = " oder ".join(_WEEKDAY_SPOKEN_DE.get(d, d) for d in trigger.weekdays) + " ist"
    elif trigger.type is TriggerType.CALENDAR:
        calendar = entity_by_id.get(trigger.calendar_entity_id or "")
        name = calendar.friendly_name if calendar is not None else trigger.calendar_entity_id
        event = "beginnt" if trigger.calendar_event == "start" else "endet"
        text = f"ein Termin im Kalender {name} {event}"
        if trigger.offset_minutes:
            direction = "nach" if trigger.offset_minutes > 0 else "vor"
            text = f"es {abs(trigger.offset_minutes)} Minuten {direction} diesem Termin ist"
    else:
        text = "ein unbekannter Auslöser eintritt"
    if trigger.delay_seconds:
        text = f"{text}, {_format_delay(trigger.delay_seconds)} lang gewartet wird"
    return text


def _speak_condition_leaf(
    condition: ConditionModel, entity_by_id: dict[str, EntitySnapshot], area_name_by_id: dict[str, str]
) -> str:
    if condition.type is ConditionType.STATE:
        target = _speak_target(condition.target, entity_by_id, area_name_by_id)
        state = _STATE_SPOKEN_DE.get(condition.state, "verändert") if condition.state is not None else "verändert"
        return f"{target} {state} ist"
    if condition.type is ConditionType.NUMERIC:
        target = _speak_target(condition.target, entity_by_id, area_name_by_id)
        comparator = "über" if condition.comparator is NumericComparator.ABOVE else "unter"
        unit = f" {condition.unit}" if condition.unit else ""
        return f"{target} {comparator} {_format_number(condition.threshold)}{unit} liegt"
    if condition.type is ConditionType.TIME:
        comparator = "vor" if condition.time_comparator is TimeComparator.BEFORE else "nach"
        return f"es {comparator} {condition.time_hour:02d}:{(condition.time_minute or 0):02d} Uhr ist"
    if condition.type is ConditionType.DATE:
        return f"heute der {(condition.date_day or 0):02d}.{(condition.date_month or 0):02d}. ist"
    if condition.type is ConditionType.WEEKDAY:
        return " oder ".join(_WEEKDAY_SPOKEN_DE.get(d, d) for d in condition.weekdays) + " ist"
    if condition.type is ConditionType.SUN:
        event = "Sonnenaufgang" if condition.sun_event is SunEvent.SUNRISE else "Sonnenuntergang"
        comparator = "vor" if condition.sun_comparator is TimeComparator.BEFORE else "nach"
        if condition.offset_minutes:
            return f"es {abs(condition.offset_minutes)} Minuten {comparator} dem {event} ist"
        return f"es {comparator} dem {event} ist"
    if condition.type is ConditionType.PRESENCE:
        who = _speak_target(condition.target, entity_by_id, area_name_by_id) if condition.target is not None else "jemand"
        state = _PRESENCE_RAW_STATE_SPOKEN_DE.get(condition.raw_state, condition.raw_state)
        return f"{who} {state} ist"
    if condition.type is ConditionType.DEVICE:
        return f"die Gerätebedingung „{condition.device_condition_type}“ erfüllt ist"
    if condition.type is ConditionType.ENTITY:
        target = _speak_target(condition.target, entity_by_id, area_name_by_id)
        return f"{target} den Zustand „{condition.raw_state}“ hat"
    if condition.type is ConditionType.CALENDAR_EVENT:
        return f"der Kalendertitel „{condition.raw_state}“ enthält"
    return "eine unbekannte Bedingung erfüllt ist"


def _speak_condition_node(
    node: ConditionNode, entity_by_id: dict[str, EntitySnapshot], area_name_by_id: dict[str, str]
) -> str:
    if node.operator is None:
        assert node.condition is not None
        return _speak_condition_leaf(node.condition, entity_by_id, area_name_by_id)
    if node.operator is LogicalOperator.NOT:
        child = node.children[0]
        if (
            child.operator is None
            and child.condition is not None
            and child.condition.type is ConditionType.PRESENCE
            and child.condition.target is None
            and child.condition.raw_state == "home"
        ):
            # AutomationConditionParser's own lexical-negation special case
            # ("niemand [mehr] zuhause ist" - see its docstring) - rendered
            # back the same idiomatic way, not "nicht (jemand zuhause ist)".
            return "niemand zuhause ist"
        return f"nicht ({_speak_condition_node(child, entity_by_id, area_name_by_id)})"
    joiner = " und " if node.operator is LogicalOperator.AND else " oder "
    return joiner.join(f"({_speak_condition_node(c, entity_by_id, area_name_by_id)})" for c in node.children)


def _speak_action_leaf(
    action: ActionModel, entity_by_id: dict[str, EntitySnapshot], area_name_by_id: dict[str, str]
) -> str:
    target = _speak_target(action.target, entity_by_id, area_name_by_id) if action.target is not None else None
    if action.type is ActionType.TURN_ON:
        text = f"{target} einschalten"
        if action.duration_seconds:
            text = f"{text} (für {_format_delay(action.duration_seconds)})"
        return text
    if action.type is ActionType.TURN_OFF:
        return f"{target} ausschalten"
    if action.type is ActionType.SET_BRIGHTNESS:
        return f"{target} auf {_format_number(action.value)} Prozent Helligkeit stellen"
    if action.type is ActionType.SET_COLOR:
        color = _COLOR_SPOKEN_DE.get(action.color_name, action.color_name)
        return f"{target} auf die Farbe {color} stellen"
    if action.type is ActionType.SET_COLOR_TEMPERATURE:
        temp = _COLOR_TEMP_SPOKEN_DE.get(action.color_temp_kelvin, f"{action.color_temp_kelvin} Kelvin")
        return f"{target} auf {temp} stellen"
    if action.type is ActionType.SET_POSITION:
        return f"{target} auf {_format_number(action.value)} Prozent Position fahren"
    if action.type is ActionType.SET_TEMPERATURE:
        return f"{target} auf {_format_number(action.value)} Grad stellen"
    if action.type is ActionType.SET_FAN_SPEED:
        return f"{target} auf {_format_number(action.value)} Prozent Stufe stellen"
    if action.type is ActionType.NOTIFY:
        return f"eine Benachrichtigung senden: „{action.message}“"
    if action.type is ActionType.DELAY:
        return f"{_format_delay(action.delay_seconds)} warten"
    if action.type is ActionType.WAIT:
        condition_text = (
            _speak_condition_node(action.wait_condition, entity_by_id, area_name_by_id)
            if action.wait_condition is not None
            else "eine unbekannte Bedingung erfüllt ist"
        )
        text = f"warten, bis {condition_text}"
        if action.timeout_seconds:
            text = f"{text} (maximal {_format_delay(action.timeout_seconds)})"
        return text
    return "eine unbekannte Aktion ausführen"


def _speak_action_step(
    step: "ActionModel | ActionGroup", entity_by_id: dict[str, EntitySnapshot], area_name_by_id: dict[str, str]
) -> str:
    if isinstance(step, ActionGroup):
        parts = [_speak_action_step(child, entity_by_id, area_name_by_id) for child in step.steps]
        if step.mode is ExecutionMode.PARALLEL:
            return "gleichzeitig " + " und ".join(parts)
        return ", dann ".join(parts)
    return _speak_action_leaf(step, entity_by_id, area_name_by_id)


def render_automation_preview(model: AutomationModel, entities: list[EntitySnapshot]) -> str:
    """The V5.23/V5.24 spoken Dry-Run/Preview text: "Automation erkannt:
    Wenn ..., [und ...,] dann ... Soll diese Automation erstellt werden?" -
    the exact sentence ``conversation.py`` speaks before storing a
    ``pending_automation_confirmation`` and waiting for the user's reply
    (V5.23). Callers only ever pass an already-``validate_automation()``-
    clean ``model`` (the confirmation flow never offers to create an
    automation ``validate_automation()`` rejected) - this function itself
    does not re-validate, purely renders whatever it is given, same
    division of labor ``render_automation_tree()`` already has.

    ``entities`` is the same live entity list the caller already resolved
    the sentence against - used only to look up friendly/area names for
    already-resolved ``entity_id``s, never to re-resolve or guess anything
    new.
    """
    entity_by_id = _entity_lookup(entities)
    area_name_by_id = _area_name_lookup(entities)
    if model.calendar_schedule is not None:
        trigger_text = f"der Zeitpunkt „{model.calendar_schedule.spoken}“ erreicht ist"
    else:
        trigger_text = " und ".join(
            _speak_trigger(t, entity_by_id, area_name_by_id) for t in model.triggers
        )
    action_text = ", dann ".join(_speak_action_step(a, entity_by_id, area_name_by_id) for a in model.actions)
    sentence = f"Wenn {trigger_text}"
    if model.conditions:
        condition_text = " und ".join(_speak_condition_node(c, entity_by_id, area_name_by_id) for c in model.conditions)
        sentence = f"{sentence} und {condition_text}"
    sentence = f"{sentence}, dann {action_text}."
    if model.once:
        sentence = f"{sentence} Diese Automation wird nach der ersten Ausführung automatisch gelöscht."
    elif model.max_runs is not None:
        sentence = (
            f"{sentence} Diese Automation wird nach {model.max_runs} "
            "Ausführungen automatisch gelöscht."
        )
    return f"Automation erkannt: {sentence} Soll diese Automation erstellt werden?"
