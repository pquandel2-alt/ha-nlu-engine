import json

from ha_nlu.automation_history import AutomationHistoryStore


def test_history_is_bounded_and_pop_restores_latest(tmp_path):
    store = AutomationHistoryStore(str(tmp_path / "history.json"), limit=2)
    for index in range(3):
        store.append(operation="edit", automation_id=str(index), created_at="now", automations=[{"id": str(index)}], metadata={str(index): {"version": 1}})
    assert [item["automation_id"] for item in store.read()] == ["1", "2"]
    assert store.pop()["automation_id"] == "2"
    assert json.loads((tmp_path / "history.json").read_text())[0]["automation_id"] == "1"
