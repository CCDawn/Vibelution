"""Personal assistant provisioning uses isolated native Agent/Session storage."""

import threading
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Thread

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
    monkeypatch.setattr(service, "get_web_language", lambda: "zh")
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


def test_default_computer_tools_are_executable_but_network_denial_stays_custom(personal_env):
    from core.authorization.tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
    from core.authorization.tool_policy_models import TurnToolGrant
    from core.web.services import tool_catalog

    row = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    names = {"personal_assistant_computer_observe_tool", "personal_assistant_computer_action_tool"}
    descriptors = [tool_catalog.build_tool_descriptor(name, args_schema={}) for name in service.TOOLS]
    grant = TurnToolGrant(turn_id="computer-turn", source="session",
        allowed_capabilities=tuple({cap for item in descriptors for cap in item.capabilities}),
        denied_tools=(), approval_mode="on_request")

    def decision(policy):
        return evaluate_tool_policy(agent_id=row["agentId"],
            policy=normalize_legacy_tool_policy(policy, registered_tool_names=service.TOOLS, policy_id=agent["toolPolicyId"]),
            grant=grant, descriptors=descriptors, registry_version=1, registry_fingerprint="test")

    assert agent["toolPolicy"]["networkAccess"] == "restricted"
    assert names <= set(decision(agent["toolPolicy"]).executable_tools)
    # An operator's deliberate network restriction must not become a legacy
    # provisioning snapshot and be silently broadened by setup retries.
    directory.update_agent_instance(row["agentId"], tool_policy={**agent["toolPolicy"], "networkAccess": "none"})
    restricted = directory.get_agent(row["agentId"])["toolPolicy"]
    service.create_personal_assistant()
    assert directory.get_agent(row["agentId"])["toolPolicy"] == restricted
    assert "personal_assistant_computer_observe_tool" not in decision(restricted).executable_tools


@pytest.mark.parametrize("custom_task", [False, True])
def test_pre_computer_upgrade_refreshes_only_untouched_normalized_task_profile(personal_env, custom_task):
    row = service.create_personal_assistant()["assistant"]
    legacy_task = {**service._PRE_MESSAGES_TASK, "constraints": service._LEGACY_DESKTOP_CONSTRAINTS}
    if custom_task:
        legacy_task["mission"] = "用户自己的任务"
    directory.update_agent_instance(row["agentId"], task_profile=legacy_task,
        tool_policy={**service.PRIVATE_V2_POLICY, "allowedTools": list(service._PRE_COMPUTER_TOOLS),
                     "preferredTools": list(service._PRE_COMPUTER_TOOLS)})
    stored_task = directory.get_agent(row["agentId"])["taskProfile"]
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    service.create_personal_assistant()
    after = directory.get_agent(row["agentId"])
    assert after["taskProfile"] == (stored_task if custom_task else directory.normalize_task_profile(service.TASK))
    assert after["toolPolicy"]["allowedTools"] == list(service.TOOLS)


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


def test_personal_starters_follow_language_without_changing_identity(personal_env, monkeypatch):
    row = service.create_personal_assistant(display_name="我的助理 My assistant")["assistant"]
    before = directory.load_state()
    monkeypatch.setattr(service, "get_web_language", lambda: "en", raising=False)
    starters = service.composer_starters_for_agent(row["agentId"], row["directSessionId"])
    assert starters[0]["heading"] == "Delegate & track"
    assert "Delegate" in starters[0]["command"]
    starters[0]["heading"] = "edited"
    assert service.composer_starters_for_agent(row["agentId"], row["directSessionId"])[0]["heading"] == "Delegate & track"
    assert service.composer_starters_for_agent(personal_env["owner"], "foreign") is None
    monkeypatch.setattr(service, "get_web_language", lambda: "zh", raising=False)
    assert service.composer_starters_for_agent(row["agentId"], row["directSessionId"]) == list(service.COMPOSER_STARTERS)
    assert directory.load_state() == before


def test_personal_validation_errors_follow_current_language(personal_env, monkeypatch):
    monkeypatch.setattr(service, "get_web_language", lambda: "en", raising=False)
    with pytest.raises(directory.AgentDirectoryError, match="single-line name"):
        service.create_personal_assistant(display_name="")
    with pytest.raises(ValueError, match="non-negative integer"):
        service.get_platform_overview(offset=-1)
    with pytest.raises(directory.AgentDirectoryError, match="has not been created"):
        service.update_personal_assistant_settings(display_name="test")
    service.create_personal_assistant()
    with pytest.raises(directory.AgentDirectoryError, match="Unsupported appearance"):
        service.update_personal_assistant_settings(preferences={"characterId": "invalid"})
    with pytest.raises(directory.AgentDirectoryError, match="Select a model"):
        service.update_personal_assistant_model(model_id="")
    monkeypatch.setattr(service, "get_web_language", lambda: "zh", raising=False)
    with pytest.raises(directory.AgentDirectoryError, match="不支持的外观"):
        service.update_personal_assistant_settings(preferences={"characterId": "invalid"})


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


