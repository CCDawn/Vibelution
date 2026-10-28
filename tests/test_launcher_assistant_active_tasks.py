"""Target transport, native index and SDK task-read authorization."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes import launcher_assistant_management as route
    from core.web.services import runtime_task_registry as registry
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    import vibelution_storage

    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(registry, "PROJECT_ROOT", root)
    monkeypatch.setattr(vibelution_storage, "resolve_project_runtime_home", lambda project: tmp_path / "runtime")
    native = NativeAgentGateway(root)
    monkeypatch.setattr(native, "_owners", lambda: None)
    store = registry.store_for(tmp_path / "runtime" / registry.STORE_DIR_NAME)
    binding = {"projectId": "project", "instanceId": "instance"}
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(binding, "authority"), native=native)
    monkeypatch.setattr(route, "_SERVICE", service)
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        yield SimpleNamespace(root=root, store=store, service=service, binding=binding, client=client, native=native)


def _connect(sdk, env, monkeypatch):
    from core.external_agent.backend_client import BackendClientError
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes.launcher_assistant_management import CAPABILITY_HEADER, SUBJECT_HEADER

    async def request(method, path, **kwargs):
        headers = {CONTROL_TOKEN_HEADER: get_control_token()}
        if kwargs.get("management_auth"):
            subject, capability = kwargs["management_auth"]
            headers.update({SUBJECT_HEADER: subject, CAPABILITY_HEADER: capability})
        response = env.client.request(method, path.removeprefix("/api"), headers=headers, json=kwargs.get("json_payload"))
        if response.status_code >= 400:
            raise BackendClientError("target refused request", code=response.json()["detail"]["code"])
        return response.json()
    monkeypatch.setattr(sdk, "_request_json", request)


def _register(env, task_id):
    from core.web.services import runtime_task_registry as registry
    snapshot = registry.new_snapshot(kind="cli_agent", task_id=task_id, status="running", label="secret C:/private/path",
                                     output="secret conversation")
    env.store.save_state(snapshot)


@pytest.mark.anyio
async def test_native_sdk_action_requires_explicit_scope_and_keeps_original_subject(env, tmp_path, monkeypatch):
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.assistant_runtime.management import ManagementAdapter
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError, _LEGACY_MANAGEMENT_SCOPES
    from tests.test_assistant_runtime_actions import _through_native_model_budget

    _register(env, "task-a")
    _register(env, "task-b")
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    sdk._state["management"] = {"clientId": "original_client_1234567890", "binding": env.binding, "scopes": _LEGACY_MANAGEMENT_SCOPES}
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=True)
    before = deepcopy(sdk._state["management"])
    async def call(project, operation):
        assert project == "project"
        return await operation(sdk)
    manager = ManagementAdapter(tmp_path / "profile", {"project": env.root}, call)
    service = SimpleNamespace(management=manager, project_ids=lambda: ["project"])
    bind_actions(service, asyncio.get_running_loop())
    try:
        with pytest.raises(BackendClientError, match="target refused") as denied:
            await asyncio.to_thread(execute_action, "task_list", {"project_id": "project"})
        assert denied.value.code == "SCOPE_DENIED"
        assert sdk._state["management"] == before
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "task_list", {"project_id": "other"})
        args = {"project_id": "project", "request_id": "grant-tasks", "expected_scopes": _LEGACY_MANAGEMENT_SCOPES, "add_scopes": ["tasks:read"]}
        assert (await asyncio.to_thread(execute_action, "authorization_upgrade", args))["status"] == "approval_required"
        assert sdk._state["management"] == before
        receipt = await asyncio.to_thread(execute_action, "authorization_upgrade", args, governed=True)
        assert receipt["authorization"]["addedScopes"] == ["tasks:read"]
        assert sdk._state["management"]["subjectId"] == grant["subjectId"]
        page = await asyncio.to_thread(execute_action, "task_list", {"project_id": "project", "limit": 1})
        assert page["tasks"][0]["taskId"] == "task-a" and page["nextOffset"] == 1
        assert "active index only" in page["coverage"]
        assert page["indexCompleteness"] == "unknown" and "may omit active tasks" in page["coverage"]
        assert "secret" not in json.dumps(page) and "private" not in json.dumps(page)
        assert (await sdk.management_active_tasks(offset=1, limit=1))["tasks"][0]["taskId"] == "task-b"
        raw, outcome, facts, rendered = _through_native_model_budget(page)
        assert outcome is None and not facts.truncated and json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        description = await asyncio.to_thread(execute_action, "describe", {"action": "task_list"})
        raw, outcome, facts, rendered = _through_native_model_budget(description)
        assert outcome is None and not facts.truncated and "tasks:read" in raw
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_index_rebuilt_after_corruption_may_omit_active_tasks(env, tmp_path, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient
    _register(env, "task-a")
    env.store.index_path.write_text("{", encoding="utf-8")
    _register(env, "task-b")
    assert env.store.load_state("task-a")["status"] == "running"
    assert env.store.active_task_ids() == ["task-b"]
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    original = await sdk._management_grant(require_existing=False)
    await sdk.management_action(action="authorization_upgrade", request_id="grant-tasks", parameters={
        "expected_scopes": original["scopes"], "add_scopes": ["tasks:read"]})
    page = await sdk.management_active_tasks()
    assert [row["taskId"] for row in page["tasks"]] == ["task-b"]
    assert page["total"] == 1 and page["indexCompleteness"] == "unknown"
    assert "may omit active tasks" in page["coverage"] and "total counts indexed tasks only" in page["coverage"]
    env.store.index_path.write_text('{"schemaVersion":1,"activeTaskIds":[]}', encoding="utf-8")
    empty = await sdk.management_active_tasks()
    assert empty["tasks"] == [] and empty["total"] == 0 and empty["indexCompleteness"] == "unknown"
    assert "may omit active tasks" in empty["coverage"]


@pytest.mark.anyio
async def test_unsupported_old_target_preserves_normal_binding(env, tmp_path, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    from core.web.services.external_management.service import ManagementError
    owner = env.service._authorization_upgrades()
    original_invoke = owner.invoke
    def old_invoke(*args, **kwargs):
        if "tasks:read" in kwargs.get("add_scopes", []):
            raise ManagementError("INVALID_INPUT", 422)
        return original_invoke(*args, **kwargs)
    monkeypatch.setattr(owner, "invoke", old_invoke)
    monkeypatch.setattr(env.service, "_authorization_upgrades", lambda: owner)
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    saved = deepcopy(sdk._state["management"])
    assert "tasks:read" not in saved["scopes"]
    with pytest.raises(BackendClientError) as error:
        await sdk.management_action(action="authorization_upgrade", request_id="grant-tasks", parameters={
            "expected_scopes": saved["scopes"], "add_scopes": ["tasks:read"]})
    assert error.value.code == "INVALID_INPUT" and sdk._state["management"] == saved
    assert (await sdk._management_grant(require_existing=True))["subjectId"] == grant["subjectId"]
    assert "tasks:read" not in env.service.binding()["scopes"]


@pytest.mark.parametrize("damage", ["missing-index", "broken-index", "duplicate-index", "missing-snapshot", "terminal-snapshot", "bad-kind", "duplicate-snapshot", "hardlink", "oversized", "wrong-root"])
def test_target_rejects_unavailable_or_inconsistent_source(env, damage):
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes.launcher_assistant_management import SUBJECT_HEADER, CAPABILITY_HEADER
    _register(env, "task-a")
    grant = env.service.bind({"client_id": "task-reader", "expected_binding": env.binding, "scopes": ["tasks:read"]})
    if damage == "missing-index":
        env.store.index_path.unlink()
    elif damage == "broken-index":
        env.store.index_path.write_text("{}", encoding="utf-8")
    elif damage == "duplicate-index":
        env.store.index_path.write_text('{"schemaVersion": 1, "activeTaskIds": [], "activeTaskIds": ["task-a"]}', encoding="utf-8")
    elif damage == "missing-snapshot":
        env.store.task_state_path("task-a").unlink()
    elif damage == "duplicate-snapshot":
        path = env.store.task_state_path("task-a")
        row = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(row)[:-1] + ', "status":"running"}', encoding="utf-8")
    elif damage == "hardlink":
        import os
        os.link(env.store.task_state_path("task-a"), env.root / "other-link.json")
    elif damage == "oversized":
        env.store.task_state_path("task-a").write_bytes(b" " * 1_000_001)
    elif damage in {"terminal-snapshot", "bad-kind"}:
        path = env.store.task_state_path("task-a")
        row = json.loads(path.read_text(encoding="utf-8"))
        row["status" if damage == "terminal-snapshot" else "kind"] = "completed" if damage == "terminal-snapshot" else "corrupt"
        path.write_text(json.dumps(row), encoding="utf-8")
    else:
        env.native.project_root = env.root / "other"
    response = env.client.get("/v1/launcher-assistant-management/active-tasks", headers={CONTROL_TOKEN_HEADER: get_control_token(),
        SUBJECT_HEADER: grant["subject_id"], CAPABILITY_HEADER: grant["subject_capability"]})
    assert response.status_code == (409 if damage == "wrong-root" else 503)


def test_main_query_uses_bounded_handle_reads_without_registry_unbounded_reader(env, monkeypatch):
    from core.assistant_runtime import migration_io
    from core.web.services.external_management.contracts import ActiveTasksQuery
    _register(env, "task-a")
    monkeypatch.setattr(env.store, "active_task_states", lambda: pytest.fail("unbounded reader used"))
    original = migration_io.read_stable_file
    calls = []
    def bounded(path, max_bytes, **kwargs):
        calls.append((path.name, max_bytes))
        return original(path, max_bytes, **kwargs)
    monkeypatch.setattr(migration_io, "read_stable_file", bounded)
    result = env.native.read_active_tasks(ActiveTasksQuery())
    assert result["tasks"][0]["taskId"] == "task-a"
    assert calls == [("_index.json", 1_000_000), ("task-a.json", 1_000_000), ("_index.json", 1_000_000)]


def test_snapshot_growth_between_stat_and_open_is_rejected(env, monkeypatch):
    import os
    if os.name != "nt":
        pytest.skip("Windows verified-handle race check")
    from core.web.services.external_management.contracts import ActiveTasksQuery
    from core.web.services.external_management.service import ManagementError
    from core.web.services.personal_assistant_project import windows_read
    _register(env, "task-a")
    original = windows_read.read_source_bytes
    def grows(root, path, budget):
        if path.name == "task-a.json":
            path.write_bytes(b" " * (budget + 1))
        return original(root, path, budget)
    monkeypatch.setattr(windows_read, "read_source_bytes", grows)
    with pytest.raises(ManagementError) as error:
        env.native.read_active_tasks(ActiveTasksQuery())
    assert error.value.code == "TASK_INDEX_UNAVAILABLE"


def test_junction_store_is_rejected(env, monkeypatch):
    import os
    import subprocess
    if os.name != "nt":
        pytest.skip("Windows junction check")
    from core.web.services import runtime_task_registry as registry
    from core.web.services.external_management.contracts import ActiveTasksQuery
    from core.web.services.external_management.service import ManagementError
    _register(env, "task-a")
    junction = env.root / "junction"
    result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J", str(junction), str(env.store.root)],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode:
        pytest.skip("Windows junction creation unavailable")
    monkeypatch.setattr(registry, "store_for", lambda _: registry.RuntimeTaskStore(junction))
    with pytest.raises(ManagementError) as error:
        env.native.read_active_tasks(ActiveTasksQuery())
    assert error.value.code == "TASK_INDEX_UNAVAILABLE"


def test_http_control_capability_scope_and_query_are_enforced(env):
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes.launcher_assistant_management import SUBJECT_HEADER, CAPABILITY_HEADER
    _register(env, "task-a")
    grant = env.service.bind({"client_id": "task-reader", "expected_binding": env.binding, "scopes": ["tasks:read"]})
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), SUBJECT_HEADER: grant["subject_id"], CAPABILITY_HEADER: grant["subject_capability"]}
    base = "/v1/launcher-assistant-management/active-tasks"
    assert env.client.get(base, headers={SUBJECT_HEADER: grant["subject_id"], CAPABILITY_HEADER: grant["subject_capability"]}).status_code == 403
    assert env.client.get(base, headers={**headers, CAPABILITY_HEADER: "z" * 48}).status_code == 403
    for query in ("?limit=7", "?offset=1&offset=2", "?path=x", "?offset=-1"):
        assert env.client.get(base + query, headers=headers).status_code == 422
