from ha_nlu.agent_action_policy import validate_agent_service_plan
from ha_nlu.service_call import ServiceCallPlan


def test_core_action_accepts_only_its_declared_target_domain():
    assert validate_agent_service_plan(
        ServiceCallPlan("lock", "unlock", "lock.front")
    ) is None
    assert validate_agent_service_plan(
        ServiceCallPlan("lock", "unlock", "switch.decoy")
    ) is not None


def test_target_fields_can_never_be_supplied_as_action_data():
    for key in ("entity_id", "device_id", "area_id", "floor_id", "label_id", "target"):
        error = validate_agent_service_plan(
            ServiceCallPlan(
                "homeassistant", "turn_off", "switch.allowed", {key: "switch.hidden"}
            )
        )
        assert error is not None
        assert "Ziel" in error


def test_core_action_rejects_unknown_data_but_alarm_code_is_explicitly_supported():
    assert validate_agent_service_plan(
        ServiceCallPlan("lock", "unlock", "lock.front", {"code": "1234"})
    ) is not None
    assert validate_agent_service_plan(
        ServiceCallPlan(
            "alarm_control_panel",
            "alarm_disarm",
            "alarm_control_panel.home",
            {"code": "1234"},
        )
    ) is None


def test_unregistered_persisted_service_is_rejected():
    error = validate_agent_service_plan(
        ServiceCallPlan("shell_command", "arbitrary", "switch.allowed")
    )
    assert error == "Die vorgeschlagene Aktion ist nicht freigegeben."
