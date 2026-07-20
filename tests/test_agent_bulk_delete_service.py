import pytest

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


def test_bulk_purge_blocks_agent_delete_when_session_purge_staging_fails(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_session = session_service.create_chat_session(title="Tombstone Failure Agent")
    agent_record = agent_directory_service.get_agent(agent_session["agentId"])
    agent_directory_service.archive_agent_instance(agent_session["agentId"], repair_mode_bindings=False)

    def fail_session_purge_stage(*args, **kwargs):
        raise OSError("session workspace unavailable")

    monkeypatch.setattr(session_service, "stage_agent_session_purge", fail_session_purge_stage)

    result = agent_bulk_delete_service.bulk_purge_agents([agent_session["agentId"]])

    assert result["status"] == "failed"
    assert result["summary"]["failedCount"] == 1
    assert result["failed"][0]["reason"] == "session_purge_stage_failed"
    assert agent_directory_service.get_agent(agent_session["agentId"], include_archived=True)["status"] == "archived"
    assert (tmp_path / agent_record["workspacePath"]).exists()
    detail = session_service.get_session_detail(agent_session["id"])
    assert detail["agentId"] == agent_session["agentId"]
    assert detail["agentStatusCode"] == "archived_agent"


def test_bulk_purge_rolls_back_staged_sessions_when_agent_delete_fails(tmp_path, monkeypatch):
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
    assert result["timingsMs"]["rollback_agent_session_purge"] >= 0
    assert result["cleanupSummary"]["sessions"] == []
    assert agent_directory_service.get_agent(agent_session["agentId"], include_archived=True)["status"] == "archived"
    assert workspace_path.exists()
    detail = session_service.get_session_detail(agent_session["id"])
    assert detail["agentId"] == agent_session["agentId"]
    assert detail["agentStatusCode"] == "archived_agent"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [
        agent_session["agentId"],
        peer_session["agentId"],
    ]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [
        agent_session["agentId"]
    ]
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


def test_bulk_archive_restores_teams_when_room_cleanup_fails(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Bulk Archive Cleanup Rollback")
    team = team_service.create_team(
        name="Bulk Archive Cleanup Rollback Team",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )

    def fail_room_cleanup(*args, **kwargs):
        raise chat_room_service.ChatRoomBusyError("room cleanup failed")

    monkeypatch.setattr(
        agent_bulk_delete_service,
        "remove_agents_from_chat_rooms",
        fail_room_cleanup,
    )

    with pytest.raises(chat_room_service.ChatRoomBusyError, match="room cleanup failed"):
        agent_bulk_delete_service.bulk_archive_agents([agent["agentId"]])

    assert agent_directory_service.get_agent(agent["agentId"])["status"] == "active"
    restored_members = team_service.get_team(team["teamId"])["members"]
    assert [member["agentId"] for member in restored_members] == [agent["agentId"]]
    assert [member["role"] for member in restored_members] == ["lead"]
    detail = session_service.get_session_detail(agent["id"])
    assert detail["readOnly"] is False
    assert detail["archiveState"] == {}


def test_bulk_archive_restores_references_for_failed_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Bulk Archive Rollback Agent")
    peer = session_service.create_chat_session(title="Bulk Archive Rollback Peer")
    room = chat_room_service.create_chat_room(
        title="Bulk Archive Rollback Room",
        participant_session_ids=[agent["id"], peer["id"]],
    )
    team = team_service.create_team(
        name="Bulk Archive Rollback Team",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )
    agent_mode_binding_service.update_mode_binding(
        "chat",
        available_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    original_available = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["chat"]["availableAgentIds"]

    def fail_archive(*args, **kwargs):
        raise agent_directory_service.AgentDirectoryError("archive write failed")

    monkeypatch.setattr(agent_bulk_delete_service, "archive_agent_instance", fail_archive)

    result = agent_bulk_delete_service.bulk_archive_agents([agent["agentId"]])

    assert result["status"] == "failed"
    assert result["summary"]["failedCount"] == 1
    assert agent_directory_service.get_agent(agent["agentId"])["status"] == "active"
    restored_session = session_service.get_session_detail(agent["id"])
    assert restored_session["readOnly"] is False
    assert restored_session["archiveState"] == {}
    assert team_service.get_team(team["teamId"])["members"][0]["agentId"] == agent["agentId"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [
        agent["agentId"],
        peer["agentId"],
    ]
    assert agent_mode_binding_service.get_mode_bindings_payload()["modes"]["chat"]["availableAgentIds"] == original_available
    assert result["timingsMs"]["rollback_teams"] >= 0


def test_bulk_archive_reactivates_earlier_success_when_later_agent_fails(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    first = session_service.create_chat_session(title="Bulk Archive First")
    second = session_service.create_chat_session(title="Bulk Archive Second")
    team = team_service.create_team(
        name="Bulk Archive Atomic Team",
        members=[
            {"agentId": first["agentId"], "role": "lead"},
            {"agentId": second["agentId"], "role": "reviewer"},
        ],
    )
    original_archive = agent_bulk_delete_service.archive_agent_instance

    def fail_second(agent_id, *args, **kwargs):
        if agent_id == second["agentId"]:
            raise agent_directory_service.AgentDirectoryError("second archive write failed")
        return original_archive(agent_id, *args, **kwargs)

    monkeypatch.setattr(agent_bulk_delete_service, "archive_agent_instance", fail_second)

    result = agent_bulk_delete_service.bulk_archive_agents([first["agentId"], second["agentId"]])

    assert result["status"] == "failed"
    assert result["summary"]["successCount"] == 0
    assert result["summary"]["failedCount"] == 2
    assert {item["reason"] for item in result["failed"]} == {"invalid", "batch_rolled_back"}
    assert agent_directory_service.get_agent(first["agentId"])["status"] == "active"
    assert agent_directory_service.get_agent(second["agentId"])["status"] == "active"
    assert [member["agentId"] for member in team_service.get_team(team["teamId"])["members"]] == [
        first["agentId"],
        second["agentId"],
    ]
    assert result["timingsMs"]["rollback_archived_agents"] >= 0


def test_bulk_archive_compensation_continues_after_an_earlier_rollback_fails():
    calls: list[str] = []

    def fail_first():
        calls.append("first")
        raise OSError("first rollback failed")

    def run_second():
        calls.append("second")

    failures = agent_bulk_delete_service._run_best_effort_compensations(
        {},
        [
            ("rollback_first", fail_first),
            ("rollback_second", run_second),
        ],
    )

    assert calls == ["first", "second"]
    assert failures == ["rollback_first:OSError"]


def test_bulk_archive_rollback_does_not_reactivate_legacy_archived_agent(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    legacy = session_service.create_chat_session(title="Legacy Archived")
    failing = session_service.create_chat_session(title="Failing Active")
    agent_directory_service.archive_agent_instance(
        legacy["agentId"],
        repair_mode_bindings=False,
    )
    original_archive = agent_bulk_delete_service.archive_agent_instance

    def fail_active(agent_id, *args, **kwargs):
        if agent_id == failing["agentId"]:
            raise agent_directory_service.AgentDirectoryError("archive write failed")
        return original_archive(agent_id, *args, **kwargs)

    monkeypatch.setattr(
        agent_bulk_delete_service,
        "archive_agent_instance",
        fail_active,
    )

    result = agent_bulk_delete_service.bulk_archive_agents(
        [legacy["agentId"], failing["agentId"]]
    )

    assert result["status"] == "failed"
    assert agent_directory_service.get_agent(
        legacy["agentId"],
        include_archived=True,
    )["status"] == "archived"
    assert agent_directory_service.get_agent(failing["agentId"])["status"] == "active"


def test_bulk_purge_reconciles_references_when_one_agent_delete_fails(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    first = session_service.create_chat_session(title="Purge Success")
    second = session_service.create_chat_session(title="Purge Failure")
    peer = session_service.create_chat_session(title="Purge Peer")
    room = chat_room_service.create_chat_room(
        title="Partial Purge Room",
        participant_agent_ids=[
            first["agentId"],
            second["agentId"],
            peer["agentId"],
        ],
    )
    team = team_service.create_team(
        name="Partial Purge Team",
        members=[
            {"agentId": first["agentId"], "role": "lead"},
            {"agentId": second["agentId"], "role": "reviewer"},
        ],
    )
    for item in (first, second):
        agent_directory_service.archive_agent_instance(
            item["agentId"],
            repair_mode_bindings=False,
        )
    original_purge = agent_bulk_delete_service.purge_archived_agent_instance

    def fail_second(agent_id, *args, **kwargs):
        if agent_id == second["agentId"]:
            raise agent_directory_service.AgentDirectoryError("purge failed")
        return original_purge(agent_id, *args, **kwargs)

    monkeypatch.setattr(
        agent_bulk_delete_service,
        "purge_archived_agent_instance",
        fail_second,
    )

    result = agent_bulk_delete_service.bulk_purge_agents(
        [first["agentId"], second["agentId"]]
    )

    assert result["status"] == "partial_failed"
    assert result["summary"] == {
        "requestedCount": 2,
        "successCount": 1,
        "skippedCount": 0,
        "failedCount": 1,
    }
    assert agent_directory_service.get_agent(
        first["agentId"],
        include_archived=True,
    ) is None
    assert agent_directory_service.get_agent(
        second["agentId"],
        include_archived=True,
    )["status"] == "archived"
    assert session_service.get_session_detail(first["id"]) is None
    assert session_service.get_session_detail(second["id"]) is not None
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [
        second["agentId"],
        peer["agentId"],
    ]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [
        second["agentId"]
    ]


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
