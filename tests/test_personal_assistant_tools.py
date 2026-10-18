"""Personal manager tools keep canonical identity, bounded dispatch and approval."""

import json
from functools import wraps

import pytest
from langchain_core.tools import tool

from core.authorization.tool_policy_evaluator import (
    evaluate_tool_policy,
    normalize_legacy_tool_policy,
)
from core.authorization.tool_policy_models import TurnToolGrant
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as service
from core.web.services import generic_team_workflow_service as workflow
from core.web.services import session_service, team_knowledge_service, tool_catalog
from tests.test_financial_report_registry import definition
from tests.test_personal_assistant_service import (
    _corrupt_agent,
)
from tests.test_personal_assistant_service import (
    finance_env as _finance_env,
)
from tests.test_personal_assistant_service import personal_env as _personal_env
from tools import personal_assistant_tools as tools
from tools import rebirth_tools

finance_env = _finance_env
personal_env = _personal_env
MANAGE = "personal_assistant_manage_tool"
OVERVIEW = "personal_assistant_overview_tool"


@pytest.fixture
def assistant_runtime(personal_env, monkeypatch):
    row = service.create_personal_assistant()["assistant"]
    monkeypatch.setattr(
        directory,
        "current_agent_runtime",
        lambda: {
            "agentId": row["agentId"],
            "sessionId": row["directSessionId"],
        },
    )
    return row


def _blocked(raw):
    result = json.loads(raw)
    assert result["ok"] is False and result["status"] == "blocked"


def _forbid(*_args, **_kwargs):
    pytest.fail("blocked tool reached a platform operation")


@pytest.mark.parametrize("runtime", ["missing", "ordinary", "foreign_session"])
def test_tools_reject_unbound_ordinary_and_foreign_runtime_identity(
    personal_env, assistant_runtime, monkeypatch, runtime
):
    row = assistant_runtime
    invalid = (
        {}
        if runtime == "missing"
        else {
            "agentId": personal_env["owner"]
            if runtime == "ordinary"
            else row["agentId"],
            "sessionId": "foreign-session",
        }
    )
    monkeypatch.setattr(directory, "current_agent_runtime", lambda: invalid)
    monkeypatch.setattr(service, "get_platform_overview", _forbid)
    monkeypatch.setattr(tools.operations, "agent_archive_tool", _forbid)
    _blocked(tools.personal_assistant_overview_tool())
    _blocked(
        tools.personal_assistant_manage_tool("agent_archive", '{"agent_id":"other"}')
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"roleKey": "ordinary"},
        {"primaryMode": "chat"},
        {"status": "archived"},
        {"metadata": {"personalAssistantProfile": "other"}},
    ],
)
def test_tools_reject_tampered_profile_identity(
    personal_env, assistant_runtime, monkeypatch, changes
):
    _corrupt_agent(assistant_runtime["agentId"], **changes)
    monkeypatch.setattr(service, "get_platform_overview", _forbid)
    _blocked(tools.personal_assistant_overview_tool())


@pytest.mark.parametrize("corruption", ["foreign_owner", "archived"])
def test_tools_require_actual_session_ownership_and_unarchived_row(
    personal_env, assistant_runtime, monkeypatch, corruption
):
    row = assistant_runtime
    session = session_service.load_session_chat_state(
        personal_env["root"], row["directSessionId"]
    )
    if corruption == "foreign_owner":
        session["agentId"] = session["agent_id"] = personal_env["other"]
    else:
        session["archive_state"] = session["archiveState"] = {"status": "archived"}
    session_service.save_session_chat_state(
        personal_env["root"], row["directSessionId"], session
    )
    monkeypatch.setattr(service, "get_platform_overview", _forbid)
    _blocked(tools.personal_assistant_overview_tool())


def test_tools_fail_closed_when_profile_is_no_longer_unique(
    personal_env, assistant_runtime, monkeypatch
):
    directory.create_agent_instance(
        display_name="重复个人助理",
        primary_mode="general",
        role_key=service.ROLE,
        metadata={"personalAssistantProfile": service.PROFILE},
    )
    monkeypatch.setattr(service, "get_platform_overview", _forbid)
    _blocked(tools.personal_assistant_overview_tool())


