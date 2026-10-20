"""Indexed project reads stay scoped, fresh, bounded and independently executable."""

import json
import os
from pathlib import Path

import pytest

from core.web.services import personal_assistant_service as service, session_service
from tools import personal_assistant_tools as tools
from tests.test_personal_assistant_tools import assistant_runtime
from tests.test_personal_assistant_service import personal_env, finance_env


def query(resource="index", operation="list", **kwargs):
    return json.loads(tools.personal_assistant_query_tool(resource=resource, operation=operation, **kwargs))


def test_index_describes_all_queries_without_reading_their_stores(assistant_runtime, monkeypatch):
    monkeypatch.setattr(service, "get_platform_overview", lambda **_: pytest.fail("index must not fetch state"))
    result = query()
    assert result["ok"] and result["observedAt"]
    resources = {row["resource"] for row in result["data"]["resources"]}
    assert {"project", "code", "agents", "sessions", "tasks", "attention", "inbox", "runtime", "capabilities"} <= resources
    card = query("index", "describe", object_id="code")["data"]
    assert {"list", "search", "read"} <= set(card["operations"])
    assert card["authority"] and card["limits"] and card["examples"]
    assert card["operationParameters"]["read"] == ["path", "line", "max_lines"]


@pytest.mark.skipif(os.name != "nt", reason="Windows source adapter")
def test_project_code_can_be_discovered_searched_and_read(assistant_runtime, personal_env):
    root = personal_env["root"]
    (root / "core").mkdir(exist_ok=True)
    (root / "core" / "notifications.py").write_text("def notify():\n    return 'attention_monitor'\n", encoding="utf-8")
    results = query("code", "search", query="attention_monitor")["data"]
    assert results["items"][0]["path"] == "core/notifications.py"
    assert results["items"][0]["line"] == 2
    read = query("code", "read", path="core/notifications.py", line=1, max_lines=2)
    assert read["ok"] and "def notify" in read["data"]["text"]
    assert read["evidence"] and read["untrustedContent"] is True


@pytest.mark.parametrize("path", ["../private.txt", "C:/Windows/win.ini", ".git/config", "config.toml", ".env", "token.txt", ".runtime/secrets.json"])
def test_code_query_rejects_private_and_outside_paths(assistant_runtime, path):
    result = query("code", "read", path=path)
    assert result["ok"] is False and result["status"] == "blocked"


def test_generic_query_cannot_accept_foreign_inbox_or_arbitrary_operations(assistant_runtime):
    for request in [dict(resource="inbox", object_id="another-agent"),
                    dict(resource="https://localhost/api/config"), dict(resource="sessions", operation="delete")]:
        assert query(**request)["ok"] is False


def test_query_rejects_foreign_native_identity(assistant_runtime, monkeypatch):
    monkeypatch.setattr(tools.directory, "current_agent_runtime", lambda: {"agentId": assistant_runtime["agentId"], "sessionId": "foreign"})
    assert query()["status"] == "blocked"


def test_overview_query_includes_human_attention_and_fresh_reads(assistant_runtime, monkeypatch):
    from core.web.services import personal_attention_service as attention
    counter = []
    monkeypatch.setattr(service, "get_platform_overview", lambda **_: counter.append(1) or {
        "counts": {}, "agents": [], "sessions": [], "attention": [], "pagination": {"nextOffset": None}})
    monkeypatch.setattr(attention, "attach_attention_to_overview", lambda value: {**value, "humanAttention": [{"id": "notification", "kind": "anomaly"}]})
    assert query("overview", "get")["data"]["humanAttention"][0]["id"] == "notification"
    assert query("attention", "list")["data"]["items"][0]["id"] == "notification"
    assert len(counter) == 2


def test_capabilities_do_not_claim_configured_tools_are_executable(assistant_runtime):
    result = query("capabilities", "get")["data"]
    assert "personal_assistant_query_tool" in result["configuredTools"]
    assert result["executionDecisionAvailable"] is False
    assert result["executableTools"] is None


