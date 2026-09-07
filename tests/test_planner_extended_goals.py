from ha_nlu.entities import EntitySnapshot
from ha_nlu.planner import Goal, GoalKind, StepKind, materialize_goal
from ha_nlu.risk import RiskLevel


def test_secure_home_only_closes_observed_open_perimeter():
    entities = [
        EntitySnapshot("lock.front", "Haustür", "lock", "unlocked"),
        EntitySnapshot(
            "cover.patio", "Terrassentür", "cover", "open",
            capabilities=frozenset({"POSITION"}),
        ),
        EntitySnapshot("lock.closed", "Nebentür", "lock", "locked"),
    ]

    plan = materialize_goal(
        Goal(GoalKind.SECURE_HOME), entities, options={}, is_admin=True, user_id="owner"
    )
    actions = [step for step in plan.steps if step.kind is StepKind.ACTION]

    assert [(step.action.domain, step.action.service) for step in actions] == [
        ("lock", "lock"), ("cover", "close_cover")
    ]
    assert plan.aggregate_risk >= RiskLevel.MEDIUM
    assert all(step.compensation is None for step in actions)


def test_quiet_media_pauses_only_currently_playing_entities():
    entities = [
        EntitySnapshot("media_player.living", "Wohnzimmer", "media_player", "playing"),
        EntitySnapshot("media_player.bed", "Schlafzimmer", "media_player", "idle"),
    ]

    plan = materialize_goal(
        Goal(GoalKind.QUIET_MEDIA), entities, options={}, is_admin=True, user_id="owner"
    )
    action = next(step.action for step in plan.steps if step.action is not None)

    assert action.domain == "media_player"
    assert action.service == "media_pause"
    assert action.entity_id == "media_player.living"