def test_profile_lookup_hydrates_only_assistant(personal_env, monkeypatch):
    row = service.create_personal_assistant()["assistant"]
    hydrated = []
    real_project = directory._agent_to_api

    def project(agent, **kwargs):
        hydrated.append(agent["agentId"])
        return real_project(agent, **kwargs)

    monkeypatch.setattr(directory, "_agent_to_api", project)
    assert service.get_personal_assistant()["assistant"] == row
    assert hydrated == [row["agentId"]]


def test_duplicate_profile_rejected_before_hydration(personal_env, monkeypatch):
    service.create_personal_assistant()
    duplicate = directory.create_agent_instance(
        display_name="Duplicate", role_key=service.ROLE, primary_mode="general",
        metadata={"personalAssistantProfile": service.PROFILE},
    )
    directory.update_agent_instance(duplicate["agentId"], status="archived")
    monkeypatch.setattr(directory, "_agent_to_api", _forbid_write)
    with pytest.raises(directory.AgentStateConflictError):
        service.get_personal_assistant()


@pytest.mark.parametrize("change", ["profile", "role", "mode", "missing", "archived"])
def test_profile_lookup_rechecks_full_identity(personal_env, monkeypatch, change):
    row = service.create_personal_assistant()["assistant"]
    real_get = directory.get_agent

    def changed_get(agent_id, **kwargs):
        assert agent_id == row["agentId"] and kwargs == {"include_archived": True}
        agent = real_get(agent_id, **kwargs)
        if change == "missing":
            return None
        if change == "profile":
            agent["metadata"] = {**agent["metadata"], "personalAssistantProfile": "other"}
        elif change == "role":
            agent["roleKey"] = "ordinary"
        elif change == "mode":
            agent["primaryMode"] = "chat"
        else:
            agent["status"] = "archived"
        return agent

    monkeypatch.setattr(directory, "get_agent", changed_get)
    if change == "archived":
        assert service.get_personal_assistant() == {"assistant": None}
    else:
        with pytest.raises(directory.AgentStateConflictError):
            service.get_personal_assistant()


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
    monkeypatch.setattr(session_service, "load_chat_turn_work_run_summary", lambda: pet_activity_service.load_chat_turn_work_run_summary())
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
    assert set(overview) == {"generatedAt", "counts", "agents", "sessions", "attention", "pagination"}
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
        set(row) == {"id", "agentId", "title", "status", "currentPhase", "turnId", "lastTurnStatus", "terminalReason", "activeTurnId", "lastTurnTerminalTurnId"}
        for row in overview["sessions"]
    )
    assert all(
        set(row) <= {"id", "kind", "title", "sessionId"}
        for row in overview["attention"]
    )
    assert sensitive not in str(overview)


def test_overview_counts_match_execution_groups_without_inventing_unknown_owners(monkeypatch):
    monkeypatch.setattr(directory, "list_agents", lambda **_: [])
    rows = [{"id": name, "status": "ready", "currentPhase": "ready", "terminalReason": "success"}
            for name in ("paused", "stopping", "blocked", "unknown")]
    monkeypatch.setattr(session_service, "list_sessions", lambda: rows)
    monkeypatch.setattr(session_service, "current_session_turn_id", lambda _: "")
    monkeypatch.setattr(session_service, "load_chat_turn_work_run_summary", lambda: {"activeItems": [
        {"sessionId": name, "runId": name, "status": status, "currentPhase": "thinking"}
        for name, status in (("paused", "paused"), ("stopping", "stopping"), ("blocked", "blocked"), ("unknown", "future_state"))
    ]})
    monkeypatch.setattr(pet_activity_service, "get_pet_activity", lambda: {"sessions": [], "generatedAt": ""})
    public = service._build_platform_overview_snapshot()["public"]
    assert public["counts"] == {"agents": 0, "sessions": 4, "running": 1, "waiting": 1, "failed": 0}
    states = {row["id"]: row for row in public["sessions"]}
    assert states["paused"]["status"] == "paused"
    for name in ("blocked", "unknown"):
        assert states[name]["status"] == "unknown"
        assert states[name]["activeTurnId"] == ""


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
    assert overview["pagination"]["nextOffset"] == 100
    remaining = service.get_platform_overview(offset=100)
    assert len(remaining["agents"]) == len(remaining["sessions"]) == 25
    assert remaining["pagination"]["nextOffset"] is None
    assert overview["pagination"]["revision"] == remaining["pagination"]["revision"]
    assert not {row["id"] for row in overview["sessions"]}.intersection(
        row["id"] for row in remaining["sessions"]
    )
    sessions[-1]["title"] = "另一个公开状态"
    # Revision tracks the next projection; the poll memo bounds how long a
    # change can stay invisible.
    service._reset_platform_overview_cache_for_tests()
    assert service.get_platform_overview(offset=100)["pagination"]["revision"] != overview["pagination"]["revision"]


