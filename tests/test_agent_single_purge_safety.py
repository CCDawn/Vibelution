from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agents_route
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


def test_agent_purge_blocks_delete_when_direct_session_tombstone_fails(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Tombstone Failure Agent")
    peer = session_service.create_chat_session(title="Peer Agent")
    agent_record = agent_directory_service.get_agent(agent["agentId"])
    workspace_path = tmp_path / agent_record["workspacePath"]
    room = chat_room_service.create_chat_room(
        title="Tombstone Failure Room",
        participant_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    team = team_service.create_team(
        name="Tombstone Failure Team",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=agent["agentId"],
        available_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    agent_directory_service.archive_agent_instance(agent["agentId"], repair_mode_bindings=False)
    bindings_before = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["chat"]

    def fail_tombstone(*args, **kwargs):
        return {
            "changed": False,
            "sessionId": agent["id"],
            "agentId": agent["agentId"],
            "reason": "tombstone_failed",
            "errorType": "OSError",
        }

    monkeypatch.setattr(session_service, "mark_direct_session_agent_deleted", fail_tombstone)

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 422, response.text
    assert "before permanent delete" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    assert workspace_path.exists()
    detail = session_service.get_session_detail(agent["id"])
    assert detail["agentId"] == agent["agentId"]
    assert detail["agentStatusCode"] == "archived_agent"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [agent["agentId"], peer["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [agent["agentId"]]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == bindings_before["defaultAgentId"]
    assert bindings["chat"]["availableAgentIds"] == bindings_before["availableAgentIds"]


def test_agent_purge_rolls_back_direct_session_tombstone_when_delete_fails(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Rollback Agent")
    peer = session_service.create_chat_session(title="Peer Agent")
    agent_record = agent_directory_service.get_agent(agent["agentId"])
    workspace_path = tmp_path / agent_record["workspacePath"]
    workspace_path.mkdir(parents=True, exist_ok=True)
    room = chat_room_service.create_chat_room(
        title="Rollback Room",
        participant_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    team = team_service.create_team(
        name="Rollback Team",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=agent["agentId"],
        available_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    agent_directory_service.archive_agent_instance(agent["agentId"], repair_mode_bindings=False)
    events = []
    monkeypatch.setattr(
        agents_route,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    def fail_rmtree(path):
        raise PermissionError("locked")

    monkeypatch.setattr(agent_directory_service.shutil, "rmtree", fail_rmtree)

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 422, response.text
    assert "PermissionError" in response.json()["detail"]
    failed = [event for event in events if event[0][:3] == ("agent_directory", "delete", "agent.purge.failed")]
    assert failed
    assert failed[-1][1]["fields"]["timingsMs"]["rollback_direct_session_deleted_agent"] >= 0
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    assert workspace_path.exists()
    detail = session_service.get_session_detail(agent["id"])
    assert detail["agentId"] == agent["agentId"]
    assert detail["agentStatusCode"] == "archived_agent"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [peer["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert team_detail["members"] == []
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == peer["agentId"]
    assert agent["agentId"] not in bindings["chat"]["availableAgentIds"]


def test_agent_purge_does_not_expose_direct_session_restore_token(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Successful Purge Agent")
    agent_directory_service.archive_agent_instance(agent["agentId"])

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 200, response.text
    direct_session = response.json()["purgeSummary"]["directSession"]
    assert direct_session["reason"] == "agent_purged"
    assert "restoreToken" not in direct_session
