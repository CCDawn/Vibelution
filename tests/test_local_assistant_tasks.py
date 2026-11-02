"""First-party task permissions must not widen the third-party gateway."""
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services.external_agent.service import ExternalAgentAccessError
from core.web.services.external_agent.store import ExternalAgentTaskStore
from tests.test_external_agent_task_service import FakeRuntime, _service


def local_service(tmp_path, runtime=None, **options):
    from core.web.services.local_assistant.service import LocalAssistantTaskService
    runtime = runtime or FakeRuntime()
    external = _service(tmp_path / "external", runtime, allowed_agent_ids=("someone-else",))
    external.enabled = False
    external.operator_permission_ceiling = "read_only"
    workspace = tmp_path / "task-worktree"
    workspace.mkdir(exist_ok=True)
    service = LocalAssistantTaskService(
        ExternalAgentTaskStore(tmp_path / "local"), project_root=tmp_path,
        dependencies=external.dependencies, authority_fingerprint=lambda: "a" * 64,
        workspace_factory=lambda task_id: workspace, **options,
    )
    return service, external, runtime, workspace


def start(service):
    return service.start_task(owner_id="private-task-owner", adapter_connection_id="private-connection",
        capabilities=set(), agent_id="coder", task="Implement the agreed change and run its tests",
        permission_profile="workspace_write", client_request_id="request-1", title="Development",
        runtime_revision="a" * 40, include_private=True)


def test_local_development_works_while_third_party_remains_disabled(tmp_path):
    service, external, runtime, workspace = local_service(tmp_path)
    with pytest.raises(ExternalAgentAccessError):
        start(external)
    result = start(service)
    assert result["effectivePermissionProfile"] == "workspace_write"
    record = service.store.get_task(result["taskId"])
    assert record["localWorkspacePath"] == str(workspace)
    assert record["localAuthorityFingerprint"] == "a" * 64
    assert runtime.submit_calls[0]["message_metadata"]["taskId"] == result["taskId"]
    assert external.store.list_nonterminal() == []


def test_explicit_local_deny_still_blocks_new_tasks(tmp_path):
    service, _, runtime, _ = local_service(tmp_path, denied_agent_ids=["coder"])
    with pytest.raises(ExternalAgentAccessError):
        start(service)
    assert runtime.create_calls == []


def test_native_transport_lease_survives_a_slow_model_without_widening_mcp(tmp_path, monkeypatch):
    from datetime import datetime
    from core.web.routes import local_assistant_tasks

    service, external, _, _ = local_service(tmp_path)
    external_lease = external.lease_seconds
    monkeypatch.setattr(local_assistant_tasks, "build_local_service", lambda root: service)
    native = local_assistant_tasks.local_service()
    result = start(native)
    record = native.store.get_task(result["taskId"])
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert (parse(record["leaseExpiresAt"]) - parse(record["createdAt"])).total_seconds() == 300
    assert external.lease_seconds == external_lease


def test_only_backend_record_can_enable_local_execution(tmp_path):
    from core.web.services.local_assistant.runtime import verified_task_runtime
    service, _, runtime, workspace = local_service(tmp_path)
    result = start(service)
    metadata = runtime.submit_calls[0]["message_metadata"]
    kwargs = dict(project_root=tmp_path, session_id="session-1", agent_id="coder",
                  metadata=metadata, store=service.store, authority_fingerprint=lambda: "a" * 64)
    assert verified_task_runtime(**kwargs)["workspace"] == workspace
    assert verified_task_runtime(**{**kwargs, "session_id": "foreign-session"}) is None
    assert verified_task_runtime(**{**kwargs, "agent_id": "foreign-agent"}) is None
    assert verified_task_runtime(**{**kwargs, "authority_fingerprint": lambda: "b" * 64}) is None
    assert verified_task_runtime(**{**kwargs, "metadata": {**metadata, "taskId": "eat-forged"}}) is None
    assert "localAuthorityFingerprint" not in result


def test_private_route_requires_both_control_and_launcher_capability(monkeypatch):
    from core.web.routes import local_assistant_tasks, external_agent
    from tests.test_external_agent_routes import FakeService
    local, external = FakeService(), FakeService()
    monkeypatch.setattr(local_assistant_tasks, "verify_launcher_authority", lambda token: token == "private-launcher-secret")
    monkeypatch.setattr(local_assistant_tasks, "local_service", lambda: local)
    monkeypatch.setattr(external_agent, "_SERVICE", external)
    app = FastAPI()
    app.include_router(external_agent.router, prefix="/api")
    app.include_router(local_assistant_tasks.router, prefix="/api")
    client = TestClient(app)
    path = "/api/local-assistant/v1/external-agent/agents"
    control = {CONTROL_TOKEN_HEADER: get_control_token()}
    assert client.get(path, headers=control).status_code == 403
    headers = {**control, "X-Vibelution-Management-Subject": "launcher-local",
               "X-Vibelution-Management-Capability": "private-launcher-secret"}
    assert client.get(path, headers=headers).status_code == 200
    assert local.calls and not external.calls
    client.get("/api/v1/external-agent/agents", headers=headers)
    assert external.calls