def test_platform_overview_reuses_projection_until_the_poll_ttl_expires(
    personal_env, monkeypatch
):
    scans = []

    def collect(name):
        scans.append(name)
        return []

    monkeypatch.setattr(directory, "list_agents", lambda **_kwargs: collect("agents"))
    monkeypatch.setattr(session_service, "list_sessions", lambda: collect("sessions"))
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {
            "generatedAt": "test",
            "sessions": [],
        },
    )

    first = service.get_platform_overview()
    second = service.get_platform_overview()
    assert scans == ["agents", "sessions"]
    assert second == first
    assert second is not first

    with service._PLATFORM_OVERVIEW_CACHE_LOCK:
        service._PLATFORM_OVERVIEW_CACHE["expires_at"] = 0.0
    service.get_platform_overview()
    assert scans == ["agents", "sessions", "agents", "sessions"]


def test_created_assistant_can_execute_personal_memory_tools(personal_env):
    from core.authorization.tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
    from core.authorization.tool_policy_models import TurnToolGrant
    from core.web.services import tool_catalog

    assistant = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(assistant["agentId"])
    names = ("append_personal_memory_tool", "supersede_personal_memory_tool")
    search_and_compact = ("search_agent_private_memory_tool", "compress_context_tool")
    assert set(search_and_compact) <= set(service.TOOLS)
    assert set(search_and_compact) <= set(agent["toolPolicy"]["allowedTools"])
    descriptors = [tool_catalog.build_tool_descriptor(name, args_schema={}) for name in service.TOOLS]
    policy = normalize_legacy_tool_policy(agent["toolPolicy"], registered_tool_names=service.TOOLS, policy_id=agent["toolPolicyId"])
    decision = evaluate_tool_policy(agent_id=agent["agentId"], policy=policy,
        grant=TurnToolGrant(turn_id="memory-turn", source="session", allowed_capabilities=tuple({cap for row in descriptors for cap in row.capabilities}), denied_tools=(), approval_mode="on_request"),
        descriptors=descriptors, registry_version=1, registry_fingerprint="test")
    assert set(names) <= set(decision.executable_tools)
    assert set(search_and_compact) <= set(decision.executable_tools)
    assert agent["toolPolicy"]["writeScopes"] == ["private"]


def test_legacy_default_upgrade_is_explicit_and_preserves_user_profiles(personal_env):
    row = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    legacy = directory.normalize_tool_policy(service.LEGACY_POLICY, agent["toolPolicyId"])
    legacy["policyVersion"] = 2
    directory.update_agent_instance(row["agentId"], persona_profile={"identityNotes": "自己的身份"}, task_profile={"constraints": "自己的约束"})
    _corrupt_agent(row["agentId"], toolPolicy=legacy)
    state = directory.load_state()
    state["toolPolicies"][agent["toolPolicyId"]] = legacy
    directory.save_state(state)
    actual = directory.get_agent(row["agentId"])
    assert actual["toolPolicy"] == legacy
    assert actual["createdBy"] == "user_personal_assistant"
    before = directory.load_state()
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    assert directory.load_state() == before
    assert service.create_personal_assistant()["assistant"]["setupStatus"] == "ready"
    repaired = directory.get_agent(row["agentId"])
    assert repaired["toolPolicy"]["writeScopes"] == ["private"]
    assert repaired["personaProfile"]["identityNotes"] == "自己的身份"
    assert repaired["taskProfile"]["constraints"] == "自己的约束"
    after = directory.load_state()
    service.create_personal_assistant()
    assert directory.load_state() == after


@pytest.mark.parametrize("changes", [{"policyVersion": 3}, {"maxCallsPerTurn": 5}, {"allowedTools": [], "preferredTools": []}, {"perToolRules": {"personal_assistant_manage_tool": {"approval": "always"}}}])
def test_legacy_upgrade_preserves_custom_and_resaved_policies(personal_env, changes):
    row = service.create_personal_assistant()["assistant"]
    policy = {**directory.get_agent(row["agentId"])["toolPolicy"], "writeScopes": [], "policyVersion": 2, **changes}
    _corrupt_agent(row["agentId"], toolPolicy=policy)
    before = directory.get_agent(row["agentId"])["toolPolicy"]
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "ready"
    service.create_personal_assistant()
    assert directory.get_agent(row["agentId"])["toolPolicy"] == before


def test_resuming_pending_setup_preserves_user_policy_and_profiles(personal_env, monkeypatch):
    original = session_service.ensure_agent_direct_session
    def fail(**_kwargs):
        raise RuntimeError("injected setup failure")

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", fail)
    with pytest.raises(RuntimeError):
        service.create_personal_assistant()
    row = service.get_personal_assistant()["assistant"]
    directory.update_agent_instance(row["agentId"], tool_policy={"allowedTools": [], "preferredTools": [], "networkAccess": "none"}, persona_profile={"identityNotes": "用户设置"})
    before = directory.get_agent(row["agentId"])
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", original)
    assert service.create_personal_assistant()["assistant"]["setupStatus"] == "ready"
    after = directory.get_agent(row["agentId"])
    assert after["toolPolicy"] == before["toolPolicy"]
    assert after["personaProfile"] == before["personaProfile"]


