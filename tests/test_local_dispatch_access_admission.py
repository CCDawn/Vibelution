"""Local authority stays independent while target deny and queued admission agree."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from threading import Event

import pytest

from core.web.services.external_agent.service import ExternalAgentAccessError
from core.web.services.external_management.service import ManagementError
from core.web.services.local_assistant.service import build_local_service
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_external_agent_task_service import FakeRuntime, _agent, _service
from tests.test_external_management_dispatch_access import env, metadata_env, parameters, marker


def local_service(env):
    # The entire existing third-party policy remains disabled/restricted.
    text = env.config.read_text().replace("enabled=true", "enabled=false")
    text = text.replace('denied_agent_ids=["ordinary","blocked"]', 'denied_agent_ids=["blocked"]')
    env.config.write_text(text)
    service = build_local_service(env.root)
    runtime = FakeRuntime(agents=[_agent("ordinary")])
    service.dependencies = _service(env.root / "injected", runtime).dependencies
    authority = {"fingerprint": "a" * 64}
    service.authority_fingerprint = lambda: authority["fingerprint"]
    workspace = env.root / "fixture-worktree"
    workspace.mkdir()
    service.workspace_factory = lambda _task_id: workspace
    return service, runtime, authority


def start(service):
    return service.start_task(owner_id="fixture-local-owner", adapter_connection_id="fixture-local-connection",
        capabilities=set(), agent_id="ordinary", task="fixture task", permission_profile="workspace_write",
        client_request_id="original-local-request", title="fixture", runtime_revision="fixture-revision")


def test_default_local_admission_does_not_use_mcp_disabled_allowlist_or_ceiling(env):
    from config.settings import get_config
    service, runtime, _authority = local_service(env)
    third_party = get_config().external_agent_gateway
    assert not third_party.enabled and "ordinary" not in third_party.allowed_agent_ids
    assert third_party.permission_ceiling == "read_only"
    result = start(service)
    assert result["status"] == "running" and result["effectivePermissionProfile"] == "workspace_write"
    assert service.store.get_task(result["taskId"])["localAuthorityFingerprint"] == "a" * 64
    assert service.request_authority_fingerprint == "a" * 64
    assert runtime.submit_calls and not runtime.stop_calls
    assert not (env.root / ".runtime/external_agents/tasks").exists()


def test_old_local_service_rechecks_target_deny_after_native_config_reload(env):
    service, runtime, _authority = local_service(env)
    assert "ordinary" not in service.denied_agent_ids
    with server_operator_scope("fixture-operator", roles=("operator",)):
        args = parameters(env, False)
        env.control.set(args, marker(args))
    with pytest.raises(ExternalAgentAccessError) as failure:
        start(service)
    assert failure.value.code == "AGENT_NOT_FOUND"
    assert "ordinary" in service.denied_agent_ids
    assert not runtime.create_calls and not service.store.tasks_dir.exists()


def test_local_queued_admission_blocks_disable_before_session_exists(env, monkeypatch):
    service, runtime, _authority = local_service(env)
    with server_operator_scope("fixture-operator", roles=("operator",)):
        args = parameters(env, False)
    eligible, release, disable_attempt = Event(), Event(), Event()
    create = service.store.create_task
    def pause(**kwargs):
        eligible.set()
        assert release.wait(3)
        return create(**kwargs)
    monkeypatch.setattr(service.store, "create_task", pause)
    monkeypatch.setattr(service, "_start_native_task", lambda record, **_kwargs: record)
    original = env.config.read_bytes()
    def disable():
        disable_attempt.set()
        with server_operator_scope("fixture-operator", roles=("operator",)):
            return env.control.set(args, marker(args))
    with ThreadPoolExecutor(max_workers=2) as pool:
        queued = pool.submit(start, service)
        assert eligible.wait(3)
        stopping = pool.submit(disable)
        assert disable_attempt.wait(3) and not stopping.done()
        release.set()
        task = queued.result(timeout=3)
        with pytest.raises(ManagementError, match="AGENT_BUSY"):
            stopping.result(timeout=3)
    assert task["status"] == "queued" and not task["sessionId"]
    assert service.store.get_task(task["taskId"])["status"] == "queued"
    assert env.config.read_bytes() == original and not runtime.stop_calls


@pytest.mark.parametrize("change", ["authority", "deny"])
def test_local_waiting_for_lifecycle_rechecks_fresh_principal_and_target_policy(env, monkeypatch, change):
    from core.web.services import agent_directory_service as directory
    service, runtime, authority = local_service(env)
    service.request_authority_fingerprint = "a" * 64
    attempting = Event()
    @contextmanager
    def admission(**_kwargs):
        attempting.set()
        with env.life_lock:
            yield
    monkeypatch.setattr(directory, "agent_session_lifecycle_transaction", admission)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with env.life_lock:
            pending = pool.submit(start, service)
            assert attempting.wait(3) and not pending.done()
            if change == "authority":
                authority["fingerprint"] = "b" * 64
            else:
                with server_operator_scope("fixture-operator", roles=("operator",)):
                    args = parameters(env, False)
                    env.control.set(args, marker(args))
        with pytest.raises(ExternalAgentAccessError) as failure:
            pending.result(timeout=3)
    assert failure.value.code == ("LOCAL_ASSISTANT_DISABLED" if change == "authority" else "AGENT_NOT_FOUND")
    assert not service.store.tasks_dir.exists() and not runtime.create_calls


@pytest.mark.parametrize("status", ["queued", "running", "awaiting_approval", "stop_unconfirmed", "unknown"])
def test_disable_reads_nonterminal_local_namespace_without_cancel_or_refresh(env, status):
    folder = env.root / ".runtime/local_assistant_tasks/tasks"
    folder.mkdir(parents=True)
    path = folder / "eat-local.json"
    payload = {"taskId": "eat-local", "agentId": "ordinary", "status": status, "sessionId": ""}
    path.write_text(json.dumps(payload))
    original = env.config.read_bytes()
    with server_operator_scope("fixture-operator", roles=("operator",)):
        args = parameters(env, False)
        with pytest.raises(ManagementError, match="AGENT_BUSY"):
            env.control.set(args, marker(args))
    assert env.config.read_bytes() == original and json.loads(path.read_text()) == payload


@pytest.mark.parametrize("state", ["corrupt", "incomplete", "missing_agent"])
def test_disable_refuses_uncertain_local_namespace(env, monkeypatch, state):
    from core.web.services.external_management import runtime_operations
    folder = env.root / ".runtime/local_assistant_tasks/tasks"
    folder.mkdir(parents=True)
    path = folder / "eat-local.json"
    if state == "corrupt": path.write_text("{broken")
    elif state == "missing_agent": path.write_text(json.dumps({"taskId": "eat-local", "status": "queued"}))
    else: monkeypatch.setattr(runtime_operations, "_scan", lambda *_args, **_kwargs: ([], False))
    original = env.config.read_bytes()
    with server_operator_scope("fixture-operator", roles=("operator",)):
        args = parameters(env, False)
        with pytest.raises(ManagementError, match="STATE_UNAVAILABLE"):
            env.control.set(args, marker(args))
    assert env.config.read_bytes() == original


def test_terminal_local_target_and_active_other_agent_do_not_block_or_change_other_work(env):
    folder = env.root / ".runtime/local_assistant_tasks/tasks"
    folder.mkdir(parents=True)
    snapshots = [({"taskId": "eat-finished", "agentId": "ordinary", "status": "succeeded"}),
                 ({"taskId": "eat-foreign", "agentId": "another-agent", "status": "running"})]
    for row in snapshots: (folder / (row["taskId"] + ".json")).write_text(json.dumps(row))
    before = {path: path.read_bytes() for path in folder.iterdir()}
    with server_operator_scope("fixture-operator", roles=("operator",)):
        args = parameters(env, False)
        assert env.control.set(args, marker(args))["verified"] is True
    assert {path: path.read_bytes() for path in folder.iterdir()} == before
