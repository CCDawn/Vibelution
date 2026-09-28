from __future__ import annotations

from core.chat.conversation_ledger import EVENT_USER_MESSAGE, append_conversation_event
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import agent_directory_service, session_service


def _use_tmp_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    session_service._invalidate_session_list_cache()


def _agent(
    agent_id: str,
    *,
    code: str,
    name: str,
    session_id: str,
    updated_at: str,
) -> dict:
    return {
        "agentId": agent_id,
        "agentCode": code,
        "displayName": name,
        "kind": "persistent",
        "primaryMode": "chat",
        "roleKey": "",
        "llmBindings": {"dialogue": {"modelId": f"model-{agent_id}"}},
        "promptTemplateId": "prompt-chat-default",
        "directSessionId": session_id,
        "workspacePath": f"workspace/agents/{agent_id}",
        "toolPolicyId": f"tool-{agent_id}",
        "memoryPolicyId": f"memory-{agent_id}",
        "createdBy": "test",
        "status": "active",
        "metadata": {},
        "createdAt": "2026-06-01T00:00:00Z",
        "updatedAt": updated_at,
    }


def test_session_list_repairs_duplicate_direct_session_without_losing_history(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    shared_session_id = "session-shared"
    hidden_agent_id = "agent-hidden"
    visible_agent_id = "agent-visible"
    state = agent_directory_service.default_state()
    state["agents"] = [
        _agent(
            hidden_agent_id,
            code="A014",
            name="程听澜",
            session_id=shared_session_id,
            updated_at="2026-06-09T05:49:44Z",
        ),
        _agent(
            visible_agent_id,
            code="A030",
            name="顾明澈",
            session_id=shared_session_id,
            updated_at="2026-06-09T03:36:21Z",
        ),
    ]
    agent_directory_service.save_state(state)
    # The canonical ledger owns history. Seed it before the legacy chat_state
    # blob so the one-shot materializer sees an owned session and drops the
    # blob instead of appending a duplicate "保留历史" message.
    append_conversation_event(
        tmp_path,
        shared_session_id,
        "turn-preserved-history",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "保留历史"},
        timestamp="2026-06-09T10:53:30",
    )
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": shared_session_id,
            "conversations": [
                {
                    "conversation_id": shared_session_id,
                    "title": "小米2.5pro",
                    "agent_id": visible_agent_id,
                    "agentId": visible_agent_id,
                    "updated_at": "2026-06-09T10:53:30",
                    "workspace_path": "workspace/sessions/session-shared",
                    "messages": [{"role": "user", "content": "保留历史", "timestamp": "2026-06-09T10:53:30"}],
                }
            ],
        },
    )
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    sessions = session_service.list_sessions()

    visible = next(item for item in sessions if item["agentId"] == visible_agent_id)
    hidden = next(item for item in sessions if item["agentId"] == hidden_agent_id)
    assert visible["id"] == shared_session_id
    assert hidden["id"] != shared_session_id
    assert hidden["id"].startswith("session-")
    repaired_hidden = agent_directory_service.get_agent(hidden_agent_id)
    repaired_visible = agent_directory_service.get_agent(visible_agent_id)
    assert repaired_hidden["directSessionId"] == hidden["id"]
    assert repaired_visible["directSessionId"] == shared_session_id
    persisted = load_chat_state(tmp_path)
    original = next(item for item in persisted["conversations"] if item["conversation_id"] == shared_session_id)
    assert original["agent_id"] == visible_agent_id
    original_messages = session_service._session_ledger_visible_messages(shared_session_id)
    assert [(item["role"], item["content"], item["timestamp"]) for item in original_messages] == [
        ("user", "保留历史", "2026-06-09T10:53:30")
    ]
    assert any(item["conversation_id"] == hidden["id"] for item in persisted["conversations"])
    repair_events = [
        event
        for event in recorded_events
        if event[0][:3] == (
            "conversation",
            "agent_direct_session_collision",
            "session.agent_direct_session_collision.repaired",
        )
    ]
    assert repair_events
    assert repair_events[-1][1]["fields"]["preservedSessionId"] == shared_session_id
    assert repair_events[-1][1]["fields"]["repairedCount"] == 1


def test_session_list_preserves_protected_knowledge_steward_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward_session_id = agent_directory_service.KNOWLEDGE_STEWARD_DIRECT_SESSION_ID
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    intruder_id = "agent-intruder"
    state = agent_directory_service.default_state()
    steward = _agent(
        steward_id,
        code="A017",
        name="顾映白",
        session_id=steward_session_id,
        updated_at="2026-06-09T05:46:35Z",
    )
    steward["roleKey"] = agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY
    steward["metadata"] = {
        "systemRole": agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY,
        "protected": True,
    }
    state["agents"] = [
        steward,
        _agent(
            intruder_id,
            code="A030",
            name="顾明澈",
            session_id=steward_session_id,
            updated_at="2026-06-09T05:54:36Z",
        ),
    ]
    agent_directory_service.save_state(state)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": steward_session_id,
            "conversations": [
                {
                    "conversation_id": steward_session_id,
                    "title": "知识库管理",
                    "agent_id": intruder_id,
                    "agentId": intruder_id,
                    "updated_at": "2026-06-01T04:57:02",
                    "workspace_path": "workspace/sessions/agent-knowledge-steward-direct",
                    "messages": [],
                }
            ],
        },
    )

    sessions = session_service.list_sessions()

    steward_session = next(item for item in sessions if item["agentId"] == steward_id)
    intruder_session = next(item for item in sessions if item["agentId"] == intruder_id)
    assert steward_session["id"] == steward_session_id
    assert intruder_session["id"] != steward_session_id
    assert agent_directory_service.get_agent(steward_id)["directSessionId"] == steward_session_id
    assert agent_directory_service.get_agent(intruder_id)["directSessionId"] == intruder_session["id"]