def test_config_knob_change_refreshes_existing_snapshot_budget(personal_env, monkeypatch):
    row = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    assert agent["toolPolicy"]["maxCallsPerTurn"] == service.DEFAULT_MAX_CALLS_PER_TURN
    _set_budget_knob(monkeypatch, 32)
    before = directory.load_state()
    # Read path flags the stale snapshot without repairing it.
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    assert directory.load_state() == before
    # Explicit provisioning delivers the new budget and stays idempotent.
    assert service.create_personal_assistant()["assistant"]["setupStatus"] == "ready"
    assert directory.get_agent(row["agentId"])["toolPolicy"]["maxCallsPerTurn"] == 32
    after = directory.load_state()
    service.create_personal_assistant()
    assert directory.load_state() == after


def test_stale_budget_snapshot_upgrades_after_each_reprovision(personal_env, monkeypatch):
    row = service.create_personal_assistant()["assistant"]
    for knob in (32, 8):
        _set_budget_knob(monkeypatch, knob)
        assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
        service.create_personal_assistant()
        assert (
            directory.get_agent(row["agentId"])["toolPolicy"]["maxCallsPerTurn"]
            == knob
        )


def test_pre_toolset_snapshot_upgrades_to_search_and_compress_tools(personal_env):
    row = service.create_personal_assistant()["assistant"]
    agent_id = row["agentId"]
    # Frozen historical generation, not today's toolset minus selected names.
    old_tools = service._LEGACY_TOOLS + service._DESKTOP_TOOLS
    legacy = directory.normalize_tool_policy(
        {
            **service.PRIVATE_V2_POLICY,
            "allowedTools": list(old_tools),
            "preferredTools": list(old_tools),
            "maxCallsPerTurn": service.DEFAULT_MAX_CALLS_PER_TURN,
        },
        "tool-" + agent_id,
    )
    legacy["policyVersion"] = 2
    _corrupt_agent(agent_id, toolPolicy=legacy)
    state = directory.load_state()
    state["toolPolicies"]["tool-" + agent_id] = legacy
    directory.save_state(state)
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    assert service.create_personal_assistant()["assistant"]["setupStatus"] == "ready"
    upgraded = directory.get_agent(agent_id)["toolPolicy"]
    assert upgraded["allowedTools"] == list(service.TOOLS)
    assert {
        "search_agent_private_memory_tool",
        "compress_context_tool",
    } <= set(upgraded["allowedTools"])
    assert upgraded["writeScopes"] == ["private"]
    # Toolset upgrade keeps the live budget rather than resetting it.
    assert upgraded["maxCallsPerTurn"] == service.DEFAULT_MAX_CALLS_PER_TURN


def test_agent_message_generation_is_provisioned_and_described(personal_env):
    from core.web.services import tool_catalog

    assert service.TOOLS == (*service._PRE_MESSAGES_TOOLS, "agent_message_tool", "personal_assistant_action_tool")
    row = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    assert "agent_message_tool" in agent["toolPolicy"]["allowedTools"]
    # The cross-agent collaboration tool must keep a catalog contract entry so
    # descriptor building for the whole toolset stays possible.
    descriptor = tool_catalog.build_tool_descriptor("agent_message_tool", args_schema={})
    assert descriptor.capabilities


def test_pre_messages_snapshot_upgrades_to_agent_message_tool(personal_env):
    row = service.create_personal_assistant()["assistant"]
    agent_id = row["agentId"]
    # Frozen restricted-networking default from before the agent_message_tool
    # generation, exactly as the previous current_policy wrote it.
    legacy = directory.normalize_tool_policy(
        {
            **service.PRIVATE_V2_POLICY,
            "networkAccess": "restricted",
            "allowedTools": list(service._PRE_MESSAGES_TOOLS),
            "preferredTools": list(service._PRE_MESSAGES_TOOLS),
            "maxCallsPerTurn": service.DEFAULT_MAX_CALLS_PER_TURN,
        },
        "tool-" + agent_id,
    )
    legacy["policyVersion"] = 2
    _corrupt_agent(agent_id, toolPolicy=legacy)
    state = directory.load_state()
    state["toolPolicies"]["tool-" + agent_id] = legacy
    directory.save_state(state)
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    assert service.create_personal_assistant()["assistant"]["setupStatus"] == "ready"
    upgraded = directory.get_agent(agent_id)["toolPolicy"]
    assert upgraded["allowedTools"] == list(service.TOOLS)
    assert "agent_message_tool" in upgraded["allowedTools"]
    assert "agent_message_tool" not in service._PRE_MESSAGES_TOOLS


