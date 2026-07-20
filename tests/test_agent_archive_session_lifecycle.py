from __future__ import annotations

from tests.test_agent_config_workspace_service import (
    _fake_config_workspace,
    _use_tmp_project_root,
    agent_bulk_delete_service,
    agent_directory_service,
    client,
    config_service,
    session_service,
)


def _create_agent_with_child_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    direct = session_service.create_chat_session(title="归档级联 Agent")
    child_result = session_service.create_child_session(
        direct["id"],
        user_request="验证归档级联",
        task_title="归档级联子会话",
        auto_start=False,
        switch_to_child=False,
        source="agent_archive_session_lifecycle_test",
    )
    return direct, child_result["childSession"]


def test_agent_archive_seals_direct_and_child_sessions(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)

    response = client.delete(f"/api/agents/{direct['agentId']}")

    assert response.status_code == 200, response.text
    payload = response.json()
    session_summary = payload["archiveSummary"]["sessions"]
    assert session_summary["archivedCount"] == 2
    assert set(session_summary["sessionIds"]) == {direct["id"], child["id"]}

    indexed_ids = {
        item["conversationId"]
        for item in client.get("/api/conversations").json()
    }
    assert direct["id"] not in indexed_ids
    assert child["id"] not in indexed_ids

    for session_id in (direct["id"], child["id"]):
        detail_response = client.get(f"/api/sessions/{session_id}")
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["archiveState"]["status"] == "archived"
        assert detail["archiveState"]["source"] == "agent_archive"
        assert detail["archiveState"]["agentId"] == direct["agentId"]
        assert detail["readOnly"] is True

    write_response = client.post(
        f"/api/sessions/{direct['id']}/messages",
        json={"content": "归档后不应继续写入"},
    )
    assert write_response.status_code == 422, write_response.text
    assert "归档" in str(write_response.json()["detail"]) or "archived" in str(
        write_response.json()["detail"]
    ).lower()


def test_bulk_archive_uses_the_same_session_seal_contract(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)

    result = agent_bulk_delete_service.bulk_archive_agents([direct["agentId"]])

    assert result["status"] == "completed"
    assert result["summary"]["successCount"] == 1
    session_summary = result["success"][0]["archiveSummary"]["sessions"]
    assert session_summary["archivedCount"] == 2
    assert set(session_summary["sessionIds"]) == {direct["id"], child["id"]}
    for session_id in (direct["id"], child["id"]):
        detail = session_service.get_session_detail(session_id)
        assert detail is not None
        assert detail["readOnly"] is True
        assert detail["archiveState"]["status"] == "archived"


def test_agent_purge_removes_all_archived_sessions_and_private_workspaces(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    child_workspace = tmp_path / child["workspacePath"]
    child_workspace.mkdir(parents=True, exist_ok=True)
    (child_workspace / "purge-marker.txt").write_text("remove me", encoding="utf-8")
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text

    purge_response = client.delete(f"/api/agents/{direct['agentId']}/purge")

    assert purge_response.status_code == 200, purge_response.text
    payload = purge_response.json()
    session_summary = payload["purgeSummary"]["sessions"]
    assert session_summary["deletedCount"] == 2
    assert set(session_summary["sessionIds"]) == {direct["id"], child["id"]}
    assert session_summary["historyRetention"] == "deleted"
    assert session_summary["workspaceStagedCount"] == 2
    assert session_summary["workspaceDeletedCount"] == 2
    assert not child_workspace.exists(), {"stage": "before_404_checks", **payload}
    assert agent_directory_service.get_agent(direct["agentId"], include_archived=True) is None
    assert client.get(f"/api/sessions/{direct['id']}").status_code == 404
    assert client.get(f"/api/sessions/{child['id']}").status_code == 404
    assert not child_workspace.exists(), {"stage": "after_404_checks", **payload}


def test_bulk_purge_uses_the_same_session_delete_contract(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    agent_directory_service.archive_agent_instance(
        direct["agentId"],
        repair_mode_bindings=False,
    )

    result = agent_bulk_delete_service.bulk_purge_agents([direct["agentId"]])

    assert result["status"] == "completed"
    assert result["summary"]["successCount"] == 1
    session_summary = result["success"][0]["purgeSummary"]["sessions"]
    assert session_summary["deletedCount"] == 2
    assert set(session_summary["sessionIds"]) == {direct["id"], child["id"]}
    assert session_summary["historyRetention"] == "deleted"
    assert result["cleanupSummary"]["sessions"] == [session_summary]
    assert session_service.get_session_detail(direct["id"]) is None
    assert session_service.get_session_detail(child["id"]) is None


def test_session_purge_stage_rolls_back_if_runtime_cleanup_fails(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    child_workspace = tmp_path / child["workspacePath"]
    child_workspace.mkdir(parents=True, exist_ok=True)
    agent_directory_service.archive_agent_instance(
        direct["agentId"],
        repair_mode_bindings=False,
    )

    def fail_runtime_cleanup(*args, **kwargs):
        raise OSError("runtime cleanup failed")

    monkeypatch.setattr(session_service, "_clear_session_live_output", fail_runtime_cleanup)

    response = client.delete(f"/api/agents/{direct['agentId']}/purge")

    assert response.status_code == 422, response.text
    assert agent_directory_service.get_agent(
        direct["agentId"],
        include_archived=True,
    )["status"] == "archived"
    assert session_service.get_session_detail(direct["id"]) is not None
    assert session_service.get_session_detail(child["id"]) is not None
    assert child_workspace.exists()


def test_lifecycle_telemetry_failure_does_not_change_archive_or_purge_result(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)

    def fail_telemetry(*args, **kwargs):
        raise OSError("telemetry unavailable")

    monkeypatch.setattr(session_service, "record_runtime_scene_event", fail_telemetry)

    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    purge_response = client.delete(f"/api/agents/{direct['agentId']}/purge")
    assert purge_response.status_code == 200, purge_response.text
    assert session_service.get_session_detail(direct["id"]) is None
    assert session_service.get_session_detail(child["id"]) is None


def test_final_workspace_cleanup_failure_is_reported_without_restoring_deleted_agent(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text

    def fail_staging_cleanup(*args, **kwargs):
        raise PermissionError("workspace locked")

    monkeypatch.setattr(
        session_service,
        "_delete_agent_session_purge_staging_root",
        fail_staging_cleanup,
    )

    purge_response = client.delete(f"/api/agents/{direct['agentId']}/purge")

    assert purge_response.status_code == 200, purge_response.text
    sessions = purge_response.json()["purgeSummary"]["sessions"]
    assert sessions["status"] == "cleanup_pending"
    assert sessions["cleanupPending"] is True
    assert sessions["workspacePendingCount"] == sessions["workspaceStagedCount"]
    assert sessions["workspaceDeletedCount"] == 0
    assert sessions["cleanupFailureTypes"] == ["PermissionError"]
    assert agent_directory_service.get_agent(
        direct["agentId"],
        include_archived=True,
    ) is None
    assert session_service.get_session_detail(direct["id"]) is None
    assert session_service.get_session_detail(child["id"]) is None
