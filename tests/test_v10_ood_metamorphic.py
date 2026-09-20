from __future__ import annotations

import json
from pathlib import Path

import pytest

from homeintent.goal_intent import interpret_goal
from homeintent.goal_model import GoalKind
from homeintent.nlu.language_frontend import analyse_language


CORPUS = Path(__file__).parent / "data" / "v10_goal_ood_de.json"


def test_v10_ood_corpus_is_handwritten_diverse_and_large():
    cases = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert len(cases) >= 150
    assert len({item["input"] for item in cases}) == len(cases)
    assert len({item["category"] for item in cases}) >= 15
    assert all(isinstance(item["input"], str) and len(item["input"].split()) >= 3 for item in cases)


@pytest.mark.parametrize(
    "text",
    (
        "Wenn ich gehe, prüf bitte, ob noch Fenster offen sind und sag mir Bescheid.",
        "Wenn ich das Haus verlasse, prüfe, ob Fenster offen sind und informiere mich.",
        "Sobald ich nicht mehr zuhause bin, kontrolliere offene Fenster und sag mir Bescheid.",
    ),
)
def test_leave_home_paraphrases_have_same_typed_trigger(text: str):
    goal = interpret_goal(
        analyse_language(text),
        current_user_id="user-1",
        current_person_entity_id="person.philipp",
    )
    assert goal is not None and goal.kind is GoalKind.MONITOR_AND_NOTIFY
    assert goal.trigger is not None
    assert (
        goal.trigger.kind,
        goal.trigger.person_entity_id,
        goal.trigger.zone_id,
        goal.conditions[0].kind,
    ) == ("person_leaves_zone", "person.philipp", "home", "open_entities")


def test_nobody_home_is_not_equivalent_to_current_user_leaving():
    current = interpret_goal(
        analyse_language("Wenn ich gehe und noch Licht an ist, sag mir Bescheid."),
        current_person_entity_id="person.philipp",
    )
    household = interpret_goal(
        analyse_language("Wenn niemand zuhause ist und noch Licht an ist, sag uns Bescheid."),
        current_person_entity_id="person.philipp",
        household_person_ids=("person.philipp", "person.julia"),
    )
    assert current is not None and household is not None
    assert current.trigger is not None and household.trigger is not None
    assert current.trigger.kind == "person_leaves_zone"
    assert household.trigger.kind == "nobody_home"


def test_goal_result_and_scheduled_action_remain_distinct():
    result = interpret_goal(
        analyse_language("Sorge dafür, dass es morgen um 7 Uhr im Wohnzimmer 21 Grad hat.")
    )
    action = interpret_goal(
        analyse_language("Stell morgen um 7 Uhr die Heizung auf 21 Grad.")
    )
    assert result is not None and result.kind is GoalKind.SCHEDULED
    assert action is None


def test_recipient_change_changes_goal_semantics():
    mine = interpret_goal(
        analyse_language("Wenn ich gehe und ein Fenster offen ist, sag mir Bescheid."),
        current_person_entity_id="person.philipp",
    )
    ours = interpret_goal(
        analyse_language("Wenn niemand zuhause ist und Licht an ist, sag uns Bescheid."),
        household_person_ids=("person.philipp", "person.julia"),
    )
    assert mine is not None and ours is not None
    assert mine.recipient_person_ids == ("person.philipp",)
    assert ours.recipient_person_ids == ("person.philipp", "person.julia")

