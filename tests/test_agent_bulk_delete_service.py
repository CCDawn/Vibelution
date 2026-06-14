from core.web.services import (
    agent_bulk_delete_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    session_service,
    team_service,
)


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def test_bulk_purge_blocks_agent_delete_when_direct_session_tombstone_fails(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_session = session_service.create_chat_session(title="Tombstone Failure Agent")
    agent_record = agent_directory_service.get_agent(agent_session["agentId"])
    agent_directory_service.archive_agent_instance(agent_session["agentId"], repair_mode_bindings=False)

    def fail_tombstone(*args, **kwargs):
        return {
            "changed": False,
            "sessionId": agent_session["id"],
            "agentId": agent_session["agentId"],
            "reason": "tombstone_failed",
            "errorType": "OSError",
        }

    monkeypatch.setattr(session_service, "mark_direct_session_agent_deleted", fail_tombstone)

    result = agent_bulk_delete_service.bulk_purge_agents([agent_session["agentId"]])

    assert result["status"] == "failed"
    assert result["summary"]["failedCount"] == 1
    assert result["failed"][0]["reason"] == "tombstone_failed"
    assert agent_directory_service.get_agent(agent_session["agentId"], include_archived=True)["status"] == "archived"
    assert (tmp_path / agent_record["workspacePath"]).exists()
    detail = session_service.get_session_detail(agent_session["id"])
    assert detail["agentId"] == agent_session["agentId"]
    assert detail["agentStatusCode"] == "archived_agent"


def test_bulk_purge_rolls_back_direct_session_tombstone_when_agent_delete_fails(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_session = session_service.create_chat_session(title="Workspace Locked Agent")
    peer_session = session_service.create_chat_session(title="Peer Agent")
    agent_record = agent_directory_service.get_agent(agent_session["agentId"])
    workspace_path = tmp_path / agent_record["workspacePath"]
    workspace_path.mkdir(parents=True, exist_ok=True)
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=agent_session["agentId"],
        available_agent_ids=[agent_session["agentId"], peer_session["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="Rollback Room",
        participant_agent_ids=[agent_session["agentId"], peer_session["agentId"]],
    )
    team = team_service.create_team(
        name="Rollback Team",
        members=[{"agentId": agent_session["agentId"], "role": "lead"}],
    )
    agent_directory_service.archive_agent_instance(agent_session["agentId"], repair_mode_bindings=False)

    def fail_rmtree(path):
        raise PermissionError("locked")

    monkeypatch.setattr(agent_directory_service.shutil, "rmtree", fail_rmtree)

    result = agent_bulk_delete_service.bulk_purge_agents([agent_session["agentId"]])

    assert result["status"] == "failed"
    assert result["summary"]["failedCount"] == 1
    assert "PermissionError" in result["failed"][0]["message"]
    assert result["timingsMs"]["rollback_direct_session_deleted_agent"] >= 0
    assert "restoreToken" not in result["cleanupSummary"]["directSessions"][0]
    assert agent_directory_service.get_agent(agent_session["agentId"], include_archived=True)["status"] == "archived"
    assert workspace_path.exists()
    detail = session_service.get_session_detail(agent_session["id"])
    assert detail["agentId"] == agent_session["agentId"]
    assert detail["agentStatusCode"] == "archived_agent"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [peer_session["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert team_detail["members"] == []
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == peer_session["agentId"]
    assert agent_session["agentId"] not in bindings["chat"]["availableAgentIds"]


def test_bulk_archive_skips_system_fixed_role_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    protected = agent_directory_service.create_agent_instance(
        display_name="System Fixed Role",
        metadata={"fixedRole": True, "supervisedRole": "baseline"},
        primary_mode="supervised_evolution",
        role_key="baseline",
    )

    result = agent_bulk_delete_service.bulk_archive_agents([protected["agentId"]])

    assert result["status"] == "completed"
    assert result["summary"]["successCount"] == 0
    assert result["summary"]["skippedCount"] == 1
    assert result["skipped"] == [
        {
            "agentId": protected["agentId"],
            "reason": "protected",
            "message": "Protected core Agent cannot be archived.",
        }
    ]
    assert agent_directory_service.get_agent(protected["agentId"])["status"] == "active"


def test_bulk_purge_skips_system_fixed_role_agent_even_when_legacy_archived(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    protected = agent_directory_service.create_agent_instance(display_name="Legacy Archived Fixed Role")
    agent_directory_service.archive_agent_instance(protected["agentId"])
    agent_directory_service.update_agent_instance(
        protected["agentId"],
        metadata={"fixedRole": True, "supervisedRole": "reviewer"},
    )

    result = agent_bulk_delete_service.bulk_purge_agents([protected["agentId"]])

    assert result["status"] == "completed"
    assert result["summary"]["successCount"] == 0
    assert result["summary"]["skippedCount"] == 1
    assert result["skipped"] == [
        {
            "agentId": protected["agentId"],
            "reason": "protected",
            "message": "Protected core Agent cannot be purged.",
        }
    ]
    assert agent_directory_service.get_agent(protected["agentId"], include_archived=True)["status"] == "archived"