def test_registered_wrapper_is_executable_under_native_default_policy(assistant_runtime):
    from langchain_core.tools import tool
    from tests.test_financial_report_registry import definition
    from core.authorization.tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
    from core.authorization.tool_policy_models import TurnToolGrant
    from core.web.services import tool_catalog
    wrapper = definition("tools/Key_Tools.py", "personal_assistant_query_tool", {
        "tool": tool, "_personal_assistant_query_impl": tools.personal_assistant_query_tool})
    schema = wrapper.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"resource", "operation", "object_id", "query", "path", "offset", "limit", "line", "max_lines"}
    descriptor = tool_catalog.build_tool_descriptor(wrapper.name, args_schema=schema)
    assert descriptor.risk == "read" and descriptor.approval == "never"
    assert wrapper.name in tool_catalog.explicit_allow_tool_names()
    agent = tools.directory.get_agent(assistant_runtime["agentId"])
    descriptors = [tool_catalog.build_tool_descriptor(name, args_schema=schema if name == wrapper.name else {}) for name in service.TOOLS]
    decision = evaluate_tool_policy(agent_id=agent["agentId"],
        policy=normalize_legacy_tool_policy(agent["toolPolicy"], registered_tool_names=service.TOOLS, policy_id=agent["toolPolicyId"]),
        grant=TurnToolGrant(turn_id="query-turn", source="session", allowed_capabilities=descriptor.capabilities,
            denied_tools=(), approval_mode="on_request"), descriptors=descriptors, registry_version=1, registry_fingerprint="test")
    assert wrapper.name in decision.executable_tools
    assert json.loads(wrapper.invoke({}))["ok"]


@pytest.mark.parametrize("custom", [False, True])
def test_explicit_setup_upgrades_old_default_but_preserves_custom_denial_and_prompt(personal_env, custom):
    row = service.create_personal_assistant()["assistant"]
    previous = {**service.current_policy(), "allowedTools": list(service._COMPUTER_TOOLS),
        "preferredTools": list(service._COMPUTER_TOOLS), "networkAccess": "none" if custom else "restricted"}
    task = {**service._PRE_QUERY_TASK, **({"responsibilities": "我的职责"} if custom else {})}
    tools.directory.update_agent_instance(row["agentId"], tool_policy=previous, task_profile=task)
    before = tools.directory.get_agent(row["agentId"])
    # GET must not provision tools or modify profiles.
    service.get_personal_assistant()
    assert tools.directory.get_agent(row["agentId"]) == before
    service.create_personal_assistant()
    after = tools.directory.get_agent(row["agentId"])
    if custom:
        assert after["toolPolicy"] == before["toolPolicy"] and after["taskProfile"] == before["taskProfile"]
    else:
        assert "personal_assistant_query_tool" in after["toolPolicy"]["allowedTools"]
        assert after["taskProfile"] == tools.directory.normalize_task_profile(service.TASK)


def test_upgrade_does_not_overwrite_custom_task_profile(personal_env):
    row = service.create_personal_assistant()["assistant"]
    previous = {**service.current_policy(), "allowedTools": list(service._COMPUTER_TOOLS), "preferredTools": list(service._COMPUTER_TOOLS)}
    tools.directory.update_agent_instance(row["agentId"], tool_policy=previous, task_profile={"responsibilities": "自定义"})
    before = tools.directory.get_agent(row["agentId"])["taskProfile"]
    service.create_personal_assistant()
    assert tools.directory.get_agent(row["agentId"])["taskProfile"] == before


def test_setup_recovers_default_navigation_after_interrupted_policy_upgrade(personal_env):
    row = service.create_personal_assistant()["assistant"]
    tools.directory.update_agent_instance(row["agentId"], task_profile=service._PRE_QUERY_TASK)
    service.create_personal_assistant()
    assert tools.directory.get_agent(row["agentId"])["taskProfile"] == tools.directory.normalize_task_profile(service.TASK)


