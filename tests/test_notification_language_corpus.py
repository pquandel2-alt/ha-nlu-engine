"""HomeIntent 7.1.2 notification/reminder evaluation corpus.

``tests/eval/notification_cases.json`` holds handwritten German utterances
with handwritten expected meanings (never produced by the parser).  Each case
is routed through the same engine entry points the live conversation uses:
immediate notification, the automation clause analysis, the reminder
adapter and the relative-time one-shot projection.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest

from homeintent.engine import NluEngine
from homeintent.entities import EntitySnapshot
from homeintent.nlu.action_model import ActionModel, ActionType, NotificationRecipientKind
from homeintent.nlu.automation_model import TriggerType
from homeintent.notification_language import TEST_NOTIFICATION_MESSAGE
from homeintent.notification_target import NotificationTargetResolver
from homeintent.reminder import reminder_automation_text
from homeintent.user_context import NotificationTarget, NotificationTargetKind, UserContextStore

CORPUS = json.loads(
    (Path(__file__).parent / "eval" / "notification_cases.json").read_text(encoding="utf-8")
)["cases"]
LANGUAGE_CASES = [case for case in CORPUS if "text" in case]
RESOLVER_CASES = [case for case in CORPUS if "resolver" in case]

REQUIRED_CATEGORIES = {
    "immediate_push", "delayed_push", "state_triggered_push", "area_scoped_push",
    "explicit_message", "implicit_message", "modal_language", "polite_language",
    "action_first", "trigger_first", "no_comma", "STT_like", "query_vs_notify",
    "reminder_vs_notify", "ambiguous_recipient", "missing_target", "multi_user",
    "negative_examples",
}

ENTITIES = [
    EntitySnapshot(
        "binary_sensor.wohnzimmer_fenster_links", "Wohnzimmer Fenster links",
        "binary_sensor", "off", area_id="wohnzimmer", area_name="Wohnzimmer",
        device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.wohnzimmer_fenster_rechts", "Wohnzimmer Fenster rechts",
        "binary_sensor", "off", area_id="wohnzimmer", area_name="Wohnzimmer",
        device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.badezimmerfenster", "Badezimmerfenster", "binary_sensor", "off",
        area_id="bad", area_name="Badezimmer", device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.haustuer", "Haustür", "binary_sensor", "off",
        area_id="flur", area_name="Flur", device_class="door",
    ),
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "off", area_id="kueche", area_name="Küche",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot("notify.mobile_app_iphone_von_philipp", "iPhone von Philipp", "notify", "unknown"),
]
RECIPIENTS = {
    "current_user": NotificationRecipientKind.CURRENT_USER,
    "household": NotificationRecipientKind.HOUSEHOLD,
    "named": NotificationRecipientKind.EXPLICIT_TARGET,
}

_ENGINE = NluEngine()


def _notifications(result) -> list[ActionModel]:
    if result is None:
        return []
    return [
        step for step in result.model.actions
        if isinstance(step, ActionModel) and step.type is ActionType.NOTIFY
    ]


def _delayed(text: str):
    rewritten = reminder_automation_text(text)
    if rewritten is not None:
        result = _ENGINE.match_relative_time_automation(rewritten, ENTITIES)
        if result is not None:
            return result
    return _ENGINE.match_relative_time_automation(text, ENTITIES)


def test_corpus_size_and_categories():
    assert len(CORPUS) >= 150
    counts = Counter(case["category"] for case in CORPUS)
    assert REQUIRED_CATEGORIES <= set(counts)
    assert all(counts[category] >= 3 for category in REQUIRED_CATEGORIES)


@pytest.mark.parametrize("case", LANGUAGE_CASES, ids=lambda case: case["text"][:60])
def test_notification_language_case(case):
    text = case["text"]
    kind = case["kind"]
    immediate = _ENGINE.match_immediate_notification(text)

    if kind in {"none", "none_or_delayed"}:
        assert immediate is None
        automation = _ENGINE.match_automation(text, ENTITIES)
        assert not any(item.recipient is not None for item in _notifications(automation))
        if kind == "none":
            assert not _notifications(_delayed(text))
        return

    expected_recipient = RECIPIENTS[case["recipient"]]
    if kind == "immediate":
        assert immediate is not None
        assert immediate.recipient_kind is expected_recipient
        if "test" in case:
            assert immediate.test is case["test"]
        if case.get("test"):
            assert immediate.resolved_message() == TEST_NOTIFICATION_MESSAGE
        if "message" in case:
            assert immediate.resolved_message() == case["message"]
        return

    assert immediate is None, "timed or triggered requests are never sent immediately"
    if kind == "delayed":
        result = _delayed(text)
        assert result is not None and result.validation_error is None
        [trigger] = result.model.triggers
        assert trigger.type is TriggerType.RELATIVE_TIME
        assert trigger.relative_offset_seconds == case["offset"]
        assert result.model.once is True
    else:
        result = _ENGINE.match_automation(text, ENTITIES)
        assert result is not None and result.validation_error is None
        [trigger] = result.model.triggers
        expected = case["trigger"]
        assert trigger.type is TriggerType.STATE
        assert trigger.state.name == expected["state"]
        if "device_class" in expected:
            assert trigger.target.device_class == expected["device_class"]
        if "domain" in expected:
            assert trigger.target.domain == expected["domain"]
        assert trigger.target.area_id == expected["area_id"]
    [notification] = _notifications(result)
    assert notification.recipient is not None
    assert notification.recipient.kind is expected_recipient
    assert not notification.recipient.materialized  # materialized only for a live user
    if "message" in case:
        assert notification.message == case["message"]


@pytest.mark.parametrize("case", RESOLVER_CASES, ids=lambda case: case["category"])
def test_notification_recipient_case(case, tmp_path):
    scenario = case["resolver"]
    store = UserContextStore(tmp_path / "users.json")
    for user, targets in scenario["bindings"].items():
        asyncio.run(store.async_set_user(
            user, person_entity_id=None, confirmed=True,
            notification_targets=[
                NotificationTarget(target, NotificationTargetKind.ENTITY) for target in targets
            ],
        ))
    resolver = NotificationTargetResolver(
        user_contexts=store,
        configured_targets=scenario["configured"],
        push_enabled=scenario.get("push_enabled", True),
    )
    resolution = resolver.resolve(RECIPIENTS[scenario["kind"]], scenario["user"])
    assert resolution.status.value == case["expected_status"]
    assert [item.target_id for item in resolution.targets] == case.get("expected_targets", [])
