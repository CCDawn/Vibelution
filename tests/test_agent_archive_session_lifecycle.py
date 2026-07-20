from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from tests.test_agent_config_workspace_service import (
    _fake_config_workspace,
    _use_tmp_project_root,
    agent_bulk_delete_service,
    agent_directory_service,
    client,
    config_service,
    session_service,
)

_MINIMAL_PNG = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 32)


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


def test_purge_rejects_direct_session_reassigned_to_another_active_agent(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archived_agent_id = direct["agentId"]
    archive_response = client.delete(f"/api/agents/{archived_agent_id}")
    assert archive_response.status_code == 200, archive_response.text
    replacement = agent_directory_service.create_agent_instance(
        display_name="接管会话 Agent",
        direct_session_id=direct["id"],
    )

    purge_response = client.delete(f"/api/agents/{archived_agent_id}/purge")

    assert purge_response.status_code == 422, purge_response.text
    assert "active Agent" in str(purge_response.json()["detail"]) or "活跃 Agent" in str(
        purge_response.json()["detail"]
    )
    assert agent_directory_service.get_agent(
        archived_agent_id,
        include_archived=True,
    )["status"] == "archived"
    assert agent_directory_service.get_agent(replacement["agentId"])["status"] == "active"
    assert session_service.get_session_detail(direct["id"]) is not None
    assert session_service.get_session_detail(child["id"]) is not None


@pytest.mark.parametrize("phase", ["queued", "paused"])
def test_archive_rejects_sessions_with_pending_turns(tmp_path, monkeypatch, phase):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    with session_service._CHAT_STATE_LOCK:
        payload = session_service.load_chat_state(session_service.PROJECT_ROOT)
        conversation = session_service._find_conversation_entry(payload, direct["id"])
        assert conversation is not None
        conversation["last_turn_status"] = phase
        conversation["last_turn_id"] = f"turn-{phase}"
        session_service.save_chat_state(session_service.PROJECT_ROOT, payload)

    response = client.delete(f"/api/agents/{direct['agentId']}")

    assert response.status_code == 409, response.text
    assert agent_directory_service.get_agent(direct["agentId"])["status"] == "active"
    detail = session_service.get_session_detail(direct["id"])
    assert detail is not None
    assert detail["readOnly"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "rename",
        "select",
        "child",
        "delete",
        "reasoning",
        "attachment",
        "submit",
        "guidance",
        "edit",
    ],
)
def test_archived_session_enforces_a_real_read_only_barrier(
    tmp_path,
    monkeypatch,
    mutation,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    if mutation == "reasoning":
        monkeypatch.setattr(
            session_service,
            "_session_fixed_model_choice",
            lambda _session_id: {
                "modelId": "model-primary",
                "label": "Primary",
                "reasoningEffortValues": ["medium"],
            },
        )

    with pytest.raises(session_service.SessionValidationError) as exc_info:
        if mutation == "rename":
            session_service.update_chat_session_title(direct["id"], "不应改名")
        elif mutation == "select":
            session_service.select_chat_session(direct["id"])
        elif mutation == "child":
            session_service.create_child_session(
                direct["id"],
                user_request="不应拆子会话",
                task_title="封存后子会话",
                auto_start=False,
            )
        elif mutation == "delete":
            session_service.delete_chat_session(direct["id"])
        elif mutation == "reasoning":
            session_service.update_session_reasoning_effort(
                direct["id"],
                reasoning_effort="medium",
            )
        elif mutation == "submit":
            session_service.submit_session_message(
                direct["id"],
                "不应提交新消息",
            )
        elif mutation == "guidance":
            session_service.submit_session_guidance(
                direct["id"],
                "不应提交运行中引导",
            )
        elif mutation == "edit":
            session_service.edit_and_resubmit_session_message(
                direct["id"],
                "message-does-not-matter",
                "不应编辑并重发",
            )
        else:
            session_service.store_session_user_image_attachment(
                direct["id"],
                _MINIMAL_PNG,
                filename="sealed.png",
                content_type="image/png",
            )

    message = str(exc_info.value).lower()
    assert "read-only" in message or "只读" in message
    detail = session_service.get_session_detail(direct["id"])
    assert detail is not None
    assert detail["readOnly"] is True


@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [
        ("post", "/select"),
        ("delete", ""),
    ],
)
def test_archived_session_mutation_routes_return_validation_error(
    tmp_path,
    monkeypatch,
    method,
    path_suffix,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text

    response = getattr(client, method)(
        f"/api/sessions/{direct['id']}{path_suffix}"
    )

    assert response.status_code == 422, response.text
    assert "read-only" in str(response.json()["detail"]).lower() or "只读" in str(
        response.json()["detail"]
    )


def test_archived_agent_cannot_be_reactivated_without_a_restore_transaction(tmp_path, monkeypatch):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text

    response = client.patch(
        f"/api/agents/{direct['agentId']}",
        json={"status": "active"},
    )

    assert response.status_code == 422, response.text
    assert "restore" in str(response.json()["detail"]).lower() or "恢复" in str(
        response.json()["detail"]
    )
    assert agent_directory_service.get_agent(
        direct["agentId"],
        include_archived=True,
    )["status"] == "archived"
    assert session_service.get_session_detail(direct["id"])["readOnly"] is True


@pytest.mark.parametrize("entrypoint", ["bulk", "patch"])
def test_archive_entrypoints_idempotently_seal_legacy_archived_agent_sessions(
    tmp_path,
    monkeypatch,
    entrypoint,
):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    agent_directory_service.archive_agent_instance(
        direct["agentId"],
        repair_mode_bindings=False,
    )
    assert session_service.get_session_detail(direct["id"])["readOnly"] is False

    if entrypoint == "bulk":
        result = agent_bulk_delete_service.bulk_archive_agents([direct["agentId"]])
        assert result["summary"]["successCount"] == 1
    else:
        response = client.patch(
            f"/api/agents/{direct['agentId']}",
            json={"status": "archived"},
        )
        assert response.status_code == 200, response.text

    for session_id in (direct["id"], child["id"]):
        detail = session_service.get_session_detail(session_id)
        assert detail is not None
        assert detail["readOnly"] is True
        assert detail["archiveState"]["status"] == "archived"


def test_cleanup_pending_can_be_retried_idempotently(tmp_path, monkeypatch):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    delete_staging_root = session_service._delete_agent_session_purge_staging_root
    attempts = 0

    def fail_first_cleanup(staging_root):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("workspace locked")
        delete_staging_root(staging_root)

    monkeypatch.setattr(
        session_service,
        "_delete_agent_session_purge_staging_root",
        fail_first_cleanup,
    )
    purge_response = client.delete(f"/api/agents/{direct['agentId']}/purge")
    assert purge_response.status_code == 200, purge_response.text
    assert purge_response.json()["purgeSummary"]["sessions"]["cleanupPending"] is True

    retry = session_service.retry_pending_agent_session_purge_cleanup()
    repeated = session_service.retry_pending_agent_session_purge_cleanup()

    assert retry["cleanedRootCount"] >= 1
    assert retry["pendingRootCount"] == 0
    assert repeated["cleanedRootCount"] == 0
    assert repeated["pendingRootCount"] == 0


def test_cleanup_retry_uses_external_marker_after_partial_directory_delete(
    tmp_path,
    monkeypatch,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    delete_staging_root = session_service._delete_agent_session_purge_staging_root
    attempts = 0

    def partially_delete_first_root(staging_root):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            session_service._agent_session_purge_manifest_path(
                staging_root
            ).unlink()
            raise PermissionError("directory delete interrupted")
        delete_staging_root(staging_root)

    monkeypatch.setattr(
        session_service,
        "_delete_agent_session_purge_staging_root",
        partially_delete_first_root,
    )
    purge_response = client.delete(f"/api/agents/{direct['agentId']}/purge")
    assert purge_response.status_code == 200, purge_response.text
    assert purge_response.json()["purgeSummary"]["sessions"]["cleanupPending"] is True

    retry = session_service.retry_pending_agent_session_purge_cleanup()

    assert retry["cleanedRootCount"] >= 1
    assert retry["pendingRootCount"] == 0
    assert "MissingManifest" not in retry["cleanupFailureTypes"]


def test_cleanup_retry_ignores_an_active_staging_transaction(
    tmp_path,
    monkeypatch,
):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    agent_directory_service.archive_agent_instance(
        direct["agentId"],
        repair_mode_bindings=False,
    )
    staged = session_service.stage_agent_session_purge(
        direct["agentId"],
        direct_session_id=direct["id"],
    )
    existing_staging_roots = [
        Path(value)
        for value in staged["stagingRoots"]
        if Path(value).exists()
    ]
    assert existing_staging_roots

    retry = session_service.retry_pending_agent_session_purge_cleanup()

    assert retry["cleanedRootCount"] == 0
    assert retry["skippedActiveRootCount"] >= 1
    assert all(path.exists() for path in existing_staging_roots)
    restored = session_service.restore_staged_agent_session_purge(
        staged["restoreToken"]
    )
    assert restored["status"] == "restored"
    assert session_service.get_session_detail(direct["id"]) is not None
    assert session_service.get_session_detail(child["id"]) is not None
    assert all(not path.exists() for path in existing_staging_roots)


@pytest.mark.parametrize("failure_kind", ["missing", "conflict"])
def test_session_purge_restore_reports_workspace_loss_or_conflict(
    tmp_path,
    monkeypatch,
    failure_kind,
):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    agent_directory_service.archive_agent_instance(
        direct["agentId"],
        repair_mode_bindings=False,
    )
    staged = session_service.stage_agent_session_purge(
        direct["agentId"],
        direct_session_id=direct["id"],
    )
    move = staged["restoreToken"]["workspaceMoves"][0]
    source = Path(move["source"])
    staged_path = Path(move["staged"])
    if failure_kind == "missing":
        shutil.rmtree(staged_path)
        expected_error = "FileNotFoundError"
    else:
        source.mkdir(parents=True)
        expected_error = "FileExistsError"

    with pytest.raises(
        session_service.SessionValidationError,
        match=expected_error,
    ):
        session_service.restore_staged_agent_session_purge(
            staged["restoreToken"]
        )

    assert session_service.get_session_detail(direct["id"]) is not None
    assert session_service.get_session_detail(child["id"]) is not None


def test_cleanup_retry_rejects_a_staging_reparse_point(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    sessions_root = session_service._agent_session_workspace_roots()[0]
    sessions_root.mkdir(parents=True, exist_ok=True)
    target = sessions_root / "normal-session-workspace"
    target.mkdir()
    (target / session_service._AGENT_SESSION_PURGE_MANIFEST).write_text(
        json.dumps({"version": 1, "state": "cleanup_pending"}),
        encoding="utf-8",
    )
    junction = sessions_root / ".agent-purge-junction-probe"
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            pytest.skip(f"Windows junction creation unavailable: {created.stderr}")
    else:
        junction.symlink_to(target, target_is_directory=True)

    try:
        committed = session_service.commit_staged_agent_session_purge(
            {
                "agentId": "agent-reparse-probe",
                "sessionIds": [],
                "workspaceMoves": [],
                "stagingRoots": [str(junction)],
            }
        )
        assert committed["cleanupPending"] is True
        assert "UnsafeStagingPath" in committed["cleanupFailureTypes"]
        assert target.exists()
        retry = session_service.retry_pending_agent_session_purge_cleanup()
        assert retry["pendingRootCount"] >= 1
        assert "UnsafeStagingPath" in retry["cleanupFailureTypes"]
        assert target.exists()
        assert (target / session_service._AGENT_SESSION_PURGE_MANIFEST).exists()
    finally:
        if junction.exists() or junction.is_symlink():
            if os.name == "nt":
                os.rmdir(junction)
            else:
                junction.unlink()


def test_agent_workspace_purge_rejects_a_junction_to_another_workspace(
    tmp_path,
    monkeypatch,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    archived_agent = agent_directory_service.get_agent(
        direct["agentId"],
        include_archived=True,
    )
    workspace = agent_directory_service._lexical_project_path(
        archived_agent["workspacePath"]
    )
    if workspace.exists():
        shutil.rmtree(workspace)
    sibling_workspace = workspace.parent / "agent-sibling-workspace"
    sibling_workspace.mkdir(parents=True)
    sentinel = sibling_workspace / "sentinel.txt"
    sentinel.write_text("must survive", encoding="utf-8")
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(workspace), str(sibling_workspace)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            pytest.skip(f"Windows junction creation unavailable: {created.stderr}")
    else:
        workspace.symlink_to(sibling_workspace, target_is_directory=True)

    try:
        purge_response = client.delete(
            f"/api/agents/{direct['agentId']}/purge"
        )
        assert purge_response.status_code == 422, purge_response.text
        assert "junction" in str(purge_response.json()["detail"]).lower() or (
            "reparse" in str(purge_response.json()["detail"]).lower()
        )
        assert sentinel.read_text(encoding="utf-8") == "must survive"
        assert agent_directory_service.get_agent(
            direct["agentId"],
            include_archived=True,
        )["status"] == "archived"
    finally:
        if workspace.exists() or workspace.is_symlink():
            if os.name == "nt":
                os.rmdir(workspace)
            else:
                workspace.unlink()


def test_agent_workspace_purge_rejects_a_junction_agents_root(
    tmp_path,
    monkeypatch,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    archived_agent = agent_directory_service.get_agent(
        direct["agentId"],
        include_archived=True,
    )
    workspace = agent_directory_service._lexical_project_path(
        archived_agent["workspacePath"]
    )
    agents_root = workspace.parent
    target_root = agents_root.parent / "agents-junction-target"
    shutil.move(str(agents_root), str(target_root))
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(agents_root), str(target_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            shutil.move(str(target_root), str(agents_root))
            pytest.skip(f"Windows junction creation unavailable: {created.stderr}")
    else:
        agents_root.symlink_to(target_root, target_is_directory=True)
    sentinel = target_root / workspace.name / "root-sentinel.txt"
    sentinel.write_text("must survive root junction", encoding="utf-8")

    try:
        purge_response = client.delete(
            f"/api/agents/{direct['agentId']}/purge"
        )
        assert purge_response.status_code == 422, purge_response.text
        assert sentinel.read_text(encoding="utf-8") == (
            "must survive root junction"
        )
        assert agent_directory_service.get_agent(
            direct["agentId"],
            include_archived=True,
        )["status"] == "archived"
    finally:
        if agents_root.exists() or agents_root.is_symlink():
            if os.name == "nt":
                os.rmdir(agents_root)
            else:
                agents_root.unlink()
        if target_root.exists():
            shutil.move(str(target_root), str(agents_root))


def test_agent_workspace_purge_reparse_probe_fails_closed(
    tmp_path,
    monkeypatch,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    archived_agent = agent_directory_service.get_agent(
        direct["agentId"],
        include_archived=True,
    )
    workspace = agent_directory_service._lexical_project_path(
        archived_agent["workspacePath"]
    )
    original_lstat = Path.lstat

    def fail_workspace_lstat(path):
        if Path(path) == workspace:
            raise PermissionError("reparse probe denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_workspace_lstat)

    with pytest.raises(
        agent_directory_service.AgentDirectoryError,
        match="reparse",
    ):
        agent_directory_service.ensure_agent_purge_workspace_deletable(
            archived_agent
        )


@pytest.mark.parametrize("entrypoint", ["single", "bulk"])
def test_post_agent_delete_cleanup_exception_is_partial_success(
    tmp_path,
    monkeypatch,
    entrypoint,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text

    def fail_cleanup_commit(*args, **kwargs):
        raise session_service.SessionValidationError("cleanup validation failed")

    monkeypatch.setattr(
        session_service,
        "commit_staged_agent_session_purge",
        fail_cleanup_commit,
    )
    if entrypoint == "single":
        response = client.delete(f"/api/agents/{direct['agentId']}/purge")
        assert response.status_code == 200, response.text
        sessions = response.json()["purgeSummary"]["sessions"]
    else:
        response = client.post(
            "/api/agents/bulk-purge",
            json={"agentIds": [direct["agentId"]]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["summary"]["successCount"] == 1
        assert payload["summary"]["failedCount"] == 0
        sessions = payload["success"][0]["purgeSummary"]["sessions"]

    assert sessions["status"] == "cleanup_pending"
    assert sessions["cleanupPending"] is True
    assert sessions["cleanupFailureTypes"] == ["SessionValidationError"]
    retry = session_service.retry_pending_agent_session_purge_cleanup()
    assert retry["cleanedRootCount"] >= 1
    assert retry["pendingRootCount"] == 0
    assert agent_directory_service.get_agent(
        direct["agentId"],
        include_archived=True,
    ) is None


def test_agent_registry_mutation_waits_for_session_lifecycle_lock(
    tmp_path,
    monkeypatch,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    lifecycle_entered = threading.Event()
    release_lifecycle = threading.Event()
    mutation_completed = threading.Event()
    errors: list[Exception] = []
    original_check = session_service._ensure_agent_direct_session_not_reassigned

    def hold_lifecycle(agent_id, direct_session_id):
        original_check(agent_id, direct_session_id)
        lifecycle_entered.set()
        assert release_lifecycle.wait(2)

    monkeypatch.setattr(
        session_service,
        "_ensure_agent_direct_session_not_reassigned",
        hold_lifecycle,
    )

    def archive_sessions():
        try:
            session_service.archive_agent_sessions(
                direct["agentId"],
                direct_session_id=direct["id"],
            )
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    def mutate_registry():
        try:
            agent_directory_service.create_agent_instance(
                display_name="并发创建 Agent",
                direct_session_id="session-concurrent-probe",
            )
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)
        finally:
            mutation_completed.set()

    archive_thread = threading.Thread(target=archive_sessions)
    mutation_thread = threading.Thread(target=mutate_registry)
    archive_thread.start()
    assert lifecycle_entered.wait(2)
    mutation_thread.start()
    assert not mutation_completed.wait(0.1)
    release_lifecycle.set()
    archive_thread.join(2)
    mutation_thread.join(2)

    assert not archive_thread.is_alive()
    assert not mutation_thread.is_alive()
    assert mutation_completed.is_set()
    assert errors == []


def test_guidance_write_and_archive_are_serialized_by_chat_state_lock(
    tmp_path,
    monkeypatch,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    guidance_entered = threading.Event()
    release_guidance = threading.Event()
    archive_completed = threading.Event()
    errors: list[Exception] = []
    original_record = session_service._record_chat_next_state_signal

    def hold_guidance(**kwargs):
        guidance_entered.set()
        assert release_guidance.wait(2)
        return original_record(**kwargs)

    monkeypatch.setattr(
        session_service,
        "_record_chat_next_state_signal",
        hold_guidance,
    )

    def submit_guidance():
        try:
            session_service.submit_session_guidance(
                direct["id"],
                "先完成这条引导",
            )
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    def archive_sessions():
        try:
            session_service.archive_agent_sessions(
                direct["agentId"],
                direct_session_id=direct["id"],
            )
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)
        finally:
            archive_completed.set()

    guidance_thread = threading.Thread(target=submit_guidance)
    archive_thread = threading.Thread(target=archive_sessions)
    guidance_thread.start()
    assert guidance_entered.wait(2)
    archive_thread.start()
    assert not archive_completed.wait(0.1)
    release_guidance.set()
    guidance_thread.join(2)
    archive_thread.join(2)

    assert not guidance_thread.is_alive()
    assert not archive_thread.is_alive()
    assert archive_completed.is_set()
    assert errors == []
    assert session_service.get_session_detail(direct["id"])["readOnly"] is True


def test_session_purge_restore_continues_to_chat_state_after_workspace_failure(
    tmp_path,
    monkeypatch,
):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    agent_directory_service.archive_agent_instance(
        direct["agentId"],
        repair_mode_bindings=False,
    )
    staged = session_service.stage_agent_session_purge(
        direct["agentId"],
        direct_session_id=direct["id"],
    )
    assert session_service.get_session_detail(direct["id"]) is None

    def fail_workspace_restore(*args, **kwargs):
        raise PermissionError("workspace restore failed")

    monkeypatch.setattr(session_service.shutil, "move", fail_workspace_restore)

    with pytest.raises(
        session_service.SessionValidationError,
        match="compensation incomplete",
    ):
        session_service.restore_staged_agent_session_purge(
            staged["restoreToken"]
        )

    assert session_service.get_session_detail(direct["id"]) is not None
    assert session_service.get_session_detail(child["id"]) is not None


def test_single_archive_compensation_continues_after_an_earlier_rollback_fails():
    from core.web.routes import agents as agent_routes

    calls: list[str] = []

    def fail_first():
        calls.append("first")
        raise OSError("first rollback failed")

    def run_second():
        calls.append("second")

    failures = agent_routes._run_agent_archive_compensations(
        {},
        (
            ("rollback_first", fail_first),
            ("rollback_second", run_second),
        ),
    )

    assert calls == ["first", "second"]
    assert failures == ["rollback_first:OSError"]
