from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import homeintent.conversation as ha_conversation  # noqa: E402
from homeintent.conversation import NluConversationEntity  # noqa: E402
from homeintent.automation_executor import AutomationExecutor  # noqa: E402
from homeintent.entities import EntitySnapshot  # noqa: E402
from homeintent.experience_store import ExperienceStore  # noqa: E402
from homeintent.goal_model import GoalKind, GoalModel  # noqa: E402
from homeintent.goal_run import (  # noqa: E402
    GoalRun,
    GoalRunStore,
    GoalRunStatus,
    StepExecutionRecord,
    VerificationRecord,
)
from homeintent.learning_manager import LearningManager  # noqa: E402
from homeintent.learning_policy import LearningMode, LearningPolicy  # noqa: E402
from homeintent.model_registry import LearnedKind, ModelRegistry  # noqa: E402
from homeintent.predictive_house_model import PredictiveHouseModel  # noqa: E402
from homeintent.thermal_model import (  # noqa: E402
    ThermalBinding,
    ThermalObservation,
    train_thermal_model,
)
from homeintent.profiles import ProfileStore  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


NOW = datetime(2026, 1, 5, 6, 30, tzinfo=timezone.utc)
ENTITIES = [
    EntitySnapshot(
        "light.kitchen", "Küchenlicht", "light", "off",
        area_id="kitchen", capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "cover.kitchen", "Küchenrollladen", "cover", "closed",
        area_id="kitchen", capabilities=frozenset({"OPEN", "CLOSE"}),
    ),
    EntitySnapshot(
        "switch.coffee", "Kaffeemaschine", "switch", "off",
        area_id="kitchen", capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]


def _agent(tmp_path, monkeypatch):
    policy = LearningPolicy(
        learning_mode=LearningMode.ASK,
        predictive_models_enabled=True,
        habit_discovery_enabled=True,
    )
    registry = ModelRegistry(tmp_path / "models.json", policy)
    experiences = ExperienceStore(tmp_path / "experiences.json", policy)
    house = PredictiveHouseModel(policy)
    learning = LearningManager(experiences, registry, house, policy)
    agent = NluConversationEntity(ConfigEntry())
    agent.hass = HomeAssistant()
    agent._runtime_data.learning_policy = policy
    agent._runtime_data.learned_models = registry
    agent._runtime_data.experiences = experiences
    agent._runtime_data.predictive_house = house
    agent._runtime_data.learning_manager = learning
    agent._runtime_data.profiles = ProfileStore(tmp_path / "profiles.json")
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda *_: ENTITIES
    )
    monkeypatch.setattr(
        ha_conversation, "build_device_snapshots", lambda *_: []
    )
    return agent, learning, registry


def _turn(agent, text: str, conversation_id: str = "v11"):
    return asyncio.run(agent._async_handle_message(
        ConversationInput(
            text=text, conversation_id=conversation_id,
            context=SimpleNamespace(user_id="philipp"),
        ),
        None,
    ))


def test_inferred_preference_requires_dialog_confirmation(tmp_path, monkeypatch):
    agent, learning, registry = _agent(tmp_path, monkeypatch)
    for index in range(10):
        asyncio.run(learning.async_observe_preference_selection(
            user_id="philipp", concept="Lampe", area_id="living_room",
            entity_id="light.floor" if index < 8 else "light.ceiling",
            observed_at=NOW + timedelta(minutes=index),
        ))

    suggestion = _turn(agent, "Was weißt du über meine Lichtpräferenzen?")
    assert "Soll das" in suggestion.response.speech
    before = asyncio.run(registry.async_list(kind=LearnedKind.PREFERENCE))[0]
    assert before.knowledge_state.value == "inferred"
    agent.hass.services.async_call.assert_not_awaited()

    saved = _turn(agent, "Ja")
    after = asyncio.run(registry.async_list(kind=LearnedKind.PREFERENCE))[0]
    assert saved.response.speech.startswith("Gespeichert")
    assert after.knowledge_state.value == "confirmed"
    assert after.confirmed_by == "philipp"
    agent.hass.services.async_call.assert_not_awaited()


