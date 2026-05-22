from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.pet_system import pet_system as pet_system_module
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import pet_service


def setup_function() -> None:
    pet_system_module.reset_pet_system()


def teardown_function() -> None:
    pet_system_module.reset_pet_system()


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("feed", {"hunger": 62, "energy": 70, "health": 60, "love": 53}),
        ("talk", {"hunger": 42, "energy": 66, "health": 60, "love": 58}),
        ("care", {"hunger": 42, "energy": 78, "health": 72, "love": 54}),
    ],
)
def test_pet_actions_update_summary_and_record_scene_event(tmp_path, monkeypatch, action, expected):
    pet_system_module.reset_pet_system()
    monkeypatch.chdir(tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        pet_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    pet = pet_system_module.get_pet_system()
    pet.data.attributes.hunger = 42
    pet.data.attributes.energy = 70
    pet.data.attributes.health = 60
    pet.data.attributes.love = 50
    pet.save()

    response = _client().post("/api/pet/actions", json={"action": action})

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == action
    for field, value in expected.items():
        assert payload["summary"][field] == value
    assert payload["summary"]["name"] == "虾宝"
    assert (tmp_path / "workspace" / "memory" / "pet_info.json").exists()
    assert len(recorded_events) == 1
    event_args, event_kwargs = recorded_events[0]
    assert event_args == ("pet", "action", "pet.action.applied")
    assert event_kwargs["outcome"] == "success"
    assert event_kwargs["fields"]["action"] == action
    assert event_kwargs["fields"]["before"]["hunger"] == 42
    for field, value in expected.items():
        event_field = "totalInteractions" if field == "totalInteractions" else field
        assert event_kwargs["fields"]["after"][event_field] == value


def test_pet_action_rejects_unknown_action_and_records_scene_event(tmp_path, monkeypatch):
    pet_system_module.reset_pet_system()
    monkeypatch.chdir(tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        pet_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    response = _client().post("/api/pet/actions", json={"action": "dance"})

    assert response.status_code == 400
    assert "Unsupported pet action" in response.json()["detail"]
    assert len(recorded_events) == 1
    event_args, event_kwargs = recorded_events[0]
    assert event_args == ("pet", "action", "pet.action.rejected")
    assert event_kwargs["outcome"] == "rejected"
    assert event_kwargs["level"] == "warning"
    assert event_kwargs["fields"]["action"] == "dance"