def test_overview_tool_delegates_only_after_canonical_identity(
    assistant_runtime, monkeypatch
):
    calls = []
    payload = {
        "generatedAt": "test",
        "counts": {},
        "agents": [],
        "sessions": [],
        "attention": [],
    }
    monkeypatch.setattr(
        service, "get_platform_overview", lambda **_kwargs: calls.append(1) or payload
    )
    assert json.loads(tools.personal_assistant_overview_tool()) == {
        "ok": True,
        **payload,
    }
    assert calls == [1]


@pytest.mark.parametrize(
    "action,target,args",
    [
        ("agent_create", "agent_create_tool", {"display_name": "新助手"}),
        (
            "agent_update",
            "agent_update_tool",
            {"agent_id": "target", "updates_json": '{"displayName":"新名字"}'},
        ),
        ("agent_archive", "agent_archive_tool", {"agent_id": "target"}),
        (
            "session_create",
            "session_create_tool",
            {"title": "新会话", "agent_id": "target"},
        ),
        (
            "session_update",
            "session_update_tool",
            {"session_id": "target", "title": "新标题"},
        ),
        (
            "session_stop",
            "session_stop_tool",
            {"session_id": "target", "turn_id": "turn-target"},
        ),
        ("session_delete", "session_delete_tool", {"session_id": "target"}),
    ],
)
def test_manage_uses_native_operation_signatures_and_preserves_result(
    assistant_runtime, monkeypatch, action, target, args
):
    calls = []
    original = getattr(tools.operations, target)
    receipt = {"ok": True, "status": "native", "agentId": "target"}
    raw_result = json.dumps(
        {
            **receipt,
            "session": {"messages": ["private transcript"]},
            "agent": {"privateMemory": "private memory"},
        }
    )

    @wraps(original)
    def operation(**kwargs):
        calls.append(kwargs)
        return raw_result

    monkeypatch.setattr(tools.operations, target, operation)
    assert (
        json.loads(tools.personal_assistant_manage_tool(action, json.dumps(args)))
        == receipt
    )
    assert calls == [args]
    _blocked(
        tools.personal_assistant_manage_tool(
            action, json.dumps({**args, "command": "arbitrary command"})
        )
    )
    assert calls == [args]


@pytest.mark.parametrize(
    "action,arguments",
    [
        ("shell", "{}"),
        ("agent_purge", "{}"),
        ("session_restore", "{}"),
        ("agent_archive", "[]"),
        ("agent_archive", "{invalid"),
        ("agent_archive", '{"padding":"' + "x" * 16001 + '"}'),
    ],
)
def test_manage_rejects_unbounded_actions_or_bad_arguments_before_dispatch(
    assistant_runtime, monkeypatch, action, arguments
):
    monkeypatch.setattr(tools.operations, "agent_archive_tool", _forbid)
    _blocked(tools.personal_assistant_manage_tool(action, arguments))


def test_knowledge_acl_uses_native_current_actor_without_spoofable_argument(
    assistant_runtime, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        team_knowledge_service,
        "grant_knowledge_base_access",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"granted": True},
    )
    arguments = {
        "knowledge_base_id": "base",
        "target_agent_id": "target",
        "permissions_json": '["read"]',
    }
    result = json.loads(
        tools.personal_assistant_manage_tool(
            "knowledge_acl_grant", json.dumps(arguments)
        )
    )
    assert result["ok"] is True, result
    assert calls == [
        (
            ("base", "target"),
            {"permissions": ["read"], "actor_agent_id": assistant_runtime["agentId"]},
        )
    ]
    _blocked(
        tools.personal_assistant_manage_tool(
            "knowledge_acl_grant",
            json.dumps({**arguments, "actor_agent_id": "foreign-agent"}),
        )
    )
    assert len(calls) == 1


def test_restart_uses_native_rebirth_and_current_session_only(
    assistant_runtime, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        rebirth_tools,
        "trigger_self_restart_tool",
        lambda **kwargs: calls.append(kwargs) or '{"ok":true,"status":"scheduled"}',
    )
    result = tools.personal_assistant_manage_tool(
        "restart", '{"reason":"用户要求重启"}'
    )
    assert json.loads(result)["status"] == "scheduled"
    assert calls == [
        {"reason": "用户要求重启", "sessionId": assistant_runtime["directSessionId"]}
    ]
    for args in (
        {"reason": ""},
        {"reason": 1},
        {"reason": "重启", "sessionId": "foreign"},
    ):
        _blocked(tools.personal_assistant_manage_tool("restart", json.dumps(args)))
    assert len(calls) == 1