def test_habit_acceptance_enters_v10_routine_confirmation_only(tmp_path, monkeypatch):
    agent, learning, registry = _agent(tmp_path, monkeypatch)
    goal = GoalModel(GoalKind.ACHIEVE_STATE, goal_id="morning")
    for index in range(15):
        stamp = NOW + timedelta(days=index)
        steps = tuple(
            StepExecutionRecord(
                f"s{step_index}", operator, (target,), (), True,
                (VerificationRecord(
                    target, expected, expected, True,
                    observed_at=stamp.isoformat(),
                ),),
            )
            for step_index, (operator, target, expected) in enumerate((
                ("LIGHT_TURN_ON", "light.kitchen", "on"),
                ("COVER_OPEN_COVER", "cover.kitchen", "open"),
                ("SWITCH_TURN_ON", "switch.coffee", "on"),
            ))
        )
        run = GoalRun(
            f"habit-{index}", "morning", stamp.isoformat(), stamp.isoformat(),
            "", "philipp", None, goal, "plan", (), (), True, steps, (),
            GoalRunStatus.SUCCESS,
        )
        asyncio.run(learning.async_observe_goal_run(run))

    suggestion = _turn(agent, "Welche Gewohnheiten hast du erkannt?", "habit")
    assert "Soll ich daraus eine Routine" in suggestion.response.speech
    preview = _turn(agent, "Ja", "habit")
    assert "Routinenvorschau" in preview.response.speech
    assert agent._runtime_data.profiles.routine(
        "Morgenroutine", user_id="philipp"
    ) is None
    saved = _turn(agent, "Ja", "habit")
    assert saved.response.speech.startswith("Gespeichert")
    assert agent._runtime_data.profiles.routine(
        "Morgenroutine", user_id="philipp"
    ) is not None
    habit = asyncio.run(registry.async_list(kind=LearnedKind.HABIT))[0]
    assert habit.parameters["creates_automation"] is False
    agent.hass.services.async_call.assert_not_awaited()


def test_thermal_deadline_creates_start_intermediate_and_final_one_shots(
    tmp_path, monkeypatch,
):
    policy = LearningPolicy(
        learning_mode=LearningMode.ASK,
        predictive_models_enabled=True,
        habit_discovery_enabled=False,
    )
    house = PredictiveHouseModel(policy)
    durations = (
        2820, 2880, 2760, 2940, 2850, 2910, 2790, 2870, 2830, 2920,
        2860, 2810, 2890, 2780, 2950, 2840, 2900, 2800, 2930, 2860,
    )
    observations = tuple(
        ThermalObservation(
            NOW - timedelta(days=index + 1),
            NOW - timedelta(days=index + 1) + timedelta(seconds=duration),
            "wohnzimmer", "sensor.living_temperature", "climate.living",
            19.0, 21.0, duration, True,
        )
        for index, duration in enumerate(durations)
    )
    model = train_thermal_model(
        ThermalBinding(
            "wohnzimmer", "sensor.living_temperature", "climate.living",
            confirmed=True,
        ),
        observations,
        policy,
        now=NOW,
    )
    assert model is not None
    house.install_thermal(model)
    climate = EntitySnapshot(
        "climate.living", "Wohnzimmerheizung", "climate", "heat",
        area_id="wohnzimmer", area_name="Wohnzimmer",
        attributes={"temperature": 19.0},
    )
    sensor = EntitySnapshot(
        "sensor.living_temperature", "Wohnzimmertemperatur", "sensor", "19",
        area_id="wohnzimmer", area_name="Wohnzimmer", unit="°C",
        device_class="temperature",
    )
    agent = NluConversationEntity(ConfigEntry())
    agent.hass = HomeAssistant()
    agent.hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    agent._runtime_data.predictive_house = house
    agent._runtime_data.learning_policy = policy
    agent._runtime_data.goal_runs = GoalRunStore(tmp_path / "runs.json")
    monkeypatch.setattr(
        AutomationExecutor, "_assign_homeintent_category", lambda *_args: None
    )
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda *_: [climate, sensor]
    )
    monkeypatch.setattr(ha_conversation, "build_device_snapshots", lambda *_: [])
    monkeypatch.setattr(ha_conversation.dt_util, "now", lambda: NOW)

    preview = _turn(
        agent,
        "Sorge dafür, dass es morgen um 7 Uhr im Wohnzimmer 21 Grad hat.",
        "thermal-deadline",
    )
    assert "Planvorschau" in preview.response.speech
    active = agent._runtime_data.dialog_manager.active("thermal-deadline")
    assert active is not None
    plan = active.slots["plan"]
    assert plan.adaptive_advice is not None
    assert plan.adaptive_advice.final_verification_at == NOW.replace(
        day=NOW.day + 1, hour=7, minute=0, second=0, microsecond=0
    )

    confirmed = _turn(agent, "Ja", "thermal-deadline")
    assert "persistent" in confirmed.response.speech.casefold()
    persisted = (tmp_path / "automations.yaml").read_text(encoding="utf-8")
    assert persisted.count("homeintent.thermal_deadline_checkpoint") == 3
    assert "phase: start" in persisted
    assert "phase: intermediate" in persisted
    assert "phase: final" in persisted
    runs = asyncio.run(agent._runtime_data.goal_runs.async_list())
    assert len(runs) == 1 and runs[0].status is GoalRunStatus.SCHEDULED
    assert agent.hass.services.async_call.await_count == 3
    assert all(
        call.args[:2] == ("automation", "reload")
        for call in agent.hass.services.async_call.await_args_list
    )
