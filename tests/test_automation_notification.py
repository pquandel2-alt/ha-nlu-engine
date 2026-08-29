"""Direct unit tests for ``automation_notification.py`` - the central
notification-vocabulary catalog and recipient resolver
``NluEngine.match_automation()`` delegates to (see
``tests/test_engine_match_automation.py`` for the same features exercised
through the full engine, and ``tests/test_integration_wave_e2e.py`` for the
real conversation pipeline). This file isolates the pure functions
themselves - especially the "never guess" recipient-resolution paths
(zero/one/many matches) that are easy to get wrong and hard to see clearly
once wrapped in the rest of ``match_automation()``.
"""

from __future__ import annotations

from ha_nlu.automation_notification import (
    notification_action_from_request,
    resolve_notify_target,
)
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionType

NOTIFY_PHILIPP = EntitySnapshot(
    "notify.mobile_app_philipp", "Philipp Handy", "notify", "unknown"
)
NOTIFY_ANNA = EntitySnapshot(
    "notify.mobile_app_anna", "Anna Handy", "notify", "unknown"
)
NOTIFY_PHILIPP_DUPLICATE = EntitySnapshot(
    "notify.mobile_app_philipp_2", "Philipp iPad", "notify", "unknown"
)
ENTITIES = [NOTIFY_PHILIPP, NOTIFY_ANNA]


# --- resolve_notify_target ---------------------------------------------------


def test_resolve_notify_target_returns_none_for_proactive_pronouns():
    for pronoun in ("mich", "mir", "uns", "Mich", "MIR"):
        assert resolve_notify_target(pronoun, ENTITIES) is None


def test_resolve_notify_target_resolves_a_unique_match():
    target = resolve_notify_target("Philipp", ENTITIES)
    assert target is not None
    assert target.domain == "notify"
    assert target.entity_id == "notify.mobile_app_philipp"


def test_resolve_notify_target_returns_none_for_zero_matches():
    assert resolve_notify_target("Klaus", ENTITIES) is None


def test_resolve_notify_target_returns_none_for_ambiguous_matches():
    ambiguous_entities = [NOTIFY_PHILIPP, NOTIFY_PHILIPP_DUPLICATE, NOTIFY_ANNA]
    assert resolve_notify_target("Philipp", ambiguous_entities) is None


def test_resolve_notify_target_matches_via_configured_alias():
    aliased = EntitySnapshot(
        "notify.mobile_app_privat", "Handy Privat", "notify", "unknown",
        aliases=("Philipp",),
    )
    target = resolve_notify_target("Philipp", [aliased])
    assert target is not None
    assert target.entity_id == "notify.mobile_app_privat"


# --- notification_action_from_request: pattern coverage ---------------------


def test_recipient_first_infinitive_form_resolves_target():
    action = notification_action_from_request(
        "Kannst du Philipp benachrichtigen", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is not None
    assert action.type is ActionType.NOTIFY
    assert action.target.entity_id == "notify.mobile_app_philipp"


def test_recipient_first_infinitive_form_with_mich_uses_proactive_channel():
    action = notification_action_from_request(
        "Kannst du mich benachrichtigen", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is not None
    assert action.target is None


def test_action_first_imperative_form_resolves_target():
    action = notification_action_from_request(
        "Benachrichtige Philipp", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is not None
    assert action.target.entity_id == "notify.mobile_app_philipp"


def test_action_first_with_message_noun_suffix_resolves_target():
    action = notification_action_from_request(
        "schicke Philipp eine Mitteilung", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is not None
    assert action.target.entity_id == "notify.mobile_app_philipp"


def test_action_trailing_leading_verb_resolves_target():
    action = notification_action_from_request(
        "schicke eine Push-Nachricht an Philipp", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is not None
    assert action.target.entity_id == "notify.mobile_app_philipp"


def test_action_trailing_trailing_verb_resolves_target():
    action = notification_action_from_request(
        "eine Push-Nachricht an Philipp schickt", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is not None
    assert action.target.entity_id == "notify.mobile_app_philipp"


def test_action_trailing_no_verb_resolves_target():
    action = notification_action_from_request(
        "eine Push-Nachricht an Philipp", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is not None
    assert action.target.entity_id == "notify.mobile_app_philipp"


def test_notification_keyword_variants_all_resolve(
):
    for phrase in (
        "schicke eine Push-Nachricht an Philipp",
        "schicke eine Push Nachricht an Philipp",
        "schicke eine Benachrichtigung an Philipp",
        "sende eine Nachricht an Philipp",
        "sende eine Mitteilung an Philipp",
        "sende eine Meldung an Philipp",
    ):
        action = notification_action_from_request(phrase, "wenn die Tür aufgeht", ENTITIES)
        assert action is not None, f"Failed: {phrase}"
        assert action.target.entity_id == "notify.mobile_app_philipp"


# --- Safety: never guess ------------------------------------------------


def test_unknown_recipient_returns_none_instead_of_falling_back():
    action = notification_action_from_request(
        "schicke eine Nachricht an Klaus", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is None


def test_ambiguous_recipient_returns_none_instead_of_guessing():
    ambiguous_entities = [NOTIFY_PHILIPP, NOTIFY_PHILIPP_DUPLICATE, NOTIFY_ANNA]
    action = notification_action_from_request(
        "Benachrichtige Philipp", "wenn die Tür aufgeht", ambiguous_entities
    )
    assert action is None


def test_explicit_dass_message_never_matches_the_recipient_patterns():
    """"benachrichtige mich dass ..." is the pre-existing, separate
    dictated-message form (see ``notify_action.yaml``/
    ``test_automation_action_parser.py::test_notify_benachrichtige_mich``) -
    none of this module's own patterns should claim it, since they would
    have no way to tell dictated content apart from a recipient name."""
    action = notification_action_from_request(
        "benachrichtige mich dass der Akku leer ist", "wenn X passiert", ENTITIES
    )
    assert action is None


def test_unrelated_action_text_returns_none():
    action = notification_action_from_request(
        "schalte das Küchenlicht ein", "wenn die Tür aufgeht", ENTITIES
    )
    assert action is None


# --- Message derivation from trigger -----------------------------------


def test_message_is_derived_from_trigger_when_not_explicit():
    action = notification_action_from_request(
        "benachrichtige mich", "wenn das Fenster im Wohnzimmer geöffnet wird", ENTITIES
    )
    assert action is not None
    assert action.message == "Das Fenster im Wohnzimmer geöffnet wird."


def test_message_falls_back_to_generic_text_for_empty_trigger():
    action = notification_action_from_request("benachrichtige mich", "", ENTITIES)
    assert action is not None
    assert action.message == "Auslöser eingetreten."
