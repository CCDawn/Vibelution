from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from tests.test_agent_config_workspace_service import (
    _fake_config_workspace,
    _use_tmp_project_root,
    agent_bulk_delete_service,
    agent_directory_service,
    chat_room_service,
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


def test_archive_preflight_releases_directory_lock_before_api_projection(tmp_path, monkeypatch):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    projection_started = threading.Event()
    release_projection = threading.Event()
    state_read_completed = threading.Event()
    original_agent_to_api = agent_directory_service._agent_to_api
    result: dict[str, object] = {}

    def blocking_agent_to_api(agent, *args, **kwargs):
        projection_started.set()
        assert release_projection.wait(timeout=2)
        return original_agent_to_api(agent, *args, **kwargs)

    def run_preflight():
        result["agent"] = agent_directory_service.ensure_agent_archive_allowed(direct["agentId"])

    def read_directory_state():
        agent_directory_service.load_state()
        state_read_completed.set()

    monkeypatch.setattr(agent_directory_service, "_agent_to_api", blocking_agent_to_api)
    preflight_thread = threading.Thread(target=run_preflight, daemon=True)
    reader_thread = threading.Thread(target=read_directory_state, daemon=True)
    preflight_thread.start()
    assert projection_started.wait(timeout=1)
    try:
        reader_thread.start()
        assert state_read_completed.wait(timeout=0.5), (
            "Agent API projection must not hold the global directory lock."
        )
    finally:
        release_projection.set()
        preflight_thread.join(timeout=2)
        reader_thread.join(timeout=2)

    assert result["agent"]["agentId"] == direct["agentId"]


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
        for item in client.get("/api/conversations").json()["items"]
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


def test_reset_all_agent_test_conversations_preserves_agents_and_clears_lineage(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    second = session_service.create_chat_session(title="第二个测试 Agent")
    child_workspace = tmp_path / child["workspacePath"]
    child_workspace.mkdir(parents=True, exist_ok=True)
    (child_workspace / "turn_journal.jsonl").write_text("{}\n", encoding="utf-8")

    result = session_service.reset_all_agent_test_conversations()

    assert result["status"] == "deleted"
    assert set(result["sessionIds"]) == {direct["id"], child["id"], second["id"]}
    assert result["deletedCount"] == 3
    assert result["agentBindingsCleared"] >= 2
    assert not child_workspace.exists()
    conversations_payload = client.get("/api/conversations").json()
    assert conversations_payload["items"] == []
    assert conversations_payload["totalEstimate"] == 0
    for agent_id in (direct["agentId"], second["agentId"]):
        agent = agent_directory_service.get_agent(agent_id, include_archived=True)
        assert agent is not None
        assert agent["status"] == "active"
        assert agent.get("directSessionId") in {None, ""}


def test_reset_all_agent_test_conversations_fails_closed_while_a_turn_is_active(tmp_path, monkeypatch):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    session_service._set_session_running(child["id"], True)

    with pytest.raises(session_service.SessionBusyError):
        session_service.reset_all_agent_test_conversations()

    assert session_service.get_session_detail(direct["id"]) is not None
    assert session_service.get_session_detail(child["id"]) is not None
    agent = agent_directory_service.get_agent(direct["agentId"], include_archived=True)
    assert agent is not None
    assert agent.get("directSessionId") == direct["id"]


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


@pytest.mark.parametrize("lightweight", [False, True])
def test_archived_session_can_be_viewed_without_mutating_or_activating_it(
    tmp_path, monkeypatch, lightweight,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    response = client.delete(f"/api/agents/{direct['agentId']}")
    assert response.status_code == 200, response.text
    before = session_service.load_session_chat_state(tmp_path, direct["id"])
    active_before = session_service.load_active_conversation_id(tmp_path)
    writes = []
    original_save = session_service.save_session_chat_state

    def record_save(*args, **kwargs):
        writes.append((args, kwargs))
        return original_save(*args, **kwargs)

    monkeypatch.setattr(session_service, "save_session_chat_state", record_save)
    selected = session_service.select_chat_session(direct["id"], lightweight=lightweight)

    assert selected["id"] == direct["id"]
    assert selected["readOnly"] is True
    assert selected["archiveState"]["source"] == "agent_archive"
    selected_response = client.post(
        f"/api/sessions/{direct['id']}/select",
        headers={"Prefer": "respond-async"} if lightweight else {},
    )
    assert selected_response.status_code == 200
    assert selected_response.json()["readOnly"] is True
    assert session_service.load_session_chat_state(tmp_path, direct["id"]) == before
    assert session_service.load_active_conversation_id(tmp_path) == active_before
    assert writes == []


@pytest.mark.parametrize(
    "mutation",
    [
        "rename",
        "child",
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
        elif mutation == "child":
            session_service.create_child_session(
                direct["id"],
                user_request="不应拆子会话",
                task_title="封存后子会话",
                auto_start=False,
            )
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


def test_archived_session_can_still_be_deleted(tmp_path, monkeypatch):
    """Read-only sealing must not block delete — otherwise archived sessions
    are wedged forever (the historical 422 "已归档并处于只读状态" defect)."""

    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text

    result = session_service.delete_chat_session(direct["id"])

    assert result["deleted"] is True
    assert result["deletedSessionId"] == direct["id"]
    payload = session_service.load_chat_state(session_service.PROJECT_ROOT)
    assert session_service._find_conversation_entry(payload, direct["id"]) is None


def test_archived_session_delete_route_succeeds(tmp_path, monkeypatch):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    archive_response = client.delete(f"/api/agents/{direct['agentId']}")
    assert archive_response.status_code == 200, archive_response.text

    response = client.delete(f"/api/sessions/{direct['id']}")

    assert response.status_code == 200, response.text
    payload = session_service.load_chat_state(session_service.PROJECT_ROOT)
    assert session_service._find_conversation_entry(payload, direct["id"]) is None


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


def test_restore_replay_does_not_resurrect_deleted_tombstoned_sessions(
    tmp_path,
    monkeypatch,
):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    timestamp = session_service._now_timestamp()
    # A lifecycle restore token whose snapshot list still carries a session
    # that was deleted through the agent-deleted tombstone path.
    token = {
        "agentId": direct["agentId"],
        "sessionIds": [direct["id"], "deleted-session"],
        "previousConversations": [
            {
                "index": 0,
                "conversation": {
                    "conversation_id": direct["id"],
                    "agent_id": direct["agentId"],
                    "title": "live session",
                    "messages": [],
                },
            },
            {
                "index": 1,
                "conversation": {
                    "conversation_id": "deleted-session",
                    "agent_id": "",
                    "agentId": "",
                    "agent_deleted_id": direct["agentId"],
                    "agentDeletedId": direct["agentId"],
                    "agentMissing": True,
                    "agentStatusCode": "deleted_agent",
                    "agentDeletedTombstone": {
                        "agentId": direct["agentId"],
                        "sessionId": "deleted-session",
                        "deletedAt": timestamp,
                        "previousStatus": "ready",
                        "historyRetention": "preserved_tombstone",
                    },
                    "title": "deleted session",
                    "messages": [],
                },
            },
        ],
        "previousActiveConversationId": direct["id"],
        "previousUpdatedAt": "",
        "previousVersion": 1,
        "createdReplacementSessionId": "",
        "workspaceMoves": [],
    }

    assert session_service._restore_agent_session_lifecycle_state(token) is True

    payload = session_service.load_chat_state(session_service.PROJECT_ROOT)
    restored_ids = [
        str(raw.get("conversation_id") or "").strip()
        for raw in list(payload.get("conversations") or [])
        if isinstance(raw, dict)
    ]
    assert direct["id"] in restored_ids
    assert "deleted-session" not in restored_ids


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


def test_archive_failure_rolls_back_dissolved_last_member_room(tmp_path, monkeypatch):
    from core.web.routes import agents as agent_routes

    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    room = chat_room_service.create_chat_room(
        title="归档回滚群聊",
        participant_session_ids=[direct["id"]],
    )

    def fail_archive(*args, **kwargs):
        raise agent_directory_service.AgentDirectoryError("archive write failed")

    monkeypatch.setattr(agent_routes, "archive_agent_instance", fail_archive)

    response = client.delete(f"/api/agents/{direct['agentId']}")

    assert response.status_code == 422, response.text
    assert agent_directory_service.get_agent(direct["agentId"])["status"] == "active"
    detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert detail is not None
    assert [item["agentId"] for item in detail["participants"]] == [direct["agentId"]]


def test_archive_keeps_shared_room_for_non_last_member(tmp_path, monkeypatch):
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    peer = session_service.create_chat_session(title="共享群聊留守 Agent")
    room = chat_room_service.create_chat_room(
        title="共享群聊",
        participant_agent_ids=[direct["agentId"], peer["agentId"]],
    )

    response = client.delete(f"/api/agents/{direct['agentId']}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["archiveSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert payload["archiveSummary"]["dissolvedRoomIds"] == []
    assert [item["roomId"] for item in chat_room_service.list_chat_rooms()] == [room["roomId"]]
    detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [item["agentId"] for item in detail["participants"]] == [peer["agentId"]]


def test_archive_waits_out_submit_admission_window_then_refuses_busy(tmp_path, monkeypatch):
    """G4 (chat-fix2 R4): archive must not seal inside a submit admission window.

    Submit holds the per-session admission lock from its busy check through
    running registration. An archive issued inside that window must park on
    the same lock (taken before the lifecycle chat-state lock, canonical
    order) and then refuse as busy instead of sealing a session whose turn is
    still being admitted.
    """
    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    agent_id = direct["agentId"]
    session_id = direct["id"]
    admit_lock = session_service._session_submit_admit_lock(session_id)
    admit_lock.acquire()
    archive_started = threading.Event()
    result_box: dict[str, object] = {}

    def run_archive():
        archive_started.set()
        try:
            result_box["result"] = session_service.archive_agent_sessions(
                agent_id,
                direct_session_id=session_id,
            )
        except BaseException as exc:  # noqa: BLE001 - forwarded to assertions below
            result_box["error"] = exc

    archiver = threading.Thread(target=run_archive, name="agent-archive-admit-race")
    archiver.start()
    assert archive_started.wait(timeout=5)
    time.sleep(0.1)  # let the archive park on the admission lock; outcome is order-independent
    # The submit window closes with the turn registered as running.
    session_service._set_session_running(session_id, True, turn_id="turn-archive-race")
    admit_lock.release()
    archiver.join(timeout=15)
    assert archiver.is_alive() is False
    try:
        assert isinstance(result_box.get("error"), session_service.SessionBusyError)
        assert "result" not in result_box

        # The refused archive must leave the direct session unsealed and open.
        detail = session_service.get_session_detail(
            session_id, message_limit=0, transcript_scope="none"
        )
        assert detail is not None
        assert detail.get("readOnly") is not True
        assert str((detail.get("archiveState") or {}).get("status") or "") != "archived"
    finally:
        session_service._set_session_running(session_id, False)


def _archive_via_http(entry, agent_id):
    if entry == "delete":
        return client.delete(f"/api/agents/{agent_id}")
    if entry == "patch":
        return client.patch(f"/api/agents/{agent_id}", json={"status": "archived"})
    return client.post("/api/agents/bulk-archive", json={"agentIds": [agent_id]})


@pytest.mark.parametrize("entry", ["delete", "patch", "bulk"])
def test_archive_route_waiting_for_admission_does_not_block_other_session(
    tmp_path, monkeypatch, entry,
):
    from core.web.services.session.admission_lock import SessionAdmissionLock

    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    peer = session_service.create_chat_session(title="归档期间仍可操作")
    waiting = threading.Event()
    release = threading.Event()
    peer_completed = threading.Event()
    result: dict[str, object] = {}
    original_acquire = SessionAdmissionLock.acquire

    def delayed_acquire(lock, *args, **kwargs):
        if threading.current_thread().name.startswith("AnyIO worker"):
            waiting.set()
            assert release.wait(timeout=5)
        return original_acquire(lock, *args, **kwargs)

    monkeypatch.setattr(SessionAdmissionLock, "acquire", delayed_acquire)

    def archive():
        result["response"] = _archive_via_http(entry, direct["agentId"])

    def rename_peer():
        session_service.update_chat_session_title(peer["id"], "归档等待期间已改名")
        peer_completed.set()

    archiver = threading.Thread(target=archive, daemon=True)
    peer_writer = threading.Thread(target=rename_peer, daemon=True)
    archiver.start()
    try:
        assert waiting.wait(timeout=3)
        peer_writer.start()
        assert peer_completed.wait(timeout=0.5), (
            "Waiting for archive admission must not hold the global chat-state lock."
        )
    finally:
        release.set()
        archiver.join(timeout=10)
        if peer_writer.ident is not None:
            peer_writer.join(timeout=10)
    assert not archiver.is_alive()
    assert not peer_writer.is_alive()
    response = result["response"]
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("entry", ["delete", "patch", "bulk"])
def test_archive_route_and_owned_session_delete_finish_without_lock_inversion(
    tmp_path, monkeypatch, entry,
):
    from core.web.services.session.admission_lock import SessionAdmissionLock

    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    held = threading.Event()
    archive_waiting = threading.Event()
    deletion_completed = threading.Event()
    results: dict[str, object] = {}
    original_acquire = SessionAdmissionLock.acquire
    target_path = session_service._session_submit_admit_lock(child["id"]).path

    def observed_acquire(lock, *, timeout=30.0):
        if threading.current_thread().name.startswith("AnyIO worker") and lock.path == target_path:
            archive_waiting.set()
            # Keep a broken implementation's failure bounded and reclaimable.
            timeout = min(timeout, 1.0)
        return original_acquire(lock, timeout=timeout)

    monkeypatch.setattr(SessionAdmissionLock, "acquire", observed_acquire)

    def delete_owned_session():
        try:
            with session_service._session_submit_admit_lock(child["id"]):
                held.set()
                assert archive_waiting.wait(timeout=3)
                results["deletion"] = session_service.delete_chat_session(child["id"])
                deletion_completed.set()
        except BaseException as exc:
            results["deletion_error"] = exc

    def archive():
        results["response"] = _archive_via_http(entry, direct["agentId"])

    deleter = threading.Thread(target=delete_owned_session, daemon=True)
    archiver = threading.Thread(target=archive, daemon=True)
    deleter.start()
    try:
        assert held.wait(timeout=3)
        archiver.start()
        assert deletion_completed.wait(timeout=3), results
    finally:
        deleter.join(timeout=5)
        if archiver.ident is not None:
            archiver.join(timeout=5)
    assert not deleter.is_alive()
    assert not archiver.is_alive()
    assert "deletion_error" not in results, results
    assert results["deletion"]["deleted"] is True
    response = results["response"]
    assert response.status_code == 200, response.text
    assert session_service.get_session_detail(direct["id"])["readOnly"] is True


@pytest.mark.parametrize("entry", ["delete", "patch", "bulk"])
def test_archive_refuses_new_owned_session_before_reference_writes(
    tmp_path, monkeypatch, entry,
):
    from core.web.services.session.admission_lock import SessionAdmissionLock

    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    room = chat_room_service.create_chat_room(
        title="归档快照变化仍保留成员", participant_session_ids=[direct["id"]],
    )
    original_acquire = SessionAdmissionLock.acquire
    added: list[str] = []

    def add_session_before_lifecycle(lock, *args, **kwargs):
        acquired = original_acquire(lock, *args, **kwargs)
        if not added:
            added.append("creating")
            child = session_service.create_child_session(
                direct["id"], user_request="并发新增", task_title="归档快照之后",
                auto_start=False, switch_to_child=False,
            )["childSession"]
            added[0] = child["id"]
        return acquired

    monkeypatch.setattr(SessionAdmissionLock, "acquire", add_session_before_lifecycle)
    response = _archive_via_http(entry, direct["agentId"])

    if entry == "bulk":
        assert response.status_code == 200, response.text
        assert response.json()["summary"]["failedCount"] == 1
        assert response.json()["failed"][0]["reason"] == "busy"
    else:
        assert response.status_code == 409, response.text
    assert agent_directory_service.get_agent(direct["agentId"])["status"] == "active"
    assert session_service.get_session_detail(added[0])["readOnly"] is False
    assert chat_room_service.get_chat_room_detail(room["roomId"])["participants"][0]["agentId"] == direct["agentId"]


def test_archive_admission_timeout_releases_partially_acquired_session_locks(
    tmp_path, monkeypatch,
):
    direct, child = _create_agent_with_child_session(tmp_path, monkeypatch)
    first_id, last_id = sorted([direct["id"], child["id"]])
    held = threading.Event()
    release = threading.Event()
    first_available = threading.Event()

    def hold_last():
        with session_service._session_submit_admit_lock(last_id):
            held.set()
            assert release.wait(timeout=5)

    def acquire_first():
        with session_service._session_submit_admit_lock(first_id):
            first_available.set()

    holder = threading.Thread(target=hold_last, daemon=True)
    checker = threading.Thread(target=acquire_first, daemon=True)
    holder.start()
    try:
        assert held.wait(timeout=2)
        with pytest.raises(session_service.SessionBusyError):
            with session_service.agent_archive_transaction(direct["agentId"], timeout=0.05):
                pytest.fail("Archive entered while the final session admission was held.")
        checker.start()
        assert first_available.wait(timeout=1)
    finally:
        release.set()
        holder.join(timeout=3)
        if checker.ident is not None:
            checker.join(timeout=3)
    assert not holder.is_alive()
    assert not checker.is_alive()


@pytest.mark.parametrize("entry", ["delete", "patch", "bulk"])
@pytest.mark.parametrize("held_lock", ["chat_thread", "agent", "state"])
def test_archive_route_lock_budget_reports_busy_and_releases_all_locks(
    tmp_path, monkeypatch, entry, held_lock,
):
    from core.web.services import runtime_scene_service

    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    scene = runtime_scene_service.start_runtime_scene("agent_archive_lock_regression")
    scene_dir = Path(scene["runtimeSceneDir"])
    assert scene_dir.is_relative_to(tmp_path)
    original_transaction = session_service.agent_archive_transaction
    monkeypatch.setattr(
        session_service, "agent_archive_transaction",
        lambda agent_id: original_transaction(agent_id, timeout=0.2),
    )
    lock = {
        "chat_thread": session_service._CHAT_STATE_LOCK._thread_lock,
        "agent": agent_directory_service._AGENT_SESSION_LIFECYCLE_LOCK,
        "state": agent_directory_service._STATE_LOCK,
    }[held_lock]
    held = threading.Event()
    release = threading.Event()

    def hold():
        with lock:
            held.set()
            release.wait(timeout=3)  # bounded cleanup even if a route ignores its budget

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    started = time.monotonic()
    try:
        assert held.wait(timeout=2)
        response = _archive_via_http(entry, direct["agentId"])
        assert time.monotonic() - started < 2
        if entry == "bulk":
            assert response.status_code == 200, response.text
            assert response.json()["failed"][0]["reason"] == "busy"
        else:
            assert response.status_code == 409, response.text
    finally:
        release.set()
        holder.join(timeout=3)
    assert not holder.is_alive()
    events = [
        json.loads(line)
        for line in (scene_dir / "events" / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    lock_events = [event for event in events if event["event_code"].startswith("agent.archive.lock.")]
    expected_codes = ["agent.archive.lock.requested"]
    if held_lock != "state":
        expected_codes.append("agent.archive.lock.waiting")
    expected_codes.append("agent.archive.lock.busy")
    assert [event["event_code"] for event in lock_events] == expected_codes
    busy = lock_events[-1]["fields"]
    assert busy["agentId"] == direct["agentId"]
    assert busy["sessionCount"] == (0 if held_lock == "state" else 2)
    assert busy["stage"] == ("snapshot" if held_lock == "state" else "chat_agent_lifecycle")
    assert busy["errorType"] == "SessionBusyError"
    assert 100 <= busy["waitMs"] < 2000
    assert agent_directory_service.get_agent(direct["agentId"])["status"] == "active"
    retry = _archive_via_http(entry, direct["agentId"])
    assert retry.status_code == 200, retry.text
    assert session_service.get_session_detail(direct["id"])["readOnly"] is True


@pytest.mark.parametrize("entry", ["delete", "patch", "bulk"])
def test_archive_route_waits_for_submit_admission_then_refuses_busy(
    tmp_path, monkeypatch, entry,
):
    from core.web.services.session.admission_lock import SessionAdmissionLock

    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    admission = session_service._session_submit_admit_lock(direct["id"])
    original_acquire = SessionAdmissionLock.acquire
    waiting = threading.Event()
    result: dict[str, object] = {}

    def observe_admission(lock, *args, **kwargs):
        if threading.current_thread().name.startswith("AnyIO worker") and lock.path == admission.path:
            waiting.set()
        return original_acquire(lock, *args, **kwargs)

    monkeypatch.setattr(SessionAdmissionLock, "acquire", observe_admission)
    admission.acquire()

    def archive():
        result["response"] = _archive_via_http(entry, direct["agentId"])

    archiver = threading.Thread(target=archive, daemon=True)
    archiver.start()
    try:
        assert waiting.wait(timeout=3)
        # Model the submit admission's final registration before it releases
        # its fence. No worker or external model call is started by this test.
        session_service._set_session_running(direct["id"], True, turn_id="archive-admission-race")
    finally:
        admission.release()
        archiver.join(timeout=5)
        session_service._set_session_running(direct["id"], False)
    assert not archiver.is_alive()
    response = result["response"]
    if entry == "bulk":
        assert response.status_code == 200, response.text
        assert response.json()["failed"][0]["reason"] == "busy"
    else:
        assert response.status_code == 409, response.text
    assert agent_directory_service.get_agent(direct["agentId"])["status"] == "active"
    assert session_service.get_session_detail(direct["id"])["readOnly"] is False
