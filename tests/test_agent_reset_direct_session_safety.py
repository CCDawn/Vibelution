from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_bulk_delete_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    session_service,
    team_service,
)


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def test_agent_reset_direct_session_bind_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    direct_session = session_service.create_chat_session(title="Reset Bind Failure Agent")
    agent = agent_directory_service.get_agent(direct_session["agentId"])
    original_update_agent_instance = agent_directory_service.update_agent_instance

    def fail_replacement_bind(agent_id, *args, **kwargs):
        if str(agent_id or "").strip() == agent["agentId"] and str(kwargs.get("direct_session_id") or "").strip() not in {
            "",
            direct_session["id"],
        }:
            raise agent_directory_service.AgentDirectoryError("replacement bind blocked")
        return original_update_agent_instance(agent_id, *args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "update_agent_instance", fail_replacement_bind)

    response = client.post(f"/api/agents/{agent['agentId']}/reset", json={"clearRuntimeState": False})

    assert response.status_code == 422, response.text
    assert "replacement bind blocked" in response.json()["detail"]
    restored_agent = agent_directory_service.get_agent(agent["agentId"])
    assert restored_agent["directSessionId"] == direct_session["id"]
    assert session_service.get_session_detail(direct_session["id"]) is not None
    session_ids = {item["id"] for item in session_service.list_sessions()}
    assert direct_session["id"] in session_ids


def test_agent_reset_direct_session_success_rebinds_before_removing_old_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    direct_session = session_service.create_chat_session(title="Reset Rebind Order Agent")
    agent = agent_directory_service.get_agent(direct_session["agentId"])
    observed_old_session_present_during_bind = []
    original_update_agent_instance = agent_directory_service.update_agent_instance

    def track_replacement_bind(agent_id, *args, **kwargs):
        if str(agent_id or "").strip() == agent["agentId"] and str(kwargs.get("direct_session_id") or "").strip() not in {
            "",
            direct_session["id"],
        }:
            observed_old_session_present_during_bind.append(session_service.get_session_detail(direct_session["id"]) is not None)
        return original_update_agent_instance(agent_id, *args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "update_agent_instance", track_replacement_bind)

    response = client.post(f"/api/agents/{agent['agentId']}/reset", json={"clearRuntimeState": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert observed_old_session_present_during_bind == [True]
    assert payload["resetSummary"]["resetDirectSession"] is True
    assert payload["resetSummary"]["previousDirectSessionId"] == direct_session["id"]
    assert payload["resetSummary"]["replacementDirectSessionId"] == payload["agent"]["directSessionId"]
    assert payload["resetSummary"]["skippedPaths"] == []
    assert session_service.get_session_detail(direct_session["id"]) is None
    assert session_service.get_session_detail(payload["agent"]["directSessionId"]) is not None