def _seed_two_agent_registry(agent_directory_service) -> None:
    state = agent_directory_service.default_state()
    state["agents"] = [
        _agent(
            "agent-one",
            code="A041",
            name="沈知微",
            session_id="session-one",
            updated_at="2026-06-10T01:00:00Z",
        ),
        _agent(
            "agent-two",
            code="A042",
            name="陆望舒",
            session_id="session-two",
            updated_at="2026-06-10T01:01:00Z",
        ),
    ]
    agent_directory_service.save_state(state)


def _write_inbox_churn(agent_directory_service, agent_id: str) -> None:
    """Simulate streaming-side churn on a signature input that cannot change
    collision-repair detection: the agent's inbox JSONL."""
    state = agent_directory_service.load_state()
    agent = next(
        (
            item
            for item in state.get("agents") or []
            if isinstance(item, dict)
            and str(item.get("agentId") or "").strip() == agent_id
        ),
        None,
    )
    assert agent is not None
    inbox_path = agent_directory_service._agent_workspace_event_path(
        agent,
        "agent_inbox_messages.jsonl",
    )
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    with inbox_path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind":"probe","body":"streaming churn"}\n')


def test_collision_repair_memo_skips_rescan_while_registry_unchanged(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_two_agent_registry(agent_directory_service)
    original_load = session_service.load_chat_state
    load_calls = {"count": 0}

    def counting_load(project_root):
        load_calls["count"] += 1
        return original_load(project_root)

    monkeypatch.setattr(session_service, "load_chat_state", counting_load)

    # First scan runs and memoizes on the registry fingerprint.
    assert session_service._repair_agent_direct_session_collisions() is False
    first_scan_loads = load_calls["count"]
    assert first_scan_loads >= 1

    # Inbox/churn writes cannot change duplicate-group detection, so the memo
    # must skip the chat-state reload behind _CHAT_STATE_LOCK.
    _write_inbox_churn(agent_directory_service, "agent-one")
    assert session_service._repair_agent_direct_session_collisions() is False
    assert load_calls["count"] == first_scan_loads


def test_collision_repair_still_runs_after_registry_change(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_two_agent_registry(agent_directory_service)
    original_load = session_service.load_chat_state
    load_calls = {"count": 0}

    def counting_load(project_root):
        load_calls["count"] += 1
        return original_load(project_root)

    monkeypatch.setattr(session_service, "load_chat_state", counting_load)

    assert session_service._repair_agent_direct_session_collisions() is False
    first_scan_loads = load_calls["count"]

    # Streaming churn keeps the repair memoized (delayed convergence).
    _write_inbox_churn(agent_directory_service, "agent-two")
    assert session_service._repair_agent_direct_session_collisions() is False
    assert load_calls["count"] == first_scan_loads

    # A registry change (collision introduced, bypassing create/update
    # validation like the legacy data this repair exists for) changes the
    # fingerprint, so the repair must run again.
    state = agent_directory_service.load_state()
    for agent in state.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("agentId") or "").strip() == "agent-two":
            agent["directSessionId"] = "session-one"
    agent_directory_service.save_state(state)

    assert session_service._repair_agent_direct_session_collisions() is True
    assert load_calls["count"] > first_scan_loads
    assert agent_directory_service.get_agent("agent-one")["directSessionId"] == "session-one"
    repaired_two = agent_directory_service.get_agent("agent-two")
    assert repaired_two["directSessionId"] != "session-one"
    assert repaired_two["directSessionId"].startswith("session-")


def test_agent_directory_rejects_new_active_direct_session_collision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    first = agent_directory_service.create_agent_instance(
        display_name="First",
        direct_session_id="session-one",
        llm_bindings={"dialogue": {"modelId": "model-first"}},
    )

    try:
        agent_directory_service.create_agent_instance(
            display_name="Second",
            direct_session_id=first["directSessionId"],
            llm_bindings={"dialogue": {"modelId": "model-second"}},
        )
    except agent_directory_service.AgentDirectoryError as exc:
        assert "direct session is already bound" in str(exc)
    else:
        raise AssertionError("duplicate active directSessionId should be rejected")


def test_agent_directory_rejects_update_to_existing_active_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    first = agent_directory_service.create_agent_instance(
        display_name="First",
        direct_session_id="session-one",
        llm_bindings={"dialogue": {"modelId": "model-first"}},
    )
    second = agent_directory_service.create_agent_instance(
        display_name="Second",
        direct_session_id="session-two",
        llm_bindings={"dialogue": {"modelId": "model-second"}},
    )

    try:
        agent_directory_service.update_agent_instance(second["agentId"], direct_session_id=first["directSessionId"])
    except agent_directory_service.AgentDirectoryError as exc:
        assert "direct session is already bound" in str(exc)
    else:
        raise AssertionError("updating to a duplicate active directSessionId should be rejected")

    assert agent_directory_service.get_agent(second["agentId"])["directSessionId"] == "session-two"
