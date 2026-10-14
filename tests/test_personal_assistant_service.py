"""Personal assistant provisioning uses isolated native Agent/Session storage."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as service
from core.web.services import pet_activity_service, session_service
from core.web.services.session import directory_runtime
from core.web.services.session_archive_service import conversation_is_archived
from tests.test_financial_knowledge_service import finance_env as _finance_env

finance_env = _finance_env


@pytest.fixture
def personal_env(finance_env, monkeypatch):
    root = finance_env["root"]
    monkeypatch.setattr(session_service, "PROJECT_ROOT", root)
    monkeypatch.setattr(directory, "CONFIG_PATH", root / "developer-off.toml")
    # Never attach to the running operator's ConversationStore or model config.
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: None)
    monkeypatch.setattr(directory_runtime, "is_directory_store_open", lambda: False)
    monkeypatch.setattr(session_service, "default_session_llm_bindings", dict)
    return finance_env


def _profile_agents():
    return [
        row
        for row in directory.load_state()["agents"]
        if (row.get("metadata") or {}).get("personalAssistantProfile")
        == service.PROFILE
    ]


def _corrupt_agent(agent_id, **changes):
    """Simulate persisted corruption without asking native mutators to permit it."""
    state = directory.load_state()
    for row in state["agents"]:
        if row["agentId"] == agent_id:
            row.update(changes)
    directory.save_state(state)


def _forbid_write(*_args, **_kwargs):
    pytest.fail("a read-only entry attempted provisioning or repair")


def test_empty_get_is_read_only_and_does_not_adopt_same_name_agent(
    personal_env, monkeypatch
):
    directory.update_agent_instance(personal_env["owner"], display_name="个人助理")
    before = directory.load_state()
    monkeypatch.setattr(directory, "create_agent_instance", _forbid_write)
    monkeypatch.setattr(directory, "update_agent_instance", _forbid_write)
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", _forbid_write)
    assert service.get_personal_assistant() == {"assistant": None}
    assert directory.load_state() == before


def test_explicit_setup_uses_native_identity_and_restricted_policy_from_creation(
    personal_env, monkeypatch
):
    calls = []
    real_create = directory.create_agent_instance

    def inspect_create(**kwargs):
        calls.append(kwargs)
        return real_create(**kwargs)

    monkeypatch.setattr(directory, "create_agent_instance", inspect_create)
    monkeypatch.setattr(
        session_service,
        "default_session_llm_bindings",
        lambda: {"dialogue": {"modelId": "test-model"}},
    )
    result = service.create_personal_assistant()
    row = result["assistant"]
    assert row["setupStatus"] == "ready" and row["directSessionId"]
    assert row["profile"] == "personal_assistant_v1" and row["renderer"] == "whale"
    assert row["status"] == "active"
    assert len(calls) == 1
    assert calls[0]["role_key"] == service.ROLE == "personal_assistant"
    assert calls[0]["primary_mode"] == "general"
    assert calls[0]["prompt_template_id"] == "prompt-chat-default"
    assert calls[0]["llm_bindings"] == {"dialogue": {"modelId": "test-model"}}
    initial = calls[0]["initial_tool_policy"]
    assert initial["allowedTools"] and "*" not in initial["allowedTools"]
    assert not {
        "cli_tool",
        "shell_tool",
        "edit_file_tool",
        "write_file_tool",
    }.intersection(initial["allowedTools"])
    agent = directory.get_agent(row["agentId"])
    assert agent["toolPolicyId"] == "tool-" + row["agentId"]
    assert agent["personaProfile"]["identityNotes"]
    assert agent["taskProfile"]["constraints"]
    session = session_service.load_session_chat_state(
        personal_env["root"], row["directSessionId"]
    )
    assert session["agentId"] == row["agentId"]
    assert not conversation_is_archived(session)
    assert service.get_personal_assistant()["assistant"] == row


def test_repeated_setup_preserves_ready_user_policy_persona_and_name(personal_env):
    first = service.create_personal_assistant()["assistant"]
    directory.update_agent_instance(
        first["agentId"],
        display_name="我的助理",
        tool_policy={"allowedTools": [], "networkAccess": "none"},
        persona_profile={"identityNotes": "用户自己的身份说明"},
        task_profile={"constraints": "用户自己的边界"},
    )
    before = directory.get_agent(first["agentId"])
    service.get_personal_assistant()
    second = service.create_personal_assistant("不要改名")["assistant"]
    after = directory.get_agent(first["agentId"])
    assert second["agentId"] == first["agentId"]
    assert second["directSessionId"] == first["directSessionId"]
    for field in ("displayName", "toolPolicy", "personaProfile", "taskProfile"):
        assert after[field] == before[field]
    assert len(_profile_agents()) == 1


def test_concurrent_setup_creates_one_agent_and_one_session(personal_env):
    before_sessions = set(
        session_service.list_session_runtime_ids(personal_env["root"])
    )
    gate = Barrier(4)

    def create(_):
        gate.wait(timeout=10)
        return service.create_personal_assistant()["assistant"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(create, range(4)))
    assert len({row["agentId"] for row in rows}) == 1
    assert len({row["directSessionId"] for row in rows}) == 1
    assert rows[0]["directSessionId"]
    assert len(_profile_agents()) == 1
    after_sessions = set(session_service.list_session_runtime_ids(personal_env["root"]))
    assert after_sessions - before_sessions == {rows[0]["directSessionId"]}


def test_ready_get_never_repairs_or_rewrites_native_rows(personal_env, monkeypatch):
    row = service.create_personal_assistant()["assistant"]
    before_directory = directory.load_state()
    before_session = session_service.load_session_chat_state(
        personal_env["root"], row["directSessionId"]
    )
    for name in ("create_agent_instance", "update_agent_instance", "save_state"):
        monkeypatch.setattr(directory, name, _forbid_write)
    for name in (
        "ensure_agent_direct_session",
        "save_session_chat_state",
        "get_session_detail",
    ):
        monkeypatch.setattr(session_service, name, _forbid_write)
    assert service.get_personal_assistant()["assistant"] == row
    assert directory.load_state() == before_directory
    assert (
        session_service.load_session_chat_state(
            personal_env["root"], row["directSessionId"]
        )
        == before_session
    )


def test_personal_starters_only_override_canonical_profile_and_leave_ordinary_default(
    personal_env, monkeypatch
):
    from core.web.routes import sessions

    row = service.create_personal_assistant()["assistant"]
    assert service.composer_starters_for_agent(
        row["agentId"], row["directSessionId"]
    ) == list(service.COMPOSER_STARTERS)
    assert service.composer_starters_for_agent(row["agentId"], "foreign") is None
    assert service.composer_starters_for_agent(personal_env["owner"], "foreign") is None
    default = [{"heading": "coding", "command": "unchanged"}]
    monkeypatch.setattr(sessions, "get_composer_starter_commands", lambda _: default)
    assert (
        sessions._composer_starters_for_detail(
            {"id": "ordinary", "agentId": personal_env["owner"]}
        )
        == default
    )
    assert sessions._composer_starters_for_detail(
        {"id": row["directSessionId"], "agentId": row["agentId"]}
    ) == list(service.COMPOSER_STARTERS)


def test_setup_leaves_other_agent_and_shared_tool_policy_unchanged(personal_env):
    before_agent = directory.get_agent(personal_env["owner"])
    before_default = directory.load_state()["toolPolicies"][
        directory.DEFAULT_TOOL_POLICY_ID
    ]
    service.create_personal_assistant()
    assert directory.get_agent(personal_env["owner"]) == before_agent
    assert (
        directory.load_state()["toolPolicies"][directory.DEFAULT_TOOL_POLICY_ID]
        == before_default
    )


def test_partial_setup_read_does_not_repair_and_explicit_retry_reuses_agent(
    personal_env, monkeypatch
):
    original = session_service.ensure_agent_direct_session

    def fail(**_kwargs):
        raise RuntimeError("injected session setup failure")

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", fail)
    with pytest.raises(RuntimeError, match="injected session setup failure"):
        service.create_personal_assistant()
    before = directory.load_state()
    with monkeypatch.context() as read_guard:
        read_guard.setattr(directory, "update_agent_instance", _forbid_write)
        row = service.get_personal_assistant()["assistant"]
        assert row["setupStatus"] == "setup_required" and not row["directSessionId"]
        assert directory.load_state() == before
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", original)
    resumed = service.create_personal_assistant()["assistant"]
    assert resumed["agentId"] == row["agentId"] and resumed["setupStatus"] == "ready"
    assert resumed["directSessionId"] and len(_profile_agents()) == 1


def test_archived_profile_is_hidden_and_explicit_create_does_not_replace_it(
    personal_env,
):
    row = service.create_personal_assistant()["assistant"]
    directory.update_agent_instance(row["agentId"], status="archived")
    before = directory.load_state()
    assert service.get_personal_assistant() == {"assistant": None}
    with pytest.raises(directory.AgentStateConflictError):
        service.create_personal_assistant()
    assert directory.load_state() == before


@pytest.mark.parametrize("changes", [{"roleKey": "ordinary"}, {"primaryMode": "chat"}])
def test_profile_identity_tampering_fails_closed_without_repair(personal_env, changes):
    row = service.create_personal_assistant()["assistant"]
    _corrupt_agent(row["agentId"], **changes)
    before = directory.load_state()
    for entry in (service.get_personal_assistant, service.create_personal_assistant):
        with pytest.raises(directory.AgentStateConflictError):
            entry()
    assert directory.load_state() == before


def test_multiple_profile_matches_fail_closed(personal_env):
    service.create_personal_assistant()
    directory.create_agent_instance(
        display_name="重复助理",
        role_key=service.ROLE,
        primary_mode="general",
        metadata={"personalAssistantProfile": service.PROFILE},
    )
    before = directory.load_state()
    for entry in (service.get_personal_assistant, service.create_personal_assistant):
        with pytest.raises(directory.AgentStateConflictError):
            entry()
    assert directory.load_state() == before


def test_deleted_direct_session_is_only_repaired_on_explicit_create(
    personal_env, monkeypatch
):
    row = service.create_personal_assistant()["assistant"]
    session_service.delete_chat_session_lightweight(row["directSessionId"])
    before = directory.load_state()
    real_ensure = session_service.ensure_agent_direct_session
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", _forbid_write)
    missing = service.get_personal_assistant()["assistant"]
    assert (
        missing["setupStatus"] == "session_missing" and not missing["directSessionId"]
    )
    assert directory.load_state() == before
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", real_ensure)
    restored = service.create_personal_assistant()["assistant"]
    assert restored["agentId"] == row["agentId"] and restored["setupStatus"] == "ready"
    assert (
        restored["directSessionId"]
        and restored["directSessionId"] != row["directSessionId"]
    )


@pytest.mark.parametrize("corruption", ["foreign_agent", "archived"])
def test_invalid_session_ownership_or_archive_never_projects_ready_or_rebinds(
    personal_env, corruption
):
    row = service.create_personal_assistant()["assistant"]
    session = session_service.load_session_chat_state(
        personal_env["root"], row["directSessionId"]
    )
    if corruption == "foreign_agent":
        session["agentId"] = session["agent_id"] = personal_env["other"]
    else:
        session["archive_state"] = session["archiveState"] = {"status": "archived"}
    session_service.save_session_chat_state(
        personal_env["root"], row["directSessionId"], session
    )
    before = directory.load_state()
    shown = service.get_personal_assistant()["assistant"]
    assert shown["setupStatus"] == "session_missing" and not shown["directSessionId"]
    with pytest.raises(directory.AgentStateConflictError):
        service.create_personal_assistant()
    assert directory.load_state() == before
    assert (
        session_service.load_session_chat_state(
            personal_env["root"], row["directSessionId"]
        )
        == session
    )


@pytest.mark.parametrize("name", ["", "  ", "a\nb", "a" * 81])
def test_invalid_name_cannot_create_an_identity(personal_env, name):
    with pytest.raises(directory.AgentDirectoryError):
        service.create_personal_assistant(name)
    assert service.get_personal_assistant() == {"assistant": None}


def test_platform_overview_uses_native_activity_and_only_projects_safe_summaries(
    personal_env, monkeypatch
):
    sensitive = "private-payload-must-never-escape"
    agents = [
        {
            "agentId": "agent-one",
            "displayName": "工作助手",
            "status": "active",
            "personaProfile": {"identityNotes": sensitive},
            "privateMemory": sensitive,
        },
        {
            "agentId": "agent-two",
            "displayName": "生活助手",
            "status": "active",
            "toolPolicy": {"secret": sensitive},
            "prompt": sensitive,
        },
    ]
    sessions = [
        {
            "id": key,
            "agentId": "agent-one",
            "title": "任务 " + key,
            "status": status,
            "currentPhase": status,
            "messages": [sensitive],
            "toolArgs": {"secret": sensitive},
            "privateMemory": sensitive,
        }
        for key, status in (
            ("live", "ready"),
            ("approval", "tooling"),
            ("failed", "failed_runtime"),
            ("idle", "ready"),
        )
    ]
    calls = []
    real_activity = pet_activity_service.get_pet_activity

    def observe_activity(*args, **kwargs):
        calls.append(1)
        return real_activity(*args, **kwargs)

    monkeypatch.setattr(directory, "list_agents", lambda *args, **kwargs: agents)
    monkeypatch.setattr(
        session_service, "list_sessions", lambda *args, **kwargs: sessions
    )
    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: sessions)
    monkeypatch.setattr(pet_activity_service, "get_pet_activity", observe_activity)
    monkeypatch.setattr(
        pet_activity_service,
        "load_chat_turn_work_run_summary",
        lambda: {
            "activeItems": [
                {
                    "sessionId": "live",
                    "currentPhase": "reading",
                    "userMessage": sensitive,
                }
            ]
        },
    )
    monkeypatch.setattr(
        pet_activity_service,
        "list_tool_approval_requests",
        lambda session_id, status="": (
            [{"requestId": "approval-one", "toolArgs": sensitive}]
            if session_id == "approval" and status == "pending"
            else []
        ),
    )
    monkeypatch.setattr(directory, "update_agent_instance", _forbid_write)
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", _forbid_write)

    overview = service.get_platform_overview()

    assert calls == [1]
    assert set(overview) == {"generatedAt", "counts", "agents", "sessions", "attention"}
    assert overview["counts"] == {
        "agents": 2,
        "sessions": 4,
        "running": 1,
        "waiting": 1,
        "failed": 1,
    }
    assert {row["id"] for row in overview["sessions"]} == {
        "live",
        "approval",
        "failed",
        "idle",
    }
    assert all(
        set(row) == {"id", "displayName", "status"} for row in overview["agents"]
    )
    assert all(
        set(row) == {"id", "agentId", "title", "status", "currentPhase"}
        for row in overview["sessions"]
    )
    assert all(
        set(row) <= {"id", "kind", "title", "sessionId"}
        for row in overview["attention"]
    )
    assert sensitive not in str(overview)


def test_platform_overview_keeps_total_counts_when_summaries_are_bounded(
    personal_env, monkeypatch
):
    agents = [
        {"agentId": f"agent-{index}", "displayName": "助手", "status": "active"}
        for index in range(125)
    ]
    sessions = [
        {
            "id": f"session-{index}",
            "agentId": "agent-0",
            "title": "会话",
            "status": "ready",
        }
        for index in range(125)
    ]
    monkeypatch.setattr(directory, "list_agents", lambda **_kwargs: agents)
    monkeypatch.setattr(session_service, "list_sessions", lambda: sessions)
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {
            "generatedAt": "test",
            "sessions": [],
        },
    )
    overview = service.get_platform_overview()
    assert overview["counts"]["agents"] == overview["counts"]["sessions"] == 125
    assert len(overview["agents"]) == len(overview["sessions"]) == 100