@pytest.mark.skipif(os.name != "nt", reason="Windows source adapter")
def test_own_notification_delivery_record_can_lead_to_code_and_runtime(assistant_runtime, personal_env, monkeypatch):
    from core.diagnostics import agent_log_context
    tools.directory.write_agent_inbox_message(assistant_runtime["agentId"], content="人工关注通知投递失败",
        kind="attention_monitor", metadata={"attentionId": "probe-test", "kind": "unknown", "stage": "shell",
            "reason": "invalid_payload", "reportedBy": "attention_monitor", "privateField": "not-visible"})
    tools.directory.write_agent_inbox_message(personal_env["other"], content="foreign private message")
    records = query("inbox", query="投递失败")["data"]["items"]
    assert records[0]["metadata"]["reason"] == "invalid_payload"
    assert records[0]["metadata"]["stage"] == "shell"
    assert "foreign private message" not in json.dumps(records) and "privateField" not in records[0]["metadata"]
    (personal_env["root"] / "core").mkdir(exist_ok=True)
    (personal_env["root"] / "core" / "notification.py").write_text("# attention_monitor\nreason = 'invalid_payload'\n", encoding="utf-8")
    found = query("code", "search", path="core", query=records[0]["kind"])["data"]["items"][0]
    assert "invalid_payload" in query("code", "read", path=found["path"])["data"]["text"]
    seen = []
    monkeypatch.setattr(agent_log_context, "build_agent_log_context", lambda root: seen.append(root) or {
        "firstRead": {"conclusion": "需处理", "nextStep": "查看现有诊断", "doNotDo": "不要猜测", "transcript": "private"},
        "rawLogs": "private", "selectionStatus": "selected"})
    report = query("runtime", "get")["data"]
    assert report["firstRead"]["conclusion"] == "需处理" and "transcript" not in report["firstRead"]
    assert "rawLogs" not in report and seen == [personal_env["root"].resolve()]


def test_task_status_uses_current_project_store_and_omits_outputs(assistant_runtime, personal_env, monkeypatch):
    from core.web.services import runtime_task_registry
    from vibelution_storage import resolve_project_runtime_home
    from types import SimpleNamespace
    roots = []
    monkeypatch.setattr(runtime_task_registry, "store_for", lambda root: roots.append(root) or SimpleNamespace(active_task_states=lambda: [
        {"taskId": "task-a", "status": "running", "sourceSessionId": "session-a", "output": "private", "pendingMessages": ["private"]}]))
    result = query("tasks", "get", object_id="task-a")["data"]
    assert result["status"] == "running" and "output" not in result and "pendingMessages" not in result
    assert roots == [resolve_project_runtime_home(personal_env["root"]) / runtime_task_registry.STORE_DIR_NAME]


def test_capabilities_require_matching_trusted_turn(assistant_runtime, monkeypatch):
    from core.authorization import tool_authorization_service as auth
    from types import SimpleNamespace
    runtime = {"agentId": assistant_runtime["agentId"], "sessionId": assistant_runtime["directSessionId"], "turnId": "current-turn"}
    monkeypatch.setattr(tools.directory, "current_agent_runtime", lambda: runtime)
    trusted = SimpleNamespace(agent_id=runtime["agentId"], turn_id="current-turn", executable_tools=("personal_assistant_query_tool",),
        approval_requirements=(("personal_assistant_manage_tool", "always", "destructive"),), deny_rules=())
    monkeypatch.setattr(auth, "current_execution_authorization", lambda: trusted)
    assert query("capabilities", "get")["data"]["executableTools"] == ["personal_assistant_query_tool"]
    trusted.turn_id = "stale-turn"
    assert query("capabilities", "get")["data"]["executableTools"] is None


@pytest.mark.parametrize("kwargs", [{"resource": []}, {"operation": {}}, {"offset": True}, {"limit": 51}, {"query": "x" * 201},
    {"resource": "index", "operation": "list", "object_id": "ignored"},
    {"resource": "runtime", "operation": "get", "path": "logs"}, {"resource": "project", "operation": "get", "offset": 1},
    {"resource": "code", "operation": "read", "path": "README.md", "query": "unused"}])
def test_invalid_arguments_never_reach_source(assistant_runtime, kwargs):
    assert not query(**kwargs)["ok"]


def test_native_source_failure_is_unavailable_and_does_not_echo_exception(assistant_runtime, monkeypatch):
    def fail(**_):
        raise RuntimeError("secret runtime content")
    monkeypatch.setattr(service, "get_platform_overview", fail)
    result = query("sessions")
    assert result["status"] == "unavailable" and "secret" not in json.dumps(result)


