"""Test helper exercising the productive V7 device-understanding boundary."""

from __future__ import annotations

from ha_nlu.device_result import DeviceControlResult
from ha_nlu.engine import NluEngine
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.language_frontend import LanguageDocument
from ha_nlu.risk import requires_confirmation


def understand_device(
    text: str,
    entities: list[EntitySnapshot],
    document: LanguageDocument | None = None,
) -> DeviceControlResult | None:
    outcome = NluEngine().understand(text, entities, document=document)
    payload = outcome.payload
    if payload is None or not hasattr(payload, "plan"):
        return None
    plan = payload.plan
    resolved = tuple(payload.command.entities) if payload.command is not None else ()
    return DeviceControlResult(
        plan,
        payload.response_text,
        requires_confirmation=(
            plan is not None and requires_confirmation(plan, list(resolved))
        ),
        entity=resolved[0] if len(resolved) == 1 else None,
        entities=resolved,
    )
