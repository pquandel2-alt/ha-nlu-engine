from ha_nlu.automation_management import (
    AutomationManagementKind,
    parse_automation_management,
)
from ha_nlu.automation_simulation import render_automation_simulation, simulate_automation
from ha_nlu.automation_summary import AutomationSummary
from ha_nlu.entities import EntitySnapshot


def test_simulation_is_classified_as_read_only_management():
    request = parse_automation_management(
        "Was würde die Automation für Küchenlicht jetzt tun?"
    )

    assert request is not None
    assert request.kind is AutomationManagementKind.SIMULATE
    assert request.entity_name == "Küchenlicht"


def test_simulation_evaluates_state_condition_and_describes_action():
    light = EntitySnapshot("light.kueche", "Küchenlicht", "light", "off")
    window = EntitySnapshot("binary_sensor.fenster", "Küchenfenster", "binary_sensor", "on")
    automation = AutomationSummary(
        "one", "Fensterlicht", created_by="homeintent",
        conditions=({"condition": "state", "entity_id": window.entity_id, "state": "on"},),
        actions=({"action": "light.turn_on", "target": {"entity_id": light.entity_id}},),
    )

    result = simulate_automation(automation, [light, window])
    spoken = render_automation_simulation(automation, [light, window])

    assert result.ready is True
    assert "turn on für Küchenlicht" in spoken
    assert "nur eine Simulation" in spoken


def test_unsupported_condition_never_claims_readiness():
    automation = AutomationSummary(
        "one", "Komplex", created_by="homeintent",
        conditions=({"condition": "template", "value_template": "{{ true }}"},),
    )

    result = simulate_automation(automation, [])

    assert result.ready is None
