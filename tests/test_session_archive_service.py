"""Session-level archive/unarchive: API contract + directory index sync."""

from __future__ import annotations

import json
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

from core.web.services.session import directory_runtime
from core.web.services import session_archive_service


def _create_session(tmp_path, monkeypatch, title: str = "归档测试会话") -> dict:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    return session_service.create_chat_session(title=title)


def _detail(session_id: str) -> dict:
    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_archive_unarchive_round_trip(tmp_path, monkeypatch):
    created = _create_session(tmp_path, monkeypatch)
    session_id = created["id"]

    archived = client.post(f"/api/sessions/{session_id}/archive")
    assert archived.status_code == 200, archived.text
    payload = archived.json()
    assert payload["sessionId"] == session_id
    assert payload["status"] == "archived"
    assert payload["changed"] is True
    assert payload["readOnly"] is True
    assert payload["archivedAt"]

    detail = _detail(session_id)
    assert detail["archiveState"]["status"] == "archived"
    assert detail["archiveState"]["source"] == "session_archive"
    assert detail["archiveState"]["archivedAt"] == payload["archivedAt"]
    assert detail["readOnly"] is True

    # Archived sessions accept no new turns (existing read-only guard).
    write_response = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": "归档后不应继续写入"},
    )
    assert write_response.status_code == 422, write_response.text
    assert "归档" in str(write_response.json()["detail"]) or "archived" in str(
        write_response.json()["detail"]
    ).lower()

    # Archived rows leave the canonical default list entirely (backend-level
    # exclusion, same contract as the Agent-archive lifecycle).
    listed = client.get("/api/sessions").json()
    listed_ids = {item["id"] for item in listed}
    assert session_id not in listed_ids
    queried = client.get("/api/sessions/query").json()
    assert session_id not in {item["id"] for item in queried.get("items") or []}

    # The dedicated archived listing returns it.
    archived_page = client.get("/api/session-archive").json()
    assert [item["id"] for item in archived_page["items"]] == [session_id]
    assert archived_page["totalEstimate"] == 1

    # Unarchive restores mutability and clears the flag.
    unarchived = client.post(f"/api/sessions/{session_id}/unarchive")
    assert unarchived.status_code == 200, unarchived.text
    unarchived_payload = unarchived.json()
    assert unarchived_payload["changed"] is True
    assert unarchived_payload["status"] == ""
    assert unarchived_payload["readOnly"] is False

    detail_after = _detail(session_id)
    assert detail_after.get("archiveState", {}) == {}
    assert detail_after["readOnly"] is False

    emptied = client.get("/api/session-archive").json()
    assert emptied["items"] == []
    assert emptied["totalEstimate"] == 0

    # The session is mutable again: a fresh archive round works.
    re_archived = client.post(f"/api/sessions/{session_id}/archive")
    assert re_archived.status_code == 200, re_archived.text
    assert re_archived.json()["changed"] is True


def test_archive_is_idempotent(tmp_path, monkeypatch):
    created = _create_session(tmp_path, monkeypatch)
    session_id = created["id"]

    first = client.post(f"/api/sessions/{session_id}/archive").json()
    assert first["changed"] is True
    second = client.post(f"/api/sessions/{session_id}/archive").json()
    assert second["changed"] is False
    assert second["status"] == "archived"
    assert second["archivedAt"] == first["archivedAt"]


def test_unarchive_without_archive_is_idempotent(tmp_path, monkeypatch):
    created = _create_session(tmp_path, monkeypatch)
    session_id = created["id"]

    response = client.post(f"/api/sessions/{session_id}/unarchive")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["changed"] is False
    assert payload["status"] == ""


def test_archive_rejects_session_with_in_progress_turn(tmp_path, monkeypatch):
    created = _create_session(tmp_path, monkeypatch)
    session_id = created["id"]
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)

    response = client.post(f"/api/sessions/{session_id}/archive")
    assert response.status_code == 409, response.text
    assert "归档" in str(response.json()["detail"]) or "archived" in str(
        response.json()["detail"]
    ).lower()

    detail = _detail(session_id)
    assert detail.get("archiveState", {}) == {}
    assert detail["readOnly"] is False