def test_current_policy_exempts_only_agent_message_tool_from_approval(personal_env):
    from core.authorization.tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
    from core.authorization.tool_policy_models import TurnToolGrant
    from core.web.services import tool_catalog

    policy = service.current_policy()
    assert policy["approvalOverrides"] == {"agent_message_tool": "never"}
    row = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    assert agent["toolPolicy"]["approvalOverrides"] == {"agent_message_tool": "never"}
    descriptors = [tool_catalog.build_tool_descriptor(name, args_schema={}) for name in service.TOOLS]
    decision = evaluate_tool_policy(
        agent_id=row["agentId"],
        policy=normalize_legacy_tool_policy(
            agent["toolPolicy"],
            registered_tool_names=service.TOOLS,
            policy_id=agent["toolPolicyId"],
        ),
        grant=TurnToolGrant(
            turn_id="dispatch-turn",
            source="session",
            allowed_capabilities=tuple({cap for item in descriptors for cap in item.capabilities}),
            denied_tools=(),
            approval_mode="on_request",
        ),
        descriptors=descriptors,
        registry_version=1,
        registry_fingerprint="test",
    )
    modes = {name: mode for name, mode, _risk in decision.approval_requirements}
    # Dispatch sends immediately instead of stalling on a per-send approval.
    assert modes["agent_message_tool"] == "never"
    assert "agent_message_tool" in decision.executable_tools
    # Governed mutations keep their per-call approval semantics.
    assert modes["personal_assistant_manage_tool"] == "always"


def test_pre_approval_snapshot_upgrades_to_override_policy_and_stays_idempotent(personal_env):
    row = service.create_personal_assistant()["assistant"]
    agent_id = row["agentId"]
    # The first agent_message_tool generation provisioned this exact toolset
    # before approvalOverrides existed; that stored shape must still upgrade.
    directory.update_agent_instance(
        agent_id,
        tool_policy={
            **service.PRIVATE_V2_POLICY,
            "networkAccess": "restricted",
            "allowedTools": list(service.TOOLS),
            "preferredTools": list(service.TOOLS),
        },
    )
    before = directory.get_agent(agent_id)["toolPolicy"]
    assert "approvalOverrides" not in before
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    assert service.create_personal_assistant()["assistant"]["setupStatus"] == "ready"
    upgraded = directory.get_agent(agent_id)["toolPolicy"]
    assert upgraded["approvalOverrides"] == {"agent_message_tool": "never"}
    assert upgraded["allowedTools"] == list(service.TOOLS)
    # Upgrading is idempotent: a second reprovision writes nothing new.
    after = directory.load_state()
    service.create_personal_assistant()
    assert directory.load_state() == after


@pytest.mark.parametrize("custom_task", [False, True])
def test_pre_messages_task_upgrades_to_current_generation_task(personal_env, custom_task):
    row = service.create_personal_assistant()["assistant"]
    legacy_task = dict(service._PRE_MESSAGES_TASK)
    if custom_task:
        legacy_task["mission"] = "用户自己的任务"
    directory.update_agent_instance(
        row["agentId"],
        task_profile=legacy_task,
        tool_policy={
            **service.PRIVATE_V2_POLICY,
            "networkAccess": "restricted",
            "allowedTools": list(service._PRE_MESSAGES_TOOLS),
            "preferredTools": list(service._PRE_MESSAGES_TOOLS),
        },
    )
    stored_task = directory.get_agent(row["agentId"])["taskProfile"]
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    service.create_personal_assistant()
    after = directory.get_agent(row["agentId"])
    assert after["taskProfile"] == (
        stored_task if custom_task else directory.normalize_task_profile(service.TASK)
    )
    assert after["toolPolicy"]["allowedTools"] == list(service.TOOLS)


def test_default_persona_upgrades_on_reprovision_and_user_persona_stays(personal_env):
    row = service.create_personal_assistant()["assistant"]
    directory.update_agent_instance(
        row["agentId"], persona_profile=dict(service._PRE_MESSAGES_PERSONA)
    )
    assert (
        directory.get_agent(row["agentId"])["personaProfile"]
        == service._PERSONA_HISTORY_DEFAULTS[0]
    )
    service.create_personal_assistant()
    assert (
        directory.get_agent(row["agentId"])["personaProfile"]
        == directory.normalize_persona_profile(service.PERSONA)
    )
    # Refresh is idempotent: the upgraded persona is not a historical default.
    after = directory.load_state()
    service.create_personal_assistant()
    assert directory.load_state() == after
    # A user-authored persona never matches the defaults and stays intact.
    directory.update_agent_instance(
        row["agentId"], persona_profile={"identityNotes": "我的自定义身份"}
    )
    service.create_personal_assistant()
    assert directory.get_agent(row["agentId"])["personaProfile"] == (
        directory.normalize_persona_profile({"identityNotes": "我的自定义身份"})
    )


# --- Settings surface: config knob, preferences, renderer, model binding ---


class _WebChatKnob:
    def __init__(self, value):
        self.personal_assistant_max_calls_per_turn = value


class _ConfigStub:
    def __init__(self, value):
        self.web_chat = _WebChatKnob(value)