def test_manage_registered_descriptor_always_requires_native_approval():
    wrapper = definition(
        "tools/Key_Tools.py",
        MANAGE,
        {
            "tool": tool,
            "_personal_assistant_manage_impl": tools.personal_assistant_manage_tool,
        },
    )
    schema = wrapper.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"action", "arguments_json"}
    descriptor = tool_catalog.build_tool_descriptor(MANAGE, args_schema=schema)
    assert descriptor.approval == "always" and descriptor.risk == "destructive"
    assert descriptor.concurrency == "serialized"
    policy = normalize_legacy_tool_policy(
        {
            "allowedTools": [MANAGE],
            "mutationAccess": "controlled",
            "networkAccess": "none",
        },
        registered_tool_names=[MANAGE],
        policy_id="personal-test",
    )
    decision = evaluate_tool_policy(
        agent_id="personal-test",
        policy=policy,
        grant=TurnToolGrant(
            turn_id="turn-test",
            source="session",
            allowed_capabilities=descriptor.capabilities,
            denied_tools=(),
            approval_mode="on_request",
        ),
        descriptors=[descriptor],
        registry_version=1,
        registry_fingerprint="test",
    )
    assert decision.approval_requirements == ((MANAGE, "always", "destructive"),)


def test_overview_registered_descriptor_has_no_mutation_or_approval():
    wrapper = definition(
        "tools/Key_Tools.py",
        OVERVIEW,
        {
            "tool": tool,
            "_personal_assistant_overview_impl": tools.personal_assistant_overview_tool,
        },
    )
    assert set(wrapper.args_schema.model_json_schema()["properties"]) == {
        "offset", "limit", "team_id", "flow_id"
    }
    descriptor = tool_catalog.build_tool_descriptor(
        OVERVIEW, args_schema=wrapper.args_schema.model_json_schema()
    )
    assert descriptor.risk == "read" and descriptor.approval == "never"
    assert "read_only" in descriptor.capabilities


def test_overview_supplies_native_turn_for_managed_stop(assistant_runtime, monkeypatch):
    monkeypatch.setattr(directory, "list_agents", lambda **_kwargs: [directory.get_agent(assistant_runtime["agentId"])])
    monkeypatch.setattr(session_service, "list_sessions", lambda: [{"id": "worker-session", "agentId": "worker", "title": "工作", "status": "running"}])
    monkeypatch.setattr(session_service, "_current_session_turn_id", lambda session_id: "native-worker-turn" if session_id == "worker-session" else "")
    monkeypatch.setattr(service.pet_activity_service, "get_pet_activity", lambda: {"generatedAt": "test", "sessions": []})
    calls = []
    monkeypatch.setattr(session_service, "request_stop_session_turn", lambda session_id, **kwargs: calls.append((session_id, kwargs)) or {"id": session_id})
    overview = json.loads(tools.personal_assistant_overview_tool())
    target = overview["sessions"][0]
    result = json.loads(tools.personal_assistant_manage_tool("session_stop", json.dumps({"session_id": target["id"], "turn_id": target["turnId"]})))
    assert result["ok"] is True
    assert calls == [("worker-session", {"expected_turn_id": "native-worker-turn"})]


def test_stale_overview_turn_cannot_stop_a_new_turn(assistant_runtime, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _session_id: SimpleNamespace(turn_id="new-turn", request_stop=_forbid))
    result = json.loads(tools.personal_assistant_manage_tool("session_stop", '{"session_id":"worker-session","turn_id":"old-turn"}'))
    assert result["ok"] is False
    assert result["status"] == "blocked"


def test_agent_creation_reports_real_required_fields_without_creating(assistant_runtime, monkeypatch):
    monkeypatch.setattr(session_service, "create_chat_session", _forbid)
    result = json.loads(tools.personal_assistant_manage_tool("agent_create", '{"display_name":"新助手"}'))
    assert result["ok"] is False
    assert result["error"] == "invalid_input"
    assert all(field in result["message"] for field in ("对话模型", "使用位置", "提示词"))


