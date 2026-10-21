"""Kernel audit and delivery must retain the owning project's identity."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from core.agent_kernel import service as kernel
from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service as directory
from core.web.services import session_service
from core.web.services.session import turn_diagnostics
from tests.test_agent_kernel import _create_agent, _kernel_event
from tests.test_session_repair_store_root_guard import _write_identity
from vibelution_storage import PROJECTS_HOME_ENV


@pytest.fixture
def trace_env(tmp_path, monkeypatch):
    root = tmp_path / "native-project"
    monkeypatch.setattr(kernel, "PROJECT_ROOT", tmp_path / "kernel-default")
    monkeypatch.setattr(directory, "PROJECT_ROOT", tmp_path / "directory-default")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", root)
    monkeypatch.setattr(session_service, "_record_direct_session_submit_kernel_trace_event", lambda *a, **k: None)
    monkeypatch.setattr(developer_sandbox, "route_workspace_path", lambda root, surface, *parts, **k: Path(root).joinpath(*parts))
    seen = []

    def handle(_payload):
        seen.append(kernel._kernel_root().parent)
        return {"task": {"taskId": "trace-task", "status": "succeeded"}}

    monkeypatch.setattr(kernel, "handle_kernel_event", handle)
    return root, seen


def _trace(**kwargs):
    return turn_diagnostics._create_direct_session_submit_kernel_trace(
        {"id": "session-a", "agent_id": "agent-a"},
        agent={"agentId": "agent-a", "directSessionId": "session-a"},
        turn_id="turn-a", message="audit this turn", source="user", **kwargs,
    )


def test_trace_uses_native_project_without_changing_service_roots(trace_env):
    root, seen = trace_env
    before = (kernel.PROJECT_ROOT, directory.PROJECT_ROOT, session_service.PROJECT_ROOT)

    assert _trace()["status"] == "recorded"

    assert seen == [root]
    assert (kernel.PROJECT_ROOT, directory.PROJECT_ROOT, session_service.PROJECT_ROOT) == before


def test_deferred_trace_freezes_root_at_enqueue(trace_env, monkeypatch, tmp_path):
    root, seen = trace_env
    callbacks = []
    monkeypatch.setattr(session_service, "_SESSION_CYCLE_PROJECTION_EXECUTOR", SimpleNamespace(submit=lambda fn: callbacks.append(fn)))
    turn_diagnostics._enqueue_direct_session_submit_kernel_trace(
        {"id": "session-a", "agent_id": "agent-a"},
        agent={"agentId": "agent-a"}, turn_id="turn-a", message="audit", source="user",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path / "later-project")

    assert callbacks[0]()["status"] == "recorded"
    assert seen == [root]


def test_trace_scope_restores_after_failure(trace_env, monkeypatch, tmp_path):
    outer = tmp_path / "outer-project"
    monkeypatch.setattr(kernel, "handle_kernel_event", lambda _: (_ for _ in ()).throw(RuntimeError("audit unavailable")))
    with kernel.scoped_project_root(outer):
        assert _trace()["status"] == "failed"
        assert kernel._kernel_root().parent == outer
    assert kernel._kernel_root().parent == kernel.PROJECT_ROOT


def test_concurrent_trace_roots_are_isolated(trace_env, monkeypatch, tmp_path):
    barrier = Barrier(2)
    roots = [tmp_path / "project-a", tmp_path / "project-b"]

    def handle(_):
        before = kernel._kernel_root().parent
        barrier.wait(timeout=10)
        assert kernel._kernel_root().parent == before
        return {"task": {"taskId": str(before)}}

    monkeypatch.setattr(kernel, "handle_kernel_event", handle)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda root: _trace(project_root=root), roots))
    assert [row["taskId"] for row in results] == [str(root) for root in roots]
    assert kernel._kernel_root().parent == kernel.PROJECT_ROOT


@pytest.mark.parametrize("operation", ["list", "ack"])
def test_inbox_operations_scope_directory_without_mutating_its_root(trace_env, monkeypatch, operation):
    root, _ = trace_env
    default = directory.PROJECT_ROOT
    observed = []

    def observe(value):
        observed.append(directory._active_project_root())
        return value

    monkeypatch.setattr(directory, "get_agent", lambda _: observe({"agentId": "agent-a"}))
    monkeypatch.setattr(directory, "list_agent_inbox_messages_for_agent", lambda *a, **k: observe([]))
    monkeypatch.setattr(directory, "count_agent_inbox_messages_for_agent", lambda *a, **k: observe(0))
    monkeypatch.setattr(directory, "consume_agent_inbox_message", lambda *a, **k: observe({"messageId": "m-a", "targetAgentId": "agent-a"}))
    with kernel.scoped_project_root(root):
        if operation == "list":
            kernel.list_agent_inbox("agent-a")
        else:
            kernel.ack_agent_inbox_message("agent-a", "m-a")
    assert observed and all(item == root for item in observed)
    assert directory.PROJECT_ROOT == default
    assert directory._active_project_root() == default


@pytest.mark.parametrize("wake,target", [(True, ""), (False, "session-other"), (False, "")])
def test_delivery_rejects_native_root_mismatch_before_inbox_write(trace_env, monkeypatch, tmp_path, wake, target):
    root = tmp_path / "other-project"
    writes = []
    native_calls = []
    defaults = (kernel.PROJECT_ROOT, directory.PROJECT_ROOT, session_service.PROJECT_ROOT)
    monkeypatch.setattr(directory, "write_agent_inbox_message", lambda *a, **k: writes.append(directory._active_project_root()) or {"messageId": "m-a"})
    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", lambda *a, **k: native_calls.append("wake"))
    monkeypatch.setattr(session_service, "_append_session_conversation_event", lambda *a, **k: native_calls.append("append"))
    event = kernel._normalize_event({
        "sender": {"type": "user", "id": "user"}, "recipientAgentIds": ["agent-a"],
        "semanticType": "agent.message", "payload": {"content": "complete body"},
        "wakeTarget": wake, "metadata": {"targetSessionId": target},
    })
    with kernel.scoped_project_root(root):
        deliveries = kernel._deliver_event_to_recipients(event, kernel._create_task(event))
    if wake or target:
        assert deliveries[0]["status"] == "failed"
        assert "project root" in deliveries[0]["reason"].lower()
        assert writes == []
    else:
        assert deliveries[0]["status"] == "delivered"
        assert writes == [root]
    assert native_calls == []
    assert (kernel.PROJECT_ROOT, directory.PROJECT_ROOT, session_service.PROJECT_ROOT) == defaults


def test_real_trace_then_delivery_keeps_formal_registry(tmp_path, monkeypatch):
    root = tmp_path / "identified-project"
    root.mkdir()
    _write_identity(root, "kernel-project-identity")
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(tmp_path / "projects-home"))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "fake-user"))
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "missing-config.toml"))
    for module in (kernel, directory, session_service, developer_sandbox):
        monkeypatch.setattr(module, "PROJECT_ROOT", root)
    monkeypatch.setattr(session_service, "_record_direct_session_submit_kernel_trace_event", lambda *a, **k: None)
    fallback = developer_sandbox.resolve_workspace_home()
    agent = _create_agent()
    agent_id = agent["agentId"]

    trace = turn_diagnostics._create_direct_session_submit_kernel_trace(
        {"id": "native-session", "agent_id": agent_id}, agent={"agentId": agent_id},
        turn_id="native-turn", message="trace before delivery", source="user",
    )
    result = kernel.handle_kernel_event(_kernel_event(agent_id))

    assert trace["status"] == "recorded"
    assert result["task"]["status"] == "succeeded"
    assert directory.get_agent(agent_id)["agentId"] == agent_id
    assert directory.registry_path().is_relative_to(tmp_path / "projects-home")
    assert kernel._kernel_root().is_relative_to(tmp_path / "projects-home")
    assert kernel.get_kernel_task(trace["taskId"])["taskId"] == trace["taskId"]
    assert len(directory.list_agent_inbox_messages_for_agent(agent_id, status="")) == 1
    assert not (fallback / "agent_kernel" / "index.json").exists()
    assert all(module.PROJECT_ROOT == root for module in (kernel, directory, session_service))
