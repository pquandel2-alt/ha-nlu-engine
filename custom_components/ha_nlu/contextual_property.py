"""Target inference for short, property-centric conversation follow-ups.

This is deliberately deterministic: the previous turn may contribute a
property and a spatial scope, but never an arbitrary device guess. A single
eligible actuator is selected, multiple actuators produce clarification and
read-only properties never become actions.
"""

from __future__ import annotations

import re

from .entities import EntitySnapshot, build_entity_index
from .nlu.context import ConversationContext
from .nlu.frame import AreaReference, SemanticFrame, TargetReference
from .nlu.normalize import normalize
from .nlu.parse_outcome import ParseFailureReason, UnderstandingFeedback
from .nlu.parser import ClarificationRequest, ParseContext, ParseResult
from .nlu.primitives import SemanticProperty


class ContextualPropertyResolver:
    """Resolve omitted actuator targets using the previous semantic focus."""

    def __init__(self, climate_parser, percentage_parser, fan_parser) -> None:
        self._climate_parser = climate_parser
        self._percentage_parser = percentage_parser
        self._fan_parser = fan_parser

    def resolve(
        self,
        text: str,
        entities: list[EntitySnapshot],
        context: ConversationContext | None,
    ) -> ParseResult | ClarificationRequest | UnderstandingFeedback | None:
        if context is None:
            return None
        normalized = normalize(text)

        temperature = self._temperature(normalized, text, entities, context)
        if temperature is not None:
            return temperature

        percentage = self._percentage(normalized, text, entities, context)
        if percentage is not None:
            return percentage

        return self._fan_level(normalized, text, entities, context)

    @staticmethod
    def _property(context: ConversationContext) -> SemanticProperty | None:
        if context.focus is not None and context.focus.property is not None:
            return context.focus.property
        previous = context.last_command
        raw = previous.parameters.get("property") if previous is not None else None
        if raw == "temperatur":
            return SemanticProperty.TEMPERATURE
        if raw == "helligkeit":
            return SemanticProperty.BRIGHTNESS
        if raw == "position":
            return SemanticProperty.POSITION
        if raw in ("geschwindigkeit", "stufe"):
            return SemanticProperty.FAN_SPEED
        if raw == "batterie":
            return SemanticProperty.BATTERY
        if raw == "luftfeuchtigkeit":
            return SemanticProperty.HUMIDITY
        if raw == "leistung":
            return SemanticProperty.POWER
        if raw == "energie":
            return SemanticProperty.ENERGY
        return None

    @staticmethod
    def candidates(
        domain: str,
        entities: list[EntitySnapshot],
        context: ConversationContext,
        *,
        capability: str | None = None,
    ) -> list[EntitySnapshot] | None:
        def eligible(entity: EntitySnapshot) -> bool:
            return entity.domain == domain and (
                capability is None or capability in entity.capabilities
            )

        focus = context.focus
        if focus is not None:
            if focus.scope_kind == "entity" and focus.scope_id:
                direct = [
                    entity for entity in entities
                    if entity.entity_id == focus.scope_id and eligible(entity)
                ]
                if direct:
                    return direct
            if focus.scope_kind == "area" and focus.scope_id:
                return [
                    entity for entity in entities
                    if entity.area_id == focus.scope_id and eligible(entity)
                ]
            if focus.scope_kind == "floor" and focus.scope_id:
                return [
                    entity for entity in entities
                    if entity.floor_id == focus.scope_id and eligible(entity)
                ]

        direct_ids = {
            entity.entity_id for entity in context.last_entities if eligible(entity)
        }
        if direct_ids:
            return [entity for entity in entities if entity.entity_id in direct_ids]

        previous = context.last_command
        parameters = previous.parameters if previous is not None else {}
        location_kind = parameters.get("location_kind")
        location_id = parameters.get("location_id")
        if location_kind == "area" and location_id:
            return [e for e in entities if eligible(e) and e.area_id == location_id]
        if location_kind == "floor" and location_id:
            return [e for e in entities if eligible(e) and e.floor_id == location_id]

        area_ids = {e.area_id for e in context.last_entities if e.area_id is not None}
        floor_ids = {e.floor_id for e in context.last_entities if e.floor_id is not None}
        if len(area_ids) == 1:
            area_id = next(iter(area_ids))
            return [e for e in entities if eligible(e) and e.area_id == area_id]
        if len(floor_ids) == 1:
            floor_id = next(iter(floor_ids))
            return [e for e in entities if eligible(e) and e.floor_id == floor_id]
        return None

    def _temperature(self, normalized, source, entities, context):
        prop = self._property(context)
        has_measurement = any(
            entity.domain == "sensor" and entity.device_class == "temperature"
            for entity in context.last_entities
        )
        if prop is not SemanticProperty.TEMPERATURE and not has_measurement:
            return None

        absolute = re.match(
            r"^(?:kannst du\s+)?(?:bitte\s+)?(?:"
            r"(?:(?:die\s+)?temperatur\s+)?auf\s+(?P<a>.+?)\s+grad(?:\s+"
            r"(?:erhöhen|anheben|stellen|setzen|ändern|regeln))?"
            r"|(?:erhöhe|erhöh|stelle|stell|setze|setz|ändere|änder|regel)\s+"
            r"(?:die\s+)?temperatur\s+auf\s+(?P<b>.+?)\s+grad"
            r"|(?:stelle|stell|setze|setz|mach)\s+(?:sie|es|die\s+temperatur)\s+"
            r"auf\s+(?P<c>.+?)\s+grad)\s*[?.!]*$",
            normalized,
            re.IGNORECASE,
        )
        relative = re.match(
            r"^(?:mach(?:e)?(?:\s+es|\s+die\s+temperatur)?|temperatur)?\s*"
            r"(?P<amount>.+?)\s+grad\s+(?P<direction>wärmer|kälter)\s*[?.!]*$",
            normalized,
            re.IGNORECASE,
        )
        if absolute is None and relative is None:
            return None

        candidates = self.candidates("climate", entities, context, capability="TEMPERATURE")
        if candidates is None:
            return UnderstandingFeedback(
                ParseFailureReason.UNSAFE_INFERENCE,
                "Ich kann aus der vorherigen Abfrage keinen eindeutigen Bereich ableiten.",
            )
        if not candidates:
            return UnderstandingFeedback(
                ParseFailureReason.UNSUPPORTED_CAPABILITY,
                "Dort ist keine steuerbare Heizung oder kein Thermostat für Assist freigegeben.",
            )

        if absolute is not None:
            raw_value = next(value for value in absolute.groups() if value is not None)
        else:
            raw_amount = relative.group("amount")
            probe = candidates[0]
            parsed_amount = self._climate_parser.parse(
                f"stelle {probe.friendly_name} auf {raw_amount} Grad",
                ParseContext(entities=[probe], index=build_entity_index([probe])),
            )
            # The climate grammar accepts only 5..30, while a relative delta
            # commonly is 1..4. Parse number words by using 10 + amount.
            if parsed_amount is None:
                parsed_amount = self._climate_parser.parse(
                    f"stelle {probe.friendly_name} auf zehn Grad",
                    ParseContext(entities=[probe], index=build_entity_index([probe])),
                )
                try:
                    amount = float(raw_amount.replace(",", "."))
                except ValueError:
                    word_amounts = {"ein": 1, "eine": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5}
                    amount = word_amounts.get(raw_amount.casefold(), 0)
            else:
                amount = float(parsed_amount.frame.parameters["temperature"])
            current = candidates[0].attributes.get("temperature")
            if current is None or amount <= 0:
                return UnderstandingFeedback(
                    ParseFailureReason.INVALID_VALUE,
                    "Ich konnte die gewünschte Temperaturänderung nicht bestimmen.",
                )
            raw_value = str(current + amount if relative.group("direction") == "wärmer" else current - amount)

        probe = candidates[0]
        parsed = self._climate_parser.parse(
            f"stelle {probe.friendly_name} auf {raw_value} Grad",
            ParseContext(entities=[probe], index=build_entity_index([probe])),
        )
        if parsed is None:
            return UnderstandingFeedback(
                ParseFailureReason.INVALID_VALUE,
                "Die gewünschte Temperatur muss zwischen 5 und 30 Grad liegen.",
            )
        temperature = parsed.frame.parameters["temperature"]
        return self._setpoint_result(
            source, "HassClimateSetTemperature", "Temperatur", "climate",
            {"temperature": temperature}, candidates,
        )

    def _percentage(self, normalized, source, entities, context):
        match = re.match(
            r"^(?:kannst du\s+)?(?:bitte\s+)?(?:"
            r"(?:die\s+)?(?P<property>helligkeit|position|rollläden?|rollos?|jalousien?)\s+"
            r"auf\s+(?P<a>.+?)\s*(?:prozent)?(?:\s+"
            r"(?:erhöhen|anheben|stellen|setzen|ändern|dimmen|fahren))?"
            r"|(?:stelle|stell|setze|setz|mach|fahre|fahr)\s+"
            r"(?:sie|es|die\s+helligkeit|die\s+position)\s+auf\s+"
            r"(?P<b>.+?)\s+prozent"
            r"|auf\s+(?P<c>.+?)\s+prozent)\s*[?.!]*$",
            normalized,
            re.IGNORECASE,
        )
        if match is None:
            return None
        property_word = (match.group("property") or "").casefold()
        prop = self._property(context)
        contextual_domains = {entity.domain for entity in context.last_entities}
        if property_word == "helligkeit" or (not property_word and prop is SemanticProperty.BRIGHTNESS):
            domain = "light"
        elif property_word or (not property_word and prop is SemanticProperty.POSITION):
            domain = "cover"
        elif contextual_domains == {"light"}:
            domain = "light"
        elif contextual_domains == {"cover"}:
            domain = "cover"
        else:
            return None
        raw = match.group("a") or match.group("b") or match.group("c")
        candidates = self.candidates(
            domain, entities, context,
            capability="BRIGHTNESS" if domain == "light" else "POSITION",
        )
        label = "Licht" if domain == "light" else "Rollladen"
        if not candidates:
            return UnderstandingFeedback(
                ParseFailureReason.UNSUPPORTED_CAPABILITY,
                f"Dort ist kein steuerbares {label} für Assist freigegeben.",
            )
        probe = candidates[0]
        parsed = self._percentage_parser.parse(
            f"stelle {probe.friendly_name} auf {raw} Prozent",
            ParseContext(entities=[probe], index=build_entity_index([probe])),
        )
        if parsed is None:
            return UnderstandingFeedback(
                ParseFailureReason.INVALID_VALUE,
                "Der Prozentwert muss zwischen 0 und 100 liegen.",
            )
        return self._setpoint_result(
            source, "HassSetPercentage", label, domain,
            {"percent": parsed.frame.parameters["percent"]}, candidates,
        )

    def _fan_level(self, normalized, source, entities, context):
        match = re.match(
            r"^(?:kannst du\s+)?(?:bitte\s+)?(?:"
            r"(?:die\s+)?(?:geschwindigkeit|stufe)\s+auf\s+(?:stufe\s+)?(?P<a>.+?)"
            r"(?:\s+(?:erhöhen|stellen|setzen|ändern))?"
            r"|(?:stelle|stell|setze|setz|mach)\s+(?:sie|ihn|es|die\s+stufe)\s+"
            r"auf\s+stufe\s+(?P<b>.+?)"
            r"|auf\s+stufe\s+(?P<c>.+?))\s*[?.!]*$",
            normalized,
            re.IGNORECASE,
        )
        if match is None:
            return None
        raw = match.group("a") or match.group("b") or match.group("c")
        candidates = self.candidates("fan", entities, context, capability="FAN_SPEED")
        if not candidates:
            return UnderstandingFeedback(
                ParseFailureReason.UNSUPPORTED_CAPABILITY,
                "Dort ist kein Ventilator für Assist freigegeben.",
            )
        probe = candidates[0]
        parsed = self._fan_parser.parse(
            f"stelle {probe.friendly_name} auf Stufe {raw}",
            ParseContext(entities=[probe], index=build_entity_index([probe])),
        )
        if parsed is None:
            return UnderstandingFeedback(
                ParseFailureReason.INVALID_VALUE,
                "Die Ventilatorstufe muss zwischen 1 und 10 liegen.",
            )
        return self._setpoint_result(
            source, "HassFanSetSpeed", "Ventilator", "fan",
            {"level": parsed.frame.parameters["level"]}, candidates,
        )

    @staticmethod
    def _setpoint_result(source, intent, label, domain, parameters, candidates):
        if len(candidates) > 1:
            return ClarificationRequest(
                pending_intent=intent,
                pending_target=label,
                candidates=tuple(candidates),
                pending_parameters=parameters,
            )
        entity = candidates[0]
        return ParseResult(
            frame=SemanticFrame(
                intent=intent,
                target=TargetReference(text=label, entity_id=entity.entity_id, domain=domain),
                area=(
                    AreaReference(text=entity.area_name, area_id=entity.area_id)
                    if entity.area_id is not None and entity.area_name is not None
                    else None
                ),
                parameters=parameters,
                source_text=source,
            ),
            resolved_entities=[entity],
        )