@pytest.mark.skipif(os.name != "nt", reason="Windows source adapter")
def test_source_reads_redact_literals_and_mark_truncation(assistant_runtime, personal_env):
    root = personal_env["root"]
    (root / "core").mkdir(exist_ok=True)
    (root / "core" / "settings.py").write_text('api_key = "sensitive-value"\n' + "x" * 13000, encoding="utf-8")
    result = query("code", "read", path="core/settings.py")["data"]
    assert "sensitive-value" not in result["text"] and result["truncated"]
    assert len(result["text"]) <= 12000
    (root / "core" / "large.py").write_bytes(b"x" * 256001)
    assert not query("code", "read", path="core/large.py")["ok"]


def test_source_link_aliases_and_unapproved_root_files_are_denied(assistant_runtime, personal_env):
    import os
    root = personal_env["root"]
    (root / "core").mkdir(exist_ok=True)
    (root / "private.txt").write_text("private", encoding="utf-8")
    os.link(root / "private.txt", root / "core" / "linked.py")
    for path in ("core/linked.py", "private.txt", "core/x.py:stream", "core/x.py. "):
        assert not query("code", "read", path=path)["ok"]


@pytest.mark.skipif(os.name != "nt", reason="Windows source adapter")
def test_search_budget_is_explicit_and_native_session_fields_stay_public(assistant_runtime, personal_env, monkeypatch):
    from core.web.services.personal_assistant_project import workspace
    (personal_env["root"] / "core").mkdir(exist_ok=True)
    (personal_env["root"] / "core" / "a.py").write_text("match\nmatch\nmatch\n", encoding="utf-8")
    result = query("code", "search", path="core", query="match", limit=1)["data"]
    assert result["truncated"] and result["nextOffset"] == 1
    monkeypatch.setattr(service, "get_platform_overview", lambda **_: {"sessions": [
        {"id": "s1", "title": "任务", "status": "running", "turnId": "t1", "transcript": "private", "prompt": "private"}],
        "pagination": {"revision": "1", "nextOffset": None}})
    row = query("sessions", "get", object_id="s1")["data"]
    assert row["turnId"] == "t1" and "transcript" not in row and "prompt" not in row


@pytest.mark.skipif(os.name != "nt", reason="Windows source adapter")
def test_real_checkout_source_handle_read():
    from core.web.services.personal_assistant_project import workspace
    root = Path(__file__).resolve().parents[1]
    found = workspace.discover_sources(root, path="core/web/services", query="attention_monitor", offset=0, limit=3, search=True)
    assert found["items"]
    target = found["items"][0]
    source = workspace.read_source(root, target["path"], line=target["line"], max_lines=3)
    assert "attention_monitor" in source["text"] and source["contentHash"]


def test_project_version_reads_real_checkout_without_claiming_runtime_version(monkeypatch):
    from core.web.services.personal_assistant_project.query import query_project
    from core.infrastructure.git_process import run_git
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(session_service, "PROJECT_ROOT", root)
    result = query_project({"agentId": "isolated", "sessionId": "isolated"}, resource="project", operation="get")
    assert result["ok"]
    expected = run_git(["rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, retries=0)
    assert result["data"]["checkoutHead"] == expected.stdout.strip()
    assert result["data"]["runningBuildRevision"] is None
    assert result["data"]["runningBuildStatus"] == "not_observed"


def test_workflow_status_is_scoped_partial_and_excludes_business_content(assistant_runtime, monkeypatch):
    from core.web.services import generic_team_workflow_service as workflow
    monkeypatch.setattr(workflow, "list_flows", lambda team: {"flows": [
        {"id": "flow-a", "name": "流程", "fields": ["private input schema"], "steps": ["private prompt"]}]})
    rows = query("workflows", object_id="team-a")["data"]
    assert rows["coverage"] and "steps" not in rows["items"][0] and "fields" not in rows["items"][0]
    monkeypatch.setattr(workflow, "list_runs", lambda team, **kwargs: {"runs": [
        {"id": "run-a", "status": "failed", "flow": {"id": "flow-a"}, "values": {"private": "input"}, "attempts": ["transcript"]},
        {"id": "foreign", "status": "running", "flow": {"id": "flow-b"}}]})
    result = query("workflows", "runs", object_id="team-a/flow-a")["data"]
    assert result["coverage"] and result["items"] == [{"id": "run-a", "status": "failed"}]