def test_archive_missing_session_returns_404(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    assert client.post("/api/sessions/does-not-exist/archive").status_code == 404
    assert client.post("/api/sessions/does-not-exist/unarchive").status_code == 404


def test_agent_sealed_sessions_stay_out_of_user_archive_view_and_reject_unarchive(
    tmp_path, monkeypatch
):
    """source="agent_archive" rows belong to the Agent lifecycle, not the user view."""

    created = _create_session(tmp_path, monkeypatch, title="Agent 封存会话")
    session_id = created["id"]
    agent_id = str(created.get("agentId") or "").strip()
    assert agent_id

    # Real agent-archive seal path (same contract as DELETE /api/agents).
    result = agent_bulk_delete_service.bulk_archive_agents([agent_id])
    assert result.get("archivedCount", result.get("archived", 0)) or result

    detail = _detail(session_id)
    assert detail["archiveState"]["status"] == "archived"
    assert detail["archiveState"]["source"] == "agent_archive"

    # Agent-sealed rows never enter the user archived view.
    archived_page = client.get("/api/session-archive").json()
    assert session_id not in {item["id"] for item in archived_page["items"]}

    # And user-side unarchive is rejected: only the Agent lifecycle unseals.
    response = client.post(f"/api/sessions/{session_id}/unarchive")
    assert response.status_code == 422, response.text
    detail_message = str(response.json()["detail"])
    assert "Agent" in detail_message and ("封存" in detail_message or "seal" in detail_message.lower())

    # The seal is untouched afterwards.
    detail_after = _detail(session_id)
    assert detail_after["archiveState"]["status"] == "archived"
    assert detail_after["archiveState"]["source"] == "agent_archive"
    assert detail_after["readOnly"] is True


def test_unarchive_restores_manual_read_only_state(tmp_path, monkeypatch):
    """A manually read-only session keeps read_only across an archive round."""

    created = _create_session(tmp_path, monkeypatch, title="手动只读会话")
    session_id = created["id"]
    conversation = session_service.load_session_chat_state(
        session_service.PROJECT_ROOT, session_id
    )
    assert conversation is not None
    conversation["read_only"] = True
    conversation["readOnly"] = True
    session_service.save_session_chat_state(
        session_service.PROJECT_ROOT, session_id, conversation
    )

    archived = client.post(f"/api/sessions/{session_id}/archive")
    assert archived.status_code == 200, archived.text
    unarchived = client.post(f"/api/sessions/{session_id}/unarchive")
    assert unarchived.status_code == 200, unarchived.text

    detail = _detail(session_id)
    assert detail.get("archiveState", {}) == {}
    # The pre-archive manual read-only flag survives the archive round.
    assert detail["readOnly"] is True


def test_store_directory_row_leaves_default_index_and_is_restored(
    tmp_path, monkeypatch
):
    """Store-level: archived_at_ms seal excludes the row; unarchive restores it."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "operator-config"))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        config_service, "get_config_workspace", _fake_config_workspace, raising=False
    )
    registry_path = agent_directory_service.registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schemaVersion": 7,
                "agents": [
                    {
                        "agentId": "agent-archive-store",
                        "displayName": "Archive Store",
                        "kind": "persistent",
                        "primaryMode": "chat",
                        "conversationIndexKind": "personal_agent",
                        "directSessionId": "",
                        "metadata": {
                            "conversationIndexKind": "personal_agent",
                            "directSessionVisibility": "active_session",
                        },
                        "llmBindings": {"dialogue": {"modelId": "gpt-5.6-luna"}},
                        "promptTemplateId": "chat",
                        "toolPolicyId": "tool-default",
                        "toolPolicy": {"policyId": "tool-default"},
                        "memoryPolicyId": "memory-default",
                        "memoryPolicy": {"policyId": "memory-default"},
                        "permissionPreset": "request_approval",
                        "status": "active",
                    }
                ],
                "toolPolicies": {"tool-default": {"policyId": "tool-default"}},
                "memoryPolicies": {"memory-default": {"policyId": "memory-default"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    status = directory_runtime.initialize_session_directory_runtime(project_root=tmp_path)
    assert status.status == "ready"
    try:
        created = session_service.create_chat_session(
            title="目录库归档", agent_id="agent-archive-store"
        )
        session_id = created["id"]
        store = directory_runtime.get_open_directory_store()
        assert store is not None
        assert store.repository.get_session(session_id) is not None

        result = session_archive_service.archive_session(session_id)
        assert result["changed"] is True
        # The sealed row leaves the default directory listing (hidden + archived).
        assert store.repository.get_session(session_id) is None
        page = store.repository.list_directory_page()
        assert session_id not in {
            item["sessionId"] for item in page.get("rows") or []
        }
        assert session_id not in {
            item["sessionId"]
            for item in store.repository.list_sessions(agent_id="agent-archive-store")
        }

        restored = session_archive_service.unarchive_session(session_id)
        assert restored["changed"] is True
        assert store.repository.get_session(session_id) is not None
        listed_ids = {
            item["sessionId"]
            for item in store.repository.list_sessions(agent_id="agent-archive-store")
        }
        assert session_id in listed_ids
    finally:
        directory_runtime.shutdown_session_directory_runtime()
