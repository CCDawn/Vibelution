"""Native queued admission and access revocation share Life without cancellation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json

import pytest

from core.web.services.external_agent.service import build_default_service, ExternalAgentAccessError
from core.web.services.external_agent.store import ExternalAgentTaskStore
from core.web.services.external_management.service import ManagementError
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_external_management_dispatch_access import env, metadata_env, parameters, marker
from tests.test_external_agent_task_service import FakeRuntime, _agent, _service


def enabled(env):
    with server_operator_scope("test-operator", roles=("operator",)):
        args = parameters(env)
        env.control.set(args, marker(args))


def native_service(env):
    service = build_default_service(env.root)
    runtime = FakeRuntime(agents=[_agent("ordinary")])
    service.dependencies = _service(env.root / "injected", runtime).dependencies
    return service, runtime


def start(service):
    return service.start_task(owner_id="fixture-owner", adapter_connection_id="fixture-adapter", capabilities=set(),
        agent_id="ordinary", task="fixture task", permission_profile="read_only", client_request_id="one-original",
        title="fixture", runtime_revision="fixture-revision")


def test_old_default_service_rechecks_current_gateway_after_reload(env):
    enabled(env)
    service, runtime = native_service(env)
    assert "ordinary" in service.allowed_agent_ids and "ordinary" not in service.denied_agent_ids
    with server_operator_scope("test-operator", roles=("operator",)):
        args = parameters(env, False)
        env.control.set(args, marker(args, "d" * 64))
    with pytest.raises(ExternalAgentAccessError) as failure:
        start(service)
    assert failure.value.code == "AGENT_NOT_FOUND"
    assert not service.store.tasks_dir.exists() and not runtime.create_calls and not runtime.stop_calls


def test_eligibility_to_durable_queue_window_cannot_be_missed_by_disable(env, monkeypatch):
    enabled(env)
    service, runtime = native_service(env)
    with server_operator_scope("test-operator", roles=("operator",)):
        args = parameters(env, False)
    reached, release, disable_attempt = Event(), Event(), Event()
    create = service.store.create_task
    def pause_before_durable(**kwargs):
        reached.set()
        assert release.wait(3)
        return create(**kwargs)
    monkeypatch.setattr(service.store, "create_task", pause_before_durable)
    monkeypatch.setattr(service, "_start_native_task", lambda record, **_kwargs: record)
    def disable():
        disable_attempt.set()
        with server_operator_scope("test-operator", roles=("operator",)):
            return env.control.set(args, marker(args, "d" * 64))
    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = pool.submit(start, service)
        assert reached.wait(3)
        stopping_access = pool.submit(disable)
        assert disable_attempt.wait(3) and not stopping_access.done()
        release.set()
        task = admitted.result(timeout=3)
        with pytest.raises(ManagementError, match="AGENT_BUSY"):
            stopping_access.result(timeout=3)
    assert service.store.get_task(task["taskId"])["status"] == "queued"
    assert not runtime.stop_calls and not runtime.submit_calls
    with server_operator_scope("test-operator", roles=("operator",)):
        assert env.control.read("ordinary")["operatorEnabled"] is True


@pytest.mark.parametrize("status", ["queued", "running", "stopping", "unknown"])
def test_disable_rejects_active_or_unknown_native_session_without_mutation(env, status):
    env.session_rows[0]["last_turn_status"] = status
    original = env.config.read_bytes()
    with server_operator_scope("test-operator", roles=("operator",)):
        args = parameters(env, False)
        with pytest.raises(ManagementError, match="AGENT_BUSY"):
            env.control.set(args, marker(args))
    assert env.config.read_bytes() == original and not (env.config.parent / "backups").exists()


@pytest.mark.parametrize("state", ["suspicious_work", "incomplete_tasks", "corrupt_task", "stop_unconfirmed", "missing_session"])
def test_disable_cannot_treat_incomplete_or_unsettled_native_task_authority_as_idle(env, monkeypatch, state):
    from core.web.services.external_management import runtime_operations
    folder = env.root / ".runtime/external_agents/tasks"
    folder.mkdir(parents=True)
    if state == "suspicious_work": env.suspicious_work_index = True
    elif state == "missing_session": env.session_rows.clear()
    elif state == "incomplete_tasks": monkeypatch.setattr(runtime_operations, "_external_tasks", lambda _native: ([], False))
    elif state == "corrupt_task": (folder / "eat-corrupt.json").write_text("{broken")
    else:
        (folder / "eat-unsettled.json").write_text(json.dumps({"taskId": "eat-unsettled", "agentId": "ordinary", "status": "stop_unconfirmed"}))
    original = env.config.read_bytes()
    with server_operator_scope("test-operator", roles=("operator",)):
        args = parameters(env, False)
        with pytest.raises(ManagementError) as failure:
            env.control.set(args, marker(args))
        assert failure.value.code == ("STATE_UNAVAILABLE" if state in {"incomplete_tasks", "corrupt_task", "missing_session"} else "AGENT_BUSY")
    assert env.config.read_bytes() == original and not (env.config.parent / "backups").exists()


def test_custom_injected_service_keeps_original_contract_without_native_config_io(tmp_path, monkeypatch):
    from config import settings
    def forbidden(*args, **kwargs): pytest.fail("custom service entered native config owner")
    monkeypatch.setattr(settings, "get_config", forbidden)
    service = _service(tmp_path, FakeRuntime(agents=[_agent("ordinary")]))
    assert start(service)["status"] == "running"


def test_metadata_writer_state_then_fence_and_access_commit_share_existing_lock_order(env):
    from core.infrastructure.model_reference_fence import commit_reference_metadata
    from core.infrastructure.atomic_io import atomic_write_json
    state_held, access_started = Event(), Event()
    with server_operator_scope("test-operator", roles=("operator",)):
        args = parameters(env)
    def writer():
        with env.directory._STATE_LOCK:
            state_held.set()
            assert access_started.wait(3)
            payload = json.loads(env.agents_path.read_text())
            payload["agents"][1]["displayName"] = "Unrelated metadata update"
            commit_reference_metadata(env.agents_path, payload, surface="agents",
                write=lambda: atomic_write_json(env.agents_path, payload, strict_replace=True))
    def change_access():
        assert state_held.wait(3)
        access_started.set()
        with server_operator_scope("test-operator", roles=("operator",)):
            return env.control.set(args, marker(args))
    with ThreadPoolExecutor(max_workers=2) as pool:
        updating = pool.submit(writer)
        change = pool.submit(change_access)
        updating.result(timeout=5)
        assert change.result(timeout=5)["verified"] is True
    assert json.loads(env.agents_path.read_text())["agents"][1]["displayName"] == "Unrelated metadata update"


def test_deletion_fence_snapshot_never_acquires_metadata_state_while_access_waits(env, monkeypatch):
    from contextlib import contextmanager
    from core.infrastructure import model_reference_fence as fence
    from core.assistant_runtime.migration_io import read_stable_file, strict_json
    acquired, access_waiting = Event(), Event()
    original_fence = fence.model_reference_fence
    @contextmanager
    def observed_fence(*args, **kwargs):
        access_waiting.set()
        with original_fence(*args, **kwargs) as lease:
            yield lease
    monkeypatch.setattr(fence, "model_reference_fence", observed_fence)
    with server_operator_scope("test-operator", roles=("operator",)):
        args = parameters(env)
    def deleting_snapshot():
        with original_fence(env.config):
            acquired.set()
            assert access_waiting.wait(3)
            # The deletion owner intentionally performs only metadata snapshot
            # reads while holding Fence, never State/Store or a queued writer.
            return strict_json(read_stable_file(env.agents_path, 1024 * 1024).raw)["agents"][0]["agentId"]
    def change_access():
        assert acquired.wait(3)
        with server_operator_scope("test-operator", roles=("operator",)):
            return env.control.set(args, marker(args))
    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshot = pool.submit(deleting_snapshot)
        change = pool.submit(change_access)
        assert snapshot.result(timeout=5) == "ordinary"
        assert change.result(timeout=5)["verified"] is True
