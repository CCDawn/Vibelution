from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from core.chat.turn_journal import turn_journal_path
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import agent_directory_service, session_service
from core.web.services.session import directory_runtime


@pytest.fixture
def isolated_directory_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "operator-config"))
    monkeypatch.setattr(
        directory_runtime.developer_sandbox,
        "is_developer_mode_enabled",
        lambda: False,
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(directory_runtime, "record_runtime_scene_event", lambda *_args, **_kwargs: {})
    yield tmp_path
    directory_runtime.shutdown_session_directory_runtime()


def _write_agents_registry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 7,
                "agents": [
                    {
                        "agentId": "agent-alpha",
                        "displayName": "Alpha",
                        "kind": "persistent",
                        "primaryMode": "chat",
                        "conversationIndexKind": "personal_agent",
                        "directSessionId": "legacy-session",
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


def _seed_legacy_session(project_root: Path) -> Path:
    save_chat_state(
        project_root,
        {
            "version": 1,
            "active_conversation_id": "legacy-session",
            "conversations": [
                {
                    "conversation_id": "legacy-session",
                    "title": "Legacy session",
                    "agent_id": "agent-alpha",
                    "agentId": "agent-alpha",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
            "updated_at": "2026-01-01T00:00:00",
        },
    )
    journal_path = turn_journal_path(project_root, "legacy-session")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps({"eventType": "user_message", "payload": {"content": "do not import"}})
        + "\n",
        encoding="utf-8",
    )
    return journal_path


def test_directory_runtime_discards_legacy_sessions_without_importing_journals(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    journal_path = _seed_legacy_session(project_root)

    status = directory_runtime.initialize_session_directory_runtime(project_root=project_root)

    assert status.status == "ready"
    assert status.discarded_legacy is True
    assert status.discarded_session_count == 1
    payload = load_chat_state(project_root)
    assert payload.get("conversations") == []
    assert str(payload.get("active_conversation_id") or "") == ""
    assert not journal_path.exists()
    store = directory_runtime.get_open_directory_store()
    assert store is not None
    assert store.repository.list_sessions(agent_id="agent-alpha") == []
    assert store.repository.legacy_sessions_discarded_at_ms() is not None
    agent = agent_directory_service.get_agent("agent-alpha", include_archived=True)
    assert str((agent or {}).get("directSessionId") or "") == "legacy-session"
    assert "legacy-session" in _session_ids()


def test_directory_runtime_second_initialize_keeps_new_sessions(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    _seed_legacy_session(project_root)
    first = directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    store = directory_runtime.get_open_directory_store()
    assert store is not None
    agent = store.repository.get_agent("agent-alpha")
    assert agent is not None
    store.repository.upsert_directory_session(
        session_id="kept-session",
        agent_id="agent-alpha",
        agent_config_revision_id=str(agent["currentConfigRevisionId"]),
        title="Kept after cutover",
        last_preview="preview from persist",
    ).result(timeout=5)

    second = directory_runtime.initialize_session_directory_runtime(project_root=project_root)

    assert first.discarded_legacy is True
    assert second.discarded_legacy is False
    store = directory_runtime.get_open_directory_store()
    assert store is not None
    rows = store.repository.list_sessions(agent_id="agent-alpha")
    assert [row["sessionId"] for row in rows] == ["kept-session"]
    assert rows[0]["lastPreview"] == "preview from persist"


def test_create_and_query_read_store_without_scanning_journals(
    isolated_directory_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)

    def fail_journal_scan(*_args, **_kwargs):
        raise AssertionError("query_sessions must not scan turn journals")

    monkeypatch.setattr(session_service, "load_conversation_events", fail_journal_scan)
    monkeypatch.setattr(session_service, "load_conversation_preview_slice", fail_journal_scan)

    created = session_service.create_chat_session(title="Store backed", agent_id="agent-alpha")
    session_id = str(created.get("id") or "").strip()
    assert session_id

    payload = session_service.query_sessions(limit=10)
    ids = {str(item.get("id") or "") for item in payload.get("items") or []}
    assert session_id in ids
    listed = session_service.list_sessions()
    assert session_id in {str(item.get("id") or "") for item in listed}


def _session_ids(include_hidden: bool = False) -> set[str]:
    return {
        str(item.get("id") or "").strip()
        for item in session_service.list_sessions(include_hidden_internal=include_hidden)
    }


def _store_directory_rows(*, include_hidden: bool = True) -> list[dict]:
    store = directory_runtime.get_open_directory_store()
    assert store is not None
    page = store.repository.list_directory_page(include_hidden=include_hidden, limit=200)
    return list(page.get("rows") or [])


def test_startup_query_waits_for_discard_and_does_not_flash_legacy(
    isolated_directory_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    _seed_legacy_session(project_root)
    entered = threading.Event()
    release = threading.Event()
    original_discard = directory_runtime._discard_legacy_sessions_once

    def paused_discard(store, root):
        entered.set()
        assert release.wait(5)
        return original_discard(store, root)

    monkeypatch.setattr(directory_runtime, "_discard_legacy_sessions_once", paused_discard)
    directory_runtime.begin_directory_startup()
    status_holder: dict[str, object] = {}

    def run_initialize():
        status_holder["status"] = directory_runtime.initialize_session_directory_runtime(
            project_root=project_root
        )

    init_thread = threading.Thread(target=run_initialize)
    init_thread.start()
    assert entered.wait(5)
    query_holder: dict[str, object] = {}

    def run_query():
        query_holder["payload"] = session_service.query_sessions(limit=10)
        query_holder["listed"] = session_service.list_sessions()

    query_thread = threading.Thread(target=run_query)
    query_thread.start()
    time.sleep(0.1)
    release.set()
    init_thread.join(8)
    query_thread.join(8)
    assert not init_thread.is_alive()
    assert not query_thread.is_alive()
    assert getattr(status_holder.get("status"), "status", "") == "ready"
    payload = query_holder["payload"]
    assert isinstance(payload, dict)
    query_ids = {str(item.get("id") or "") for item in payload.get("items") or []}
    listed_ids = {str(item.get("id") or "") for item in query_holder["listed"] or []}
    assert "legacy-session" not in query_ids
    assert "legacy-session" not in listed_ids


def test_startup_timeout_does_not_fall_back_to_legacy_json(
    isolated_directory_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    _seed_legacy_session(project_root)
    directory_runtime.begin_directory_startup()
    monkeypatch.setattr(directory_runtime, "STARTING_WAIT_SECONDS", 0.05)
    payload = session_service.query_sessions(limit=10)
    assert payload.get("items") == []
    assert session_service.list_sessions() == []
    chat_state = load_chat_state(project_root)
    assert any(
        str(item.get("conversation_id") or "") == "legacy-session"
        for item in chat_state.get("conversations") or []
        if isinstance(item, dict)
    )


def test_archive_agent_sessions_hides_store_directory_rows(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    created = session_service.create_chat_session(title="Archive me", agent_id="agent-alpha")
    session_id = str(created.get("id") or "").strip()
    assert session_id in _session_ids()

    session_service.archive_agent_sessions("agent-alpha", direct_session_id=session_id)

    assert session_id not in _session_ids()
    hidden_ids = _session_ids(include_hidden=True)
    assert session_id in hidden_ids
    rows = _store_directory_rows(include_hidden=True)
    match = next(row for row in rows if str(row.get("sessionId") or "") == session_id)
    assert match.get("hiddenFromIndex") is True


def test_supervised_session_is_hidden_in_store_directory(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    created = session_service.create_supervised_agent_session(
        agent_id="agent-alpha",
        title="Hidden supervised",
    )
    session_id = str(created.get("id") or "").strip()
    assert session_id
    assert session_id not in _session_ids()
    assert session_id in _session_ids(include_hidden=True)
    rows = _store_directory_rows(include_hidden=True)
    match = next(row for row in rows if str(row.get("sessionId") or "") == session_id)
    assert match.get("sessionKind") == "supervised"
    assert match.get("hiddenFromIndex") is True


def test_reset_agent_direct_session_upserts_replacement_in_store(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    created = session_service.create_chat_session(title="Old direct", agent_id="agent-alpha")
    old_id = str(created.get("id") or "").strip()
    result = session_service.reset_agent_direct_session_lightweight(
        old_id,
        agent_id="agent-alpha",
    )
    new_id = str(result.get("replacementDirectSessionId") or "").strip()
    assert new_id
    visible = _session_ids()
    assert old_id not in visible
    assert new_id in visible


def test_materialize_direct_session_upserts_store_row(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    fresh_id = "materialized-direct-session"
    agent_directory_service.update_agent_instance("agent-alpha", direct_session_id=fresh_id)
    changed = session_service._ensure_agent_directory_conversation_materialized(
        fresh_id,
        source="test_session_directory_store",
    )
    assert changed is True
    payload = load_chat_state(project_root)
    chat_ids = {
        str(item.get("conversation_id") or "")
        for item in payload.get("conversations") or []
        if isinstance(item, dict)
    }
    assert fresh_id in chat_ids
    rows = _store_directory_rows(include_hidden=True)
    store_ids = {str(row.get("sessionId") or "") for row in rows}
    assert fresh_id in store_ids, rows
    match = next(row for row in rows if str(row.get("sessionId") or "") == fresh_id)
    if match.get("hiddenFromIndex"):
        assert fresh_id in _session_ids(include_hidden=True)
    else:
        assert fresh_id in _session_ids()


def test_direct_session_collision_repair_upserts_replacement(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    created = session_service.create_chat_session(title="Shared direct", agent_id="agent-alpha")
    session_id = str(created.get("id") or "").strip()
    second = agent_directory_service.create_agent_instance(display_name="Beta")
    second_id = str((second or {}).get("agentId") or "").strip()
    assert second_id
    state = agent_directory_service.load_state()
    for agent in list(state.get("agents") or []):
        if not isinstance(agent, dict):
            continue
        if str(agent.get("agentId") or "").strip() in {"agent-alpha", second_id}:
            agent["directSessionId"] = session_id
    agent_directory_service.save_state(state)
    repaired = session_service._repair_agent_direct_session_collisions(
        source_signature=("directory-store-collision", session_id),
    )
    assert repaired is True
    alpha = agent_directory_service.get_agent("agent-alpha") or {}
    beta = agent_directory_service.get_agent(second_id) or {}
    replacement_ids = {
        str(alpha.get("directSessionId") or "").strip(),
        str(beta.get("directSessionId") or "").strip(),
    }
    assert session_id in replacement_ids
    assert len(replacement_ids) == 2
    visible = _session_ids()
    assert replacement_ids <= visible


def test_team_agent_session_is_hidden_from_user_directory(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    created = session_service.create_chat_session(
        title="Challenge cup planner",
        agent_id="agent-alpha",
        conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        activate=True,
    )
    session_id = str(created.get("id") or "").strip()
    assert session_id
    assert session_id not in _session_ids()
    assert session_id in _session_ids(include_hidden=True)
    query_ids = {
        str(item.get("id") or "")
        for item in session_service.query_sessions(limit=20).get("items") or []
    }
    assert session_id not in query_ids
    rows = _store_directory_rows(include_hidden=True)
    match = next(row for row in rows if str(row.get("sessionId") or "") == session_id)
    assert match.get("conversationIndexKind") == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
    assert match.get("hiddenFromIndex") is True


def test_experiment_bound_team_session_stays_visible_in_user_directory(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    created = session_service.create_chat_session(
        title="Experiment planner",
        agent_id="agent-alpha",
        conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        experiment_binding={
            "teamId": "research-team",
            "researchProjectId": "research-alpha",
            "experimentName": "Alpha experiment",
            "agentId": "agent-alpha",
            "roleKey": "planner",
            "attempt": 1,
        },
    )
    session_id = str(created.get("id") or "").strip()
    assert session_id
    assert session_id in _session_ids()
    rows = _store_directory_rows(include_hidden=True)
    match = next(row for row in rows if str(row.get("sessionId") or "") == session_id)
    assert match.get("hiddenFromIndex") is False


def test_discard_blocks_materialize_while_discard_in_progress(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    _seed_legacy_session(project_root)
    directory_runtime._LEGACY_DISCARD_IN_PROGRESS.set()
    try:
        changed = session_service._ensure_agent_directory_conversation_materialized(
            "legacy-session",
            source="test_discard_blocks_materialize",
        )
        payload = load_chat_state(project_root)
        chat_ids = {
            str(item.get("conversation_id") or "")
            for item in payload.get("conversations") or []
            if isinstance(item, dict)
        }
    finally:
        directory_runtime._LEGACY_DISCARD_IN_PROGRESS.clear()
    assert changed is False
    assert "legacy-session" in chat_ids


def test_purge_archives_store_directory_rows(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    _write_agents_registry(agent_directory_service.registry_path())
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    created = session_service.create_chat_session(title="Purge me", agent_id="agent-alpha")
    session_id = str(created.get("id") or "").strip()
    assert session_id in _session_ids()
    agent_directory_service.update_agent_instance("agent-alpha", direct_session_id=session_id)
    agent_directory_service.archive_agent_instance("agent-alpha", repair_mode_bindings=False)
    session_service.stage_agent_session_purge("agent-alpha", direct_session_id=session_id)
    assert session_id not in _session_ids(include_hidden=True)
    rows = _store_directory_rows(include_hidden=True)
    assert all(str(row.get("sessionId") or "") != session_id for row in rows)


def test_team_agent_direct_binding_stays_hidden_from_user_directory(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    path = agent_directory_service.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 7,
                "agents": [
                    {
                        "agentId": "agent-team",
                        "displayName": "Planner",
                        "kind": "persistent",
                        "primaryMode": "research",
                        "roleKey": "planner",
                        "conversationIndexKind": "team_agent",
                        "directSessionId": "team-direct",
                        "llmBindings": {"dialogue": {"modelId": "gpt-5.6-luna"}},
                        "promptTemplateId": "chat",
                        "toolPolicyId": "tool-default",
                        "toolPolicy": {"policyId": "tool-default"},
                        "memoryPolicyId": "memory-default",
                        "memoryPolicy": {"policyId": "memory-default"},
                        "permissionPreset": "request_approval",
                        "status": "active",
                        "metadata": {
                            "conversationIndexKind": "team_agent",
                            "teamId": "research-team",
                        },
                    }
                ],
                "toolPolicies": {"tool-default": {"policyId": "tool-default"}},
                "memoryPolicies": {"memory-default": {"policyId": "memory-default"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    assert "team-direct" not in _session_ids()
    assert "team-direct" not in {
        str(item.get("id") or "")
        for item in session_service.query_sessions(limit=20).get("items") or []
    }


def test_missing_personal_direct_is_restored_on_directory_start(
    isolated_directory_runtime: Path,
):
    project_root = isolated_directory_runtime
    path = agent_directory_service.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 7,
                "agents": [
                    {
                        "agentId": "agent-chat",
                        "displayName": "Chat Agent",
                        "kind": "persistent",
                        "primaryMode": "chat",
                        "conversationIndexKind": "personal_agent",
                        "directSessionId": "",
                        "llmBindings": {"dialogue": {"modelId": "gpt-5.6-luna"}},
                        "promptTemplateId": "chat",
                        "toolPolicyId": "tool-default",
                        "toolPolicy": {"policyId": "tool-default"},
                        "memoryPolicyId": "memory-default",
                        "memoryPolicy": {"policyId": "memory-default"},
                        "permissionPreset": "request_approval",
                        "status": "active",
                        "metadata": {"conversationIndexKind": "personal_agent"},
                    }
                ],
                "toolPolicies": {"tool-default": {"policyId": "tool-default"}},
                "memoryPolicies": {"memory-default": {"policyId": "memory-default"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    directory_runtime.initialize_session_directory_runtime(project_root=project_root)
    agent = agent_directory_service.get_agent("agent-chat", include_archived=True)
    session_id = str((agent or {}).get("directSessionId") or "")
    assert session_id
    assert session_id in _session_ids()


def test_agent_direct_session_available_does_not_load_detail(
    isolated_directory_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from core.web.services.team import system_teams

    def fail_detail(*_args, **_kwargs):
        raise AssertionError("team bootstrap must not load session detail")

    monkeypatch.setattr(session_service, "get_session_detail", fail_detail)
    monkeypatch.setattr(
        session_service,
        "_is_session_workspace_intentionally_deleted",
        lambda _session_id: False,
    )
    assert system_teams._agent_direct_session_available(
        {"directSessionId": "sess-keep"},
        session_service=session_service,
    )
    assert not system_teams._agent_direct_session_available(
        {"directSessionId": ""},
        session_service=session_service,
    )