def _workflow_arguments(payload):
    return json.dumps({"team_id": "team-a", "flow_id": "flow-a", "payload": payload})


@pytest.mark.parametrize("claimed_identity", ["foreign-assistant", "current-assistant"])
def test_workflow_binding_rejects_caller_supplied_assistant_identity(
    assistant_runtime, monkeypatch, claimed_identity
):
    monkeypatch.setattr(workflow, "bind_recovery", _forbid)
    claimed = (
        assistant_runtime["agentId"]
        if claimed_identity == "current-assistant"
        else claimed_identity
    )
    _blocked(tools.personal_assistant_manage_tool(
        "workflow_recovery_bind",
        _workflow_arguments({"expectedRevision": 1, "assistantAgentId": claimed}),
    ))


def test_workflow_binding_derives_identity_from_canonical_native_session(
    assistant_runtime, monkeypatch
):
    calls = []
    payload = {
        "expectedRevision": 1,
        "repairFlowId": "repair-flow",
        "directorAgentId": "director",
        "developerAgentId": "developer",
        "reviewerAgentId": "reviewer",
        "acknowledgeAutomaticRecovery": True,
        "replaySafety": "idempotent",
    }

    def bind(team_id, flow_id, request):
        calls.append((team_id, flow_id, request))
        return {
            "status": "ready", "bindingId": "binding-a", "expiresAt": "later",
            "assistantAgentId": request["assistantAgentId"],
            "values": {"secret": "private input"},
        }

    monkeypatch.setattr(workflow, "bind_recovery", bind)
    result = json.loads(tools.personal_assistant_manage_tool(
        "workflow_recovery_bind", _workflow_arguments(payload)
    ))
    assert calls == [("team-a", "flow-a", {
        **payload, "assistantAgentId": assistant_runtime["agentId"]
    })]
    assert result == {
        "ok": True, "status": "ready", "bindingId": "binding-a", "expiresAt": "later"
    }


@pytest.mark.parametrize("action", [
    "workflow_recovery_bind", "workflow_recovery_revoke", "workflow_start"
])
def test_workflow_actions_require_canonical_native_session_before_service_access(
    assistant_runtime, monkeypatch, action
):
    monkeypatch.setattr(directory, "current_agent_runtime", lambda: {
        "agentId": assistant_runtime["agentId"], "sessionId": "foreign-session"
    })
    for name in ("bind_recovery", "get_recovery_binding", "revoke_recovery", "start_run"):
        monkeypatch.setattr(workflow, name, _forbid)
    _blocked(tools.personal_assistant_manage_tool(action, _workflow_arguments({})))


@pytest.mark.parametrize("action", [
    "workflow_recovery_bind", "workflow_recovery_revoke", "workflow_start"
])
@pytest.mark.parametrize("arguments", [
    {"team_id": "team-a", "flow_id": "flow-a", "payload": []},
    {"team_id": "team-a", "flow_id": "flow-a"},
    {"team_id": "team-a", "flow_id": "flow-a", "payload": {},
     "assistantAgentId": "foreign-assistant"},
])
def test_workflow_actions_reject_extra_identity_and_invalid_envelopes(
    assistant_runtime, monkeypatch, action, arguments
):
    monkeypatch.setattr(workflow, "bind_recovery", _forbid)
    monkeypatch.setattr(workflow, "get_recovery_binding", _forbid)
    _blocked(tools.personal_assistant_manage_tool(action, json.dumps(arguments)))


@pytest.mark.parametrize("status", ["unbound", "legacy", "expired", "unavailable"])
def test_workflow_start_requires_ready_recovery_authorization(
    assistant_runtime, monkeypatch, status
):
    monkeypatch.setattr(workflow, "get_recovery_binding", lambda *_args: {
        "assistantAgentId": assistant_runtime["agentId"], "status": status
    })
    monkeypatch.setattr(workflow, "start_run", _forbid)
    _blocked(tools.personal_assistant_manage_tool(
        "workflow_start", _workflow_arguments({"expectedRevision": 2})
    ))


