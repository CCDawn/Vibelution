"""Bound target checkout reads through the SDK, without initializing target data."""
import asyncio
import json
import os
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows verified source reader")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes import launcher_assistant_management as route
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    root = tmp_path / "project"
    (root / "core").mkdir(parents=True)
    (root / "core" / "sample.py").write_text('api_key = "secret-value"\nprint("needle")\n', encoding="utf-8")
    binding = {"projectId": "project", "instanceId": "instance"}
    monkeypatch.setattr(directory, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(binding, "authority"), native=NativeAgentGateway(root))
    monkeypatch.setattr(route, "_SERVICE", service)
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        yield SimpleNamespace(root=root, service=service, binding=binding, client=client)


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


@pytest.mark.anyio
async def test_action_sdk_target_scope_and_bounded_reads(env, tmp_path, monkeypatch):
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.assistant_runtime.management import ManagementAdapter
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    before = deepcopy(sdk._state["management"])
    assert "source:read" not in before["scopes"] and "source:read" not in env.service.binding()["scopes"]
    async def call(project, operation):
        assert project == "project"
        return await operation(sdk)
    manager = ManagementAdapter(tmp_path / "profile", {"project": env.root}, call)
    service = SimpleNamespace(management=manager, project_ids=lambda: ["project"])
    bind_actions(service, asyncio.get_running_loop())
    try:
        with pytest.raises(BackendClientError) as denied:
            await asyncio.to_thread(execute_action, "source_read", {"project_id": "project", "path": "core/sample.py"})
        assert denied.value.code == "SCOPE_DENIED" and sdk._state["management"] == before
        args = {"project_id": "project", "request_id": "grant-source", "expected_scopes": before["scopes"], "add_scopes": ["source:read"]}
        assert (await asyncio.to_thread(execute_action, "authorization_upgrade", args))["status"] == "approval_required"
        receipt = await asyncio.to_thread(execute_action, "authorization_upgrade", args, governed=True)
        assert receipt["authorization"]["addedScopes"] == ["source:read"]
        assert sdk._state["management"]["subjectId"] == grant["subjectId"]
        tree_before = {str(path): path.read_bytes() for path in env.root.rglob("*") if path.is_file()}
        result = await asyncio.to_thread(execute_action, "source_read", {"project_id": "project", "path": "core/sample.py"})
        assert "secret-value" not in result["text"] and "REDACTED_CREDENTIAL" in result["text"]
        assert result["untrustedContent"] is True and "other secrets may remain" in result["redaction"]
        page = await asyncio.to_thread(execute_action, "source_search", {"project_id": "project", "path": "core", "query": "needle"})
        assert page["items"][0]["path"] == "core/sample.py" and page["partial"] is True
        for payload in (result, page, await asyncio.to_thread(execute_action, "describe", {"action": "source_search"})):
            raw, outcome, facts, rendered = _through_native_model_budget(payload)
            assert outcome is None and not facts.truncated and json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        assert tree_before == {str(path): path.read_bytes() for path in env.root.rglob("*") if path.is_file()}
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "source_read", {"project_id": "other", "path": "core/sample.py"})
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_search_cursor_covers_unfiltered_candidates_without_skipping_matches(env, tmp_path, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient
    for index in range(18):
        (env.root / "core" / f"a{index:02}.py").write_text("needle\n", encoding="utf-8")
    (env.root / "core" / "a00.json").write_text('{"secret":"needle"}', encoding="utf-8")
    (env.root / "core" / "a01-token.py").write_text("needle PRIVATE\n", encoding="utf-8")
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    await sdk.management_action(action="authorization_upgrade", request_id="grant-source", parameters={"expected_scopes": grant["scopes"], "add_scopes": ["source:read"]})
    offset, paths = 0, []
    for _ in range(10):
        page = await sdk.management_source("search", path="core", query="needle", offset=offset)
        paths.extend(row["path"] for row in page["items"])
        assert page["partial"] is True and len(page["items"]) <= 6
        if page["nextOffset"] is None:
            break
        assert page["nextOffset"] == offset + page["examinedCandidates"] and page["nextOffset"] > offset
        offset = page["nextOffset"]
    assert set(paths) == {f"core/a{i:02}.py" for i in range(18)} | {"core/sample.py"}
    assert len(paths) == len(set(paths))


@pytest.mark.anyio
async def test_search_snippet_maps_unicode_casefold_to_original_characters(env, tmp_path, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient
    (env.root / "core" / "unicode.py").write_text("ß" * 120 + "needle ending", encoding="utf-8")
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    await sdk.management_action(action="authorization_upgrade", request_id="grant-source", parameters={
        "expected_scopes": grant["scopes"], "add_scopes": ["source:read"]})
    page = await sdk.management_source("search", path="core", query="needle")
    item = next(row for row in page["items"] if row["path"] == "core/unicode.py")
    assert item["line"] == 1 and "needle ending" in item["text"] and item["snippetTruncated"] is True


@pytest.mark.anyio
async def test_old_target_rejects_only_upgrade_without_breaking_binding(env, tmp_path, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    from core.web.services.external_management.service import ManagementError
    owner = env.service._authorization_upgrades()
    original = owner.invoke
    def old_invoke(*args, **kwargs):
        if "source:read" in kwargs.get("add_scopes", []):
            raise ManagementError("INVALID_INPUT", 422)
        return original(*args, **kwargs)
    monkeypatch.setattr(owner, "invoke", old_invoke)
    monkeypatch.setattr(env.service, "_authorization_upgrades", lambda: owner)
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    before = deepcopy(sdk._state["management"])
    with pytest.raises(BackendClientError) as error:
        await sdk.management_action(action="authorization_upgrade", request_id="grant-source", parameters={
            "expected_scopes": before["scopes"], "add_scopes": ["source:read"]})
    assert error.value.code == "INVALID_INPUT" and sdk._state["management"] == before
    assert (await sdk._management_grant(require_existing=True))["subjectId"] == grant["subjectId"]


@pytest.mark.anyio
async def test_search_maximum_page_fits_native_model_budget(env, tmp_path, monkeypatch):
    from core.assistant_runtime.management import ManagementAdapter
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.external_agent.backend_client import ManagedAgentBackendClient
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    for index in range(6):
        name = "x" * 140 + str(index) + ".py"
        (env.root / "core" / name).write_text("needle " + "\x01" * 200, encoding="utf-8")
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    await sdk.management_action(action="authorization_upgrade", request_id="grant-source", parameters={"expected_scopes": grant["scopes"], "add_scopes": ["source:read"]})
    async def call(project, operation):
        return await operation(sdk)
    service = SimpleNamespace(management=ManagementAdapter(tmp_path / "profile", {"project": env.root}, call), project_ids=lambda: ["project"])
    bind_actions(service, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(execute_action, "source_search", {"project_id": "project", "path": "core", "query": "needle"})
        assert len(result["items"]) == 6
        raw, outcome, facts, rendered = _through_native_model_budget(result)
        assert outcome is None and not facts.truncated and json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        assert any(item["snippetTruncated"] for item in result["items"])
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_long_and_control_character_lines_resume_with_hash_and_complete_json(env, tmp_path, monkeypatch):
    from core.assistant_runtime.management import ManagementAdapter
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    content = "\x01" * 15000 + "long-end\n" + "more " * 600 + "second-end\nlast-line"
    (env.root / "core" / "long.py").write_text(content, encoding="utf-8")
    sdk = ManagedAgentBackendClient(env.root, state_path=tmp_path / "sdk.json")
    _connect(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    await sdk.management_action(action="authorization_upgrade", request_id="grant-source", parameters={"expected_scopes": grant["scopes"], "add_scopes": ["source:read"]})
    project_id = "p" * 160
    async def call(project, operation):
        return await operation(sdk)
    service = SimpleNamespace(management=ManagementAdapter(tmp_path / "profile", {project_id: env.root}, call), project_ids=lambda: [project_id])
    bind_actions(service, asyncio.get_running_loop())
    try:
        args = {"project_id": project_id, "path": "core/long.py", "max_lines": 2}
        chunks = []
        for _ in range(100):
            page = await asyncio.to_thread(execute_action, "source_read", args)
            raw, outcome, facts, rendered = _through_native_model_budget(page)
            assert outcome is None and not facts.truncated and json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
            chunks.append(page["text"])
            args["expected_content_hash"] = page["contentHash"]
            if page["nextCharOffset"] is None:
                assert page["nextLine"] == 3
                break
            assert page["nextCharOffset"] == page["charOffset"] + len(page["text"])
            args["char_offset"] = page["nextCharOffset"]
        else:
            pytest.fail("source cursor did not finish")
        assert "".join(chunks) == content.split("\nlast-line")[0]
        final = await asyncio.to_thread(execute_action, "source_read", {**args, "line": 3, "char_offset": 0})
        assert final["text"] == "last-line" and not final["truncated"]
        (env.root / "core" / "long.py").write_text("changed", encoding="utf-8")
        with pytest.raises(BackendClientError) as error:
            await asyncio.to_thread(execute_action, "source_read", args)
        assert error.value.code == "SOURCE_CHANGED"
    finally:
        unbind_actions(service)


def test_discovery_budget_without_cursor_is_explicitly_unavailable(env, monkeypatch):
    from core.web.services.personal_assistant_project import workspace
    from core.web.services.external_management.contracts import SourceSearchQuery
    monkeypatch.setattr(workspace, "discover_sources", lambda *a, **kw: {"items": [], "nextOffset": None,
        "truncated": True, "scannedFiles": 0, "skippedFiles": 0})
    result = env.service.native.search_source(SourceSearchQuery(path="core", query="needle"))
    assert result["partial"] and result["truncated"] and result["continuationUnavailable"] and result["nextOffset"] is None
    assert "first match per file" in result["coverage"] and "cannot" not in result["coverage"]


@pytest.mark.parametrize("path", [".git/config", "../outside.py", "C:/outside.py", "config.toml", "core/.env", "core/credentials.py", "core/api_token.py", "core/user.json", "core/sample.py:stream"])
def test_forbidden_paths_fail_schema(env, path):
    from core.web.services.external_management.contracts import SourceReadQuery
    with pytest.raises(ValueError):
        SourceReadQuery(path=path)


def test_verified_reader_rejects_hardlink_junction_and_unbound_root(env, monkeypatch):
    from core.web.services import session_service
    from core.web.services.external_management.contracts import SourceReadQuery
    from core.web.services.external_management.service import ManagementError
    source = env.root / "core" / "sample.py"
    os.link(source, env.root / "core" / "hard.py")
    with pytest.raises(ManagementError):
        env.service.native.read_source(SourceReadQuery(path="core/hard.py"))
    junction = env.root / "core" / "junction"
    result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J", str(junction), str(env.root / "core")],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode == 0:
        with pytest.raises(ManagementError):
            env.service.native.read_source(SourceReadQuery(path="core/junction/sample.py"))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", env.root / "other")
    with pytest.raises(ManagementError) as error:
        env.service.native.read_source(SourceReadQuery(path="core/sample.py"))
    assert error.value.code == "TARGET_BINDING_CHANGED"