def _set_budget_knob(monkeypatch, value):
    import config.settings as settings_module

    monkeypatch.setattr(
        settings_module, "get_config", lambda *args, **kwargs: _ConfigStub(value)
    )


def test_policy_budget_reads_config_knob_with_default_and_fallback(monkeypatch):
    assert service.current_policy()["maxCallsPerTurn"] == 16
    _set_budget_knob(monkeypatch, 24)
    assert service.current_policy()["maxCallsPerTurn"] == 24

    import config.settings as settings_module

    def broken(*_args, **_kwargs):
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(settings_module, "get_config", broken)
    assert service.current_policy()["maxCallsPerTurn"] == 16


def test_provisioned_policy_uses_configured_budget(personal_env, monkeypatch):
    _set_budget_knob(monkeypatch, 32)
    row = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    assert agent["toolPolicy"]["maxCallsPerTurn"] == 32
    assert service.LEGACY_POLICY["maxCallsPerTurn"] == 8


def _created_assistant(personal_env, monkeypatch, model_id="assistant-model"):
    monkeypatch.setattr(
        session_service,
        "default_session_llm_bindings",
        lambda: {"dialogue": {"modelId": model_id}},
    )
    return service.create_personal_assistant()["assistant"]


def _llm_options(monkeypatch, choices, current="assistant-model"):
    monkeypatch.setattr(
        session_service,
        "get_session_llm_options",
        lambda session_id: {
            "sessionId": session_id,
            "currentModelId": current,
            "choices": choices,
            "model": None,
        },
    )