@pytest.mark.parametrize("action", ["workflow_recovery_revoke", "workflow_start", "overview"])
def test_workflow_operations_cannot_cross_assistant_binding(
    assistant_runtime, monkeypatch, action
):
    lookups = []
    monkeypatch.setattr(workflow, "get_recovery_binding", lambda *args: (
        lookups.append(args) or {"assistantAgentId": "foreign-assistant", "status": "ready"}
    ))
    for name in ("revoke_recovery", "start_run", "list_runs"):
        monkeypatch.setattr(workflow, name, _forbid)
    if action == "overview":
        result = tools.personal_assistant_overview_tool(team_id="team-a", flow_id="flow-a")
    else:
        result = tools.personal_assistant_manage_tool(action, _workflow_arguments({}))
    _blocked(result)
    assert lookups == [("team-a", "flow-a")]


@pytest.mark.parametrize("action,target,payload,native_result,receipt", [
    (
        "workflow_recovery_revoke", "revoke_recovery", {"expectedRevision": 2},
        {"status": "unbound", "bindingId": "binding-a", "sourceRevision": 3},
        {"ok": True, "status": "unbound", "bindingId": "binding-a"},
    ),
    (
        "workflow_start", "start_run",
        {"expectedRevision": 2, "idempotencyKey": "start-a", "values": {"subject": "任务"}},
        {"id": "run-a", "status": "running", "values": {"subject": "任务"},
         "attempts": [{"transcript": "private transcript"}]},
        {"ok": True, "teamId": "team-a", "flowId": "flow-a", "runId": "run-a",
         "status": "running"},
    ),
])
def test_owned_workflow_mutations_use_native_payload_and_bounded_receipts(
    assistant_runtime, monkeypatch, action, target, payload, native_result, receipt
):
    calls = []
    monkeypatch.setattr(workflow, "get_recovery_binding", lambda *_args: {
        "assistantAgentId": assistant_runtime["agentId"], "status": "ready"
    })
    monkeypatch.setattr(workflow, target, lambda *args: calls.append(args) or native_result)
    assert json.loads(tools.personal_assistant_manage_tool(
        action, _workflow_arguments(payload)
    )) == receipt
    assert calls == [("team-a", "flow-a", payload)]


@pytest.mark.parametrize("team_id,flow_id", [("team-a", ""), ("", "flow-a")])
def test_workflow_overview_requires_complete_scope(assistant_runtime, monkeypatch, team_id, flow_id):
    monkeypatch.setattr(workflow, "get_recovery_binding", _forbid)
    monkeypatch.setattr(service, "get_platform_overview", _forbid)
    _blocked(tools.personal_assistant_overview_tool(team_id=team_id, flow_id=flow_id))


def test_workflow_overview_filters_and_bounds_public_run_status_without_private_content(
    assistant_runtime, monkeypatch
):
    binding = {
        "teamId": "team-a", "flowId": "flow-a", "bindingId": "binding-a",
        "assistantAgentId": assistant_runtime["agentId"], "status": "ready"
    }
    recovery = {"issueId": "issue-a", "nodeId": "node-a", "status": "tracking"}
    runs = [{
        "id": "other-run", "flow": {"id": "other-flow"}, "status": "failed",
        "current": "other-node", "revision": 1,
    }]
    runs.extend({
        "id": f"run-{index}", "flow": {"id": "flow-a", "description": "private recipe"},
        "status": "failed", "current": "node-a", "revision": index + 1,
        "recovery": recovery,
        "values": {"subject": "private business input"},
        "attempts": [{"transcript": "private transcript", "messages": ["private message"]}],
        "transcript": "private root transcript",
    } for index in range(25))
    calls = []
    monkeypatch.setattr(workflow, "get_recovery_binding", lambda *_args: binding)
    monkeypatch.setattr(workflow, "list_runs", lambda *args, **kwargs: calls.append((args, kwargs)) or {"runs": runs})
    monkeypatch.setattr(service, "get_platform_overview", _forbid)
    raw = tools.personal_assistant_overview_tool(team_id="team-a", flow_id="flow-a")
    result = json.loads(raw)
    assert result == {"ok": True, "binding": binding, "recentRuns": [{
        "runId": f"run-{index}", "status": "failed", "current": "node-a",
        "revision": index + 1, "recovery": recovery,
    } for index in range(20)]}
    assert calls == [(("team-a",), {"flow_id": "flow-a", "limit": 20})]
    for private in ("private", "values", "transcript", "messages", "attempts", "other-run"):
        assert private not in raw