def test_local_worker_preparation_reaches_native_model_handoff(monkeypatch, tmp_path):
    from core.web.services import session_service
    from core.web.services.session import worker
    from core.web.services.local_assistant import runtime
    from tests.test_session_worker import _install_full_prepare_reach_harness
    calls, lifecycle, workspaces = [], [], []
    workspace = tmp_path / "owned-worktree"
    workspace.mkdir()
    _install_full_prepare_reach_harness(monkeypatch, tmp_path, calls=calls, lifecycle=lifecycle)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "get_agent", lambda *a, **kw: {"agentId": "coder", "status": "active"})
    monkeypatch.setattr(session_service, "_get_turn_control_stop_reason", lambda *a: "")
    monkeypatch.setattr(session_service, "_ensure_session_agent_prompt_snapshot", lambda *a, **kw: {})
    monkeypatch.setattr(session_service, "_render_agent_prompt_snapshot_block", lambda *a: "")
    monkeypatch.setattr(session_service, "_session_reasoning_effort_snapshot", lambda *a: "")
    monkeypatch.setattr(session_service, "_resolve_session_agent_llm", lambda *a, **kw: None)
    monkeypatch.setattr(session_service, "build_agent_context", lambda *a, **kw: None)
    monkeypatch.setattr(runtime, "verified_task_runtime", lambda **kwargs:
        {"taskId": "eat-local", "workspace": workspace, "profile": "workspace_write"})
    from contextlib import nullcontext
    def capture_workspace(path, **kwargs):
        workspaces.append(path)
        return nullcontext()
    monkeypatch.setattr(session_service, "_session_tool_workspace_override", capture_workspace)
    control = session_service.SessionTurnControl(session_id="session-1", turn_id="turn-1")
    worker._run_session_turn_impl({"session_id": "session-1", "turn_id": "turn-1",
        "turn_control": control, "agent_id": "coder", "user_message": "Implement and test", "message_metadata": {}})
    assert "continuation" in calls
    assert workspace in workspaces


def test_expired_local_task_loses_execution_grant_and_is_stopped_by_reconcile(tmp_path):
    from core.web.services.local_assistant.runtime import verified_task_runtime
    service, _, runtime, _ = local_service(tmp_path)
    result = start(service)
    record = service.store.get_task(result["taskId"])
    service.store.transition(record["taskId"], status=record["status"], fields={
        "leaseExpiresAt": "2000-01-01T00:00:00Z", "deadlineAt": "2000-01-01T00:00:00Z"})
    assert verified_task_runtime(project_root=tmp_path, session_id="session-1", agent_id="coder",
        metadata=runtime.submit_calls[0]["message_metadata"], store=service.store,
        authority_fingerprint=lambda: "a" * 64) is None
    service.reconcile()
    assert runtime.stop_calls == [("session-1", "turn-1")]


def test_existing_backend_reconcile_also_visits_local_namespace(monkeypatch):
    from core.web import lifecycle
    from core.web.services.external_agent import service as external_service
    from core.web.services.local_assistant import service
    from types import SimpleNamespace
    seen = []
    monkeypatch.setattr(external_service, "get_default_service", lambda root:
        SimpleNamespace(reconcile=lambda: seen.append("external") or []))
    monkeypatch.setattr(service, "build_local_service", lambda root:
        SimpleNamespace(reconcile=lambda: seen.append("local") or []))
    lifecycle.reconcile_external_agent_tasks_once()
    assert seen == ["external", "local"]


def test_local_relative_reads_use_bound_worktree_without_changing_ordinary_reads(tmp_path, monkeypatch):
    from tools import shell_tools
    from core.web.services import agent_directory_service as directory
    parent = tmp_path / "parent"
    task = tmp_path / "task"
    parent.mkdir()
    task.mkdir()
    monkeypatch.setattr(shell_tools, "PROJECT_ROOT", parent)
    monkeypatch.setattr(directory, "current_agent_runtime", lambda: {"runtimeToolSource": "launcher_assistant_task:workspace_write"})
    with shell_tools.workspace_root_override(task):
        assert shell_tools._resolve_project_path("demo.py") == task / "demo.py"
        monkeypatch.setattr(directory, "current_agent_runtime", lambda: {"runtimeToolSource": ""})
        assert shell_tools._resolve_project_path("demo.py") == parent / "demo.py"