def test_settings_read_projects_defaults_without_provisioning(personal_env, monkeypatch):
    row = _created_assistant(personal_env, monkeypatch)
    _llm_options(
        monkeypatch,
        [
            {"modelId": "assistant-model", "label": "助理模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": True, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
            {"modelId": "other-model", "label": "其他", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": False, "providerHealthy": False, "missingApiKey": True,
             "availability": "missing"},
        ],
    )
    payload = service.get_personal_assistant_settings()["settings"]
    assert payload["displayName"] == "个人助理"
    assert payload["preferences"] == {
        "characterId": "dafeiyu", "showStatus": True, "showTitles": True,
        "showCompletion": True, "idleMessage": "",
    }
    assert payload["preferencesConfigured"] is False
    assert payload["model"]["currentModelId"] == "assistant-model"
    assert [choice["modelId"] for choice in payload["model"]["choices"]] == [
        "assistant-model",
        "other-model",
    ]
    assert payload["model"]["choices"][1]["providerHealthy"] is False


def test_settings_update_renames_and_persists_preferences(personal_env, monkeypatch):
    row = _created_assistant(personal_env, monkeypatch)
    result = service.update_personal_assistant_settings(
        display_name="小洛管家",
        preferences={"characterId": "xiaoluo", "showTitles": False},
    )["settings"]
    assert result["displayName"] == "小洛管家"
    assert result["preferences"]["characterId"] == "xiaoluo"
    assert result["preferences"]["showTitles"] is False
    assert result["preferences"]["showStatus"] is True
    assert result["preferencesConfigured"] is True
    agent = directory.get_agent(row["agentId"])
    assert agent["metadata"][service.PREFERENCES_METADATA_KEY] == result["preferences"]
    projected = service.get_personal_assistant()["assistant"]
    assert projected["renderer"] == "xiaoluo"
    assert projected["displayName"] == "小洛管家"


def test_settings_update_rejects_invalid_payloads(personal_env, monkeypatch):
    _created_assistant(personal_env, monkeypatch)
    before = directory.load_state()
    for name in ["", "  ", "a\nb", "a" * 81]:
        with pytest.raises(directory.AgentDirectoryError):
            service.update_personal_assistant_settings(display_name=name)
    with pytest.raises(directory.AgentDirectoryError):
        service.update_personal_assistant_settings(preferences={"unknown": True})
    with pytest.raises(directory.AgentDirectoryError):
        service.update_personal_assistant_settings(
            preferences={"characterId": "other"}
        )
    assert directory.load_state() == before


def test_settings_update_requires_active_assistant(personal_env, monkeypatch):
    with pytest.raises(directory.AgentDirectoryError):
        service.update_personal_assistant_settings(display_name="改名")
    row = _created_assistant(personal_env, monkeypatch)
    directory.update_agent_instance(row["agentId"], status="archived")
    with pytest.raises(directory.AgentStateConflictError):
        service.update_personal_assistant_settings(display_name="改名")


def test_settings_update_fails_closed_when_archive_races_the_write(
    personal_env, monkeypatch
):
    row = _created_assistant(personal_env, monkeypatch)
    real_get_agent = directory.get_agent

    def archived_after_write(agent_id, *args, **kwargs):
        agent = real_get_agent(agent_id, *args, **kwargs)
        if kwargs.get("include_archived"):
            # Simulate Agent management archiving right after our write.
            return {**agent, "status": "archived"}
        return agent

    monkeypatch.setattr(directory, "get_agent", archived_after_write)
    with pytest.raises(directory.AgentStateConflictError):
        service.update_personal_assistant_settings(display_name="改名")


def test_model_update_fails_closed_when_archive_races_the_write(
    personal_env, monkeypatch
):
    row = _created_assistant(personal_env, monkeypatch)
    _llm_options(
        monkeypatch,
        [
            {"modelId": "other-model", "label": "其他", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": False, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
        ],
    )
    real_get_agent = directory.get_agent

    def archived_after_write(agent_id, *args, **kwargs):
        agent = real_get_agent(agent_id, *args, **kwargs)
        if kwargs.get("include_archived"):
            return {**agent, "status": "archived"}
        return agent

    monkeypatch.setattr(directory, "get_agent", archived_after_write)
    with pytest.raises(directory.AgentStateConflictError):
        service.update_personal_assistant_model("other-model")


def test_budget_config_fallback_logs_warning(monkeypatch, caplog):
    import config.settings as settings_module

    def broken(*_args, **_kwargs):
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(settings_module, "get_config", broken)
    with caplog.at_level("WARNING", logger="core.web.services.personal_assistant_service"):
        assert service.current_policy()["maxCallsPerTurn"] == 16
    assert any("personal_assistant_max_calls_per_turn" in record.message for record in caplog.records)


def test_preferences_corruption_falls_back_to_safe_defaults(personal_env, monkeypatch):
    row = _created_assistant(personal_env, monkeypatch)
    _corrupt_agent(
        row["agentId"],
        metadata={
            **directory.get_agent(row["agentId"])["metadata"],
            service.PREFERENCES_METADATA_KEY: {"characterId": "hacker", "idleMessage": "x" * 200},
        },
    )
    payload = service.get_personal_assistant_settings()["settings"]
    assert payload["preferences"] == {
        "characterId": "dafeiyu", "showStatus": True, "showTitles": True,
        "showCompletion": True, "idleMessage": "x" * 48,
    }
    assert service.get_personal_assistant()["assistant"]["renderer"] == "whale"


def test_model_update_follows_whitelist_and_rebinds_dialogue(personal_env, monkeypatch):
    row = _created_assistant(personal_env, monkeypatch)
    _llm_options(
        monkeypatch,
        [
            {"modelId": "assistant-model", "label": "助理模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": True, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
            {"modelId": "whale-xl", "label": "大模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": False, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
        ],
    )
    result = service.update_personal_assistant_model("whale-xl")["model"]
    assert result["currentModelId"] == "whale-xl"
    assert directory.get_agent(row["agentId"])["llmBindings"] == {
        "dialogue": {"modelId": "whale-xl"}
    }
    before = directory.load_state()
    with pytest.raises(directory.AgentDirectoryError):
        service.update_personal_assistant_model("not-in-whitelist")
    with pytest.raises(directory.AgentDirectoryError):
        service.update_personal_assistant_model("  ")
    assert directory.load_state() == before


@pytest.mark.parametrize(
    "eligibility",
    [
        {"runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": False}}},
        {"runtimeSelectable": False, "slotCompatibility": {"dialogue": {"allowed": True}}},
        {"slotCompatibility": {"dialogue": {"allowed": True}}},
        {"runtimeSelectable": True},
        {"runtimeSelectable": True, "slotCompatibility": {"dialogue": {}}},
    ],
    ids=["embedding", "discovered-only", "missing-runtime", "missing-slots", "missing-allowed"],
)
def test_model_update_rejects_ineligible_choices_without_writing(
    personal_env, monkeypatch, eligibility
):
    _created_assistant(personal_env, monkeypatch)
    _llm_options(
        monkeypatch,
        [{
            "modelId": "ineligible-model", "providerHealthy": True,
            "missingApiKey": False, "availability": "available", **eligibility,
        }],
    )
    writes = []
    monkeypatch.setattr(directory, "update_agent_instance", lambda *args, **kwargs: writes.append(kwargs))
    before = directory.load_state()
    with pytest.raises(directory.AgentDirectoryError, match="不在可用模型列表"):
        service.update_personal_assistant_model("ineligible-model")
    assert writes == []
    assert directory.load_state() == before
    assert service.get_personal_assistant_settings()["settings"]["model"]["choices"] == []


def test_model_update_requires_owned_ready_session(personal_env, monkeypatch):
    row = _created_assistant(personal_env, monkeypatch)
    session_service.delete_chat_session_lightweight(row["directSessionId"])
    with pytest.raises(directory.AgentStateConflictError):
        service.update_personal_assistant_model("assistant-model")


def _profile_lock_is_held() -> bool:
    """Probe the profile RLock from another thread; True means NOT held."""
    observed = []

    def probe():
        acquired = service._LOCK.acquire(blocking=False)
        observed.append(acquired)
        if acquired:
            service._LOCK.release()

    thread = Thread(target=probe)
    thread.start()
    thread.join(timeout=5)
    return bool(observed[0]) if observed else True


def test_settings_and_model_writes_hold_profile_lock(personal_env, monkeypatch):
    row = _created_assistant(personal_env, monkeypatch)
    _llm_options(
        monkeypatch,
        [
            {"modelId": "assistant-model", "label": "助理模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": True, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
            {"modelId": "whale-xl", "label": "大模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": False, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
        ],
    )
    observations = []
    original_update = directory.update_agent_instance

    def probe_update(agent_id, **kwargs):
        observations.append(_profile_lock_is_held())
        return original_update(agent_id, **kwargs)

    monkeypatch.setattr(directory, "update_agent_instance", probe_update)
    service.update_personal_assistant_settings(preferences={"idleMessage": "同步中"})
    service.update_personal_assistant_model("whale-xl")
    assert observations == [False, False]
    agent = directory.get_agent(row["agentId"])
    assert agent["metadata"][service.PREFERENCES_METADATA_KEY]["idleMessage"] == "同步中"
    assert agent["llmBindings"] == {"dialogue": {"modelId": "whale-xl"}}


def test_concurrent_patches_do_not_lose_preference_or_model_updates(
    personal_env, monkeypatch
):
    row = _created_assistant(personal_env, monkeypatch)
    _llm_options(
        monkeypatch,
        [
            {"modelId": "assistant-model", "label": "助理模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": True, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
            {"modelId": "whale-xl", "label": "大模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": False, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
        ],
    )
    gate = Barrier(3)
    failures = []

    def run(worker):
        try:
            gate.wait(timeout=10)
            worker()
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            failures.append(exc)

    def patch_idle_message():
        for index in range(4):
            service.update_personal_assistant_settings(
                preferences={"idleMessage": f"p{index}"}
            )

    def patch_appearance():
        for index in range(4):
            service.update_personal_assistant_settings(
                preferences={"characterId": "xiaoluo", "showTitles": index % 2 == 0}
            )

    def flip_model():
        for index in range(4):
            service.update_personal_assistant_model(
                "whale-xl" if index % 2 == 0 else "assistant-model"
            )

    threads = [
        Thread(target=run, args=(worker,)) for worker in (patch_idle_message, patch_appearance, flip_model)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert failures == []
    agent = directory.get_agent(row["agentId"])
    preferences = agent["metadata"][service.PREFERENCES_METADATA_KEY]
    assert preferences["idleMessage"] == "p3"
    assert preferences["characterId"] == "xiaoluo"
    assert agent["llmBindings"]["dialogue"]["modelId"] in {
        "assistant-model",
        "whale-xl",
    }


@pytest.mark.parametrize(
    "unhealthy",
    [
        {"providerHealthy": False, "missingApiKey": False},
        {"providerHealthy": True, "missingApiKey": True},
    ],
    ids=["provider-broken", "missing-key"],
)
def test_model_update_rejects_unavailable_candidates_without_writing(
    personal_env, monkeypatch, unhealthy
):
    row = _created_assistant(personal_env, monkeypatch)
    _llm_options(
        monkeypatch,
        [
            {"modelId": "assistant-model", "label": "助理模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": True, "providerHealthy": True, "missingApiKey": False,
             "availability": "available"},
            {"modelId": "sick-model", "label": "病态模型", "providerLabel": "测试",
             "runtimeSelectable": True, "slotCompatibility": {"dialogue": {"allowed": True}},
             "isDefault": False, "availability": "available", **unhealthy},
        ],
    )
    before = directory.load_state()
    with pytest.raises(directory.AgentDirectoryError, match="当前不可用"):
        service.update_personal_assistant_model("sick-model")
    assert directory.load_state() == before
    assert (
        directory.get_agent(row["agentId"])["llmBindings"]["dialogue"]["modelId"]
        == "assistant-model"
    )
    # The unhealthy candidate is still listed for display; only binding is denied.
    choices = service.get_personal_assistant_settings()["settings"]["model"]["choices"]
    assert [choice["modelId"] for choice in choices] == ["assistant-model", "sick-model"]


def test_llm_options_failure_degrades_read_and_blocks_model_write(
    personal_env, monkeypatch
):
    row = _created_assistant(personal_env, monkeypatch)

    def fail(_session_id):
        raise RuntimeError("options unavailable")

    monkeypatch.setattr(session_service, "get_session_llm_options", fail)
    settings = service.get_personal_assistant_settings()["settings"]
    assert settings["model"]["currentModelId"] == "assistant-model"
    assert settings["model"]["choices"] == []
    before = directory.load_state()
    with pytest.raises(directory.AgentDirectoryError, match="暂时无法读取可用模型列表"):
        service.update_personal_assistant_model("assistant-model")
    assert directory.load_state() == before


def test_settings_get_returns_null_for_missing_or_archived_assistant(personal_env, monkeypatch):
    assert service.get_personal_assistant_settings() == {"settings": None}
    row = _created_assistant(personal_env, monkeypatch)
    assert service.get_personal_assistant_settings()["settings"]["displayName"] == "个人助理"
    directory.update_agent_instance(row["agentId"], status="archived")
    assert service.get_personal_assistant_settings() == {"settings": None}
