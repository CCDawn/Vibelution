"""Neutral documentation reuses OpenAPI discovery without granting HTTP execution."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module", autouse=True)
def private_operator_environment(tmp_path_factory):
    """Install private config/user paths before any product module is imported."""
    root = tmp_path_factory.mktemp("management-documentation")
    config_path = root / "config/config.toml"
    config_path.parent.mkdir()
    config_path.write_text("[runtime]\nprofile = ''\n", encoding="utf-8")
    patch = pytest.MonkeyPatch()
    for name, path in {"USERPROFILE": root / "user", "LOCALAPPDATA": root / "local", "TEMP": root / "tmp",
                       "TMP": root / "tmp", "TMPDIR": root / "tmp", "VIBELUTION_CONFIG_PATH": config_path,
                       "VIBELUTION_CONFIG_HOME": config_path.parent, "VIBELUTION_DATA_HOME": root / "data",
                       "VIBELUTION_PROJECTS_HOME": root / "projects"}.items():
        if path != config_path:
            path.mkdir(parents=True, exist_ok=True)
        patch.setenv(name, str(path))
    # Other test files can already have imported these modules during collection.
    from config import public_config, settings
    patch.setattr(public_config, "CONFIG_PATH", config_path)
    patch.setattr(settings, "_settings", None)
    patch.setattr(settings, "_config_path", None)
    yield root
    patch.undo()


@pytest.fixture
def env(tmp_path, monkeypatch, private_operator_environment):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management import documentation
    from core.web.services.external_management.contracts import SCOPES
    from core.web.services.external_management.service import (
        ManagementService,
        TargetIdentity,
    )
    from core.web.services.personal_assistant_platform_api import api, catalog

    calls = []
    class Native:
        def _owners(self):
            calls.append("binding-read")

        def __getattr__(self, name):
            pytest.fail("Unexpected native side effect: " + name)

    binding = {"projectId": "documentation-project", "instanceId": "documentation-instance"}
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(binding, "canonical"), native=Native())
    grant = service.bind({"client_id": "launcher", "expected_binding": binding,
                          "scopes": [scope for scope in SCOPES if scope != "agents:create:files"]})
    monkeypatch.setattr(route, "_SERVICE", service)
    monkeypatch.setattr(api, "_filter_get_endpoints", lambda paths: {path: item for path, item in paths.items() if "get" in item})
    spec = {"openapi": "3.1.0", "paths": {
        "/api/agents": {"post": {"operationId": "create_agent", "summary": "Create", "tags": ["agents"]},
                        "get": {"operationId": "list_agents", "summary": "List", "tags": ["agents"]}},
        "/api/agents/{agent_id}": {"patch": {"operationId": "update_agent", "tags": ["agents"]}},
        "/api/agents/{agent_id}/avatar": {"patch": {"operationId": "avatar_agent", "tags": ["agents"]}},
        "/api/config/language": {"put": {"operationId": "language", "tags": ["config"]}},
        "/api/teams": {"post": {"operationId": "team_create", "tags": ["teams"]}},
    }, "components": {"schemas": {}}}
    monkeypatch.setattr(catalog, "get_spec", lambda: spec)
    monkeypatch.setattr(documentation, "_get_spec", lambda: spec)
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant["subject_id"],
               route.CAPABILITY_HEADER: grant["subject_capability"]}
    with TestClient(app) as client:
        yield SimpleNamespace(service=service, args=(grant["subject_id"], grant["subject_capability"]), spec=spec,
            client=client, headers=headers, binding=binding, calls=calls, native=service.native,
            root=tmp_path, catalog=catalog, documentation=documentation, config_root=private_operator_environment)


PREFIX = "/api/v1/launcher-assistant-management/api-documentation"


def test_documentation_requires_operator_subject_scope_and_current_binding(env):
    from core.web.control import CONTROL_TOKEN_HEADER
    from core.web.routes import launcher_assistant_management as route
    url = PREFIX + "/catalog"
    assert env.client.get(url).status_code == 403
    assert env.client.get(url, headers={**env.headers, CONTROL_TOKEN_HEADER: "bad"}).status_code == 403
    assert env.client.get(url, headers={**env.headers, route.CAPABILITY_HEADER: "bad"}).status_code == 403
    grant = env.service.bind({"client_id": "read-agents", "expected_binding": env.binding, "scopes": ["agents:read"]})
    headers = {**env.headers, route.SUBJECT_HEADER: grant["subject_id"], route.CAPABILITY_HEADER: grant["subject_capability"]}
    assert env.client.get(url, headers=headers).json()["detail"]["code"] == "SCOPE_DENIED"
    from core.web.services.external_management.service import TargetIdentity
    env.service.identity = lambda: TargetIdentity({**env.binding, "instanceId": "another"}, "canonical")
    assert env.client.get(url, headers=env.headers).status_code == 409
    assert env.calls == []


def test_documentation_reprojects_only_migrated_agent_actions_and_never_legacy_execution(env):
    response = env.client.get(PREFIX + "/catalog", headers=env.headers)
    assert response.status_code == 200
    result = response.json()
    assert result["untrustedContent"] is True and result["source"] == "registered-openapi"
    entries = {item["operationId"]: item for item in result["operations"]}
    for operation, action in (("create_agent", "agent_create"), ("update_agent", "agent_update"), ("avatar_agent", "agent_avatar")):
        entry = entries[operation]
        assert entry["executable"] is True and entry["action"] == action
        assert entry["argumentHelp"] == {"action": "describe", "parameters": {"action": action}}
    for operation in ("list_agents", "language", "team_create"):
        assert entries[operation]["access"] == "operator_only" and entries[operation]["executable"] is False
    for entry in entries.values():
        assert not {"tool", "execution", "approval", "allowedFields", "constraints", "reason"} & set(entry)
    encoded = json.dumps(result)
    assert "read_gateway" not in encoded and "personal_assistant_" not in encoded


def test_native_catalog_pagination_search_and_describe_schema_are_reused(env):
    env.spec["paths"]["/api/agents"]["post"]["requestBody"] = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Create"}}}}
    env.spec["components"]["schemas"]["Create"] = {"type": "object", "properties": {"name": {"type": "string"}}}
    result = env.client.get(PREFIX + "/catalog", params={"query": "agent", "tag": "agents", "offset": 1, "limit": 2}, headers=env.headers).json()
    assert result["offset"] == 1 and result["limit"] == 2 and result["total"] == 4 and len(result["operations"]) == 2
    detail = env.client.get(PREFIX + "/operations/create_agent", headers=env.headers).json()
    assert detail["components"]["schemas"]["Create"] == env.spec["components"]["schemas"]["Create"]
    assert detail["requestBody"] == env.spec["paths"]["/api/agents"]["post"]["requestBody"]
    assert detail["operation"]["action"] == "agent_create"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"offset": -1}, {"query": "x" * 513}, {"tag": "x" * 129},
                                   {"url": "http://unused"}, {"method": "POST"}])
def test_documentation_rejects_out_of_contract_query(env, params):
    assert env.client.get(PREFIX + "/catalog", params=params, headers=env.headers).status_code == 422
    assert not env.calls


def test_duplicate_unknown_and_missing_schema_preserve_native_refusal(env):
    env.spec["paths"]["/api/duplicate"] = {"get": {"operationId": "create_agent"}}
    result = env.client.get(PREFIX + "/operations/create_agent", headers=env.headers).json()
    assert result["ok"] is False and "duplicated" in result["message"]
    assert env.client.get(PREFIX + "/operations/missing", headers=env.headers).json()["ok"] is False
    env.spec["paths"]["/api/schema"] = {"get": {"operationId": "schema", "responses": {"200": {"$ref": "#/components/schemas/Missing"}}}}
    result = env.client.get(PREFIX + "/operations/schema", headers=env.headers).json()
    assert result["truncated"] is True and "Missing" in result["omittedSchemas"]


def test_oversized_catalog_fails_bounded_without_truncating_identity(env):
    env.spec["paths"] = {"/api/" + str(index): {"get": {"operationId": "op-" + str(index), "summary": "x" * 5000}} for index in range(20)}
    response = env.client.get(PREFIX + "/catalog", headers=env.headers)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "DOCUMENTATION_TOO_LARGE"
    assert env.client.get(PREFIX + "/catalog", params={"limit": 1}, headers=env.headers).json()["operations"][0]["operationId"] == "op-0"


def test_description_budget_and_zero_mutation_no_pa_no_http(env, monkeypatch):
    import httpx

    from core.web.services import agent_directory_service as directory
    monkeypatch.setattr(directory, "current_agent_runtime", lambda: pytest.fail("PA runtime must not be read"))
    monkeypatch.setattr(directory, "create_agent_instance", lambda **_: pytest.fail("Agent creation forbidden"))
    monkeypatch.setattr(httpx, "request", lambda *_args, **_kwargs: pytest.fail("arbitrary HTTP forbidden"))
    env.spec["paths"]["/api/schema"] = {"get": {"operationId": "schema", "responses": {"200": {"$ref": "#/components/schemas/Large"}}}}
    env.spec["components"]["schemas"]["Large"] = {"description": "x" * 100000}
    original = copy.deepcopy(env.spec)
    before = {path: path.read_bytes() for path in env.root.rglob("*.json")}
    result = env.client.get(PREFIX + "/operations/schema", headers=env.headers).json()
    assert result["truncated"] is True and len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= env.catalog.MAX_DESCRIPTION_CHARS
    assert env.spec == original and before == {path: path.read_bytes() for path in env.root.rglob("*.json")}
    assert env.calls == ["binding-read"]


def test_seven_scope_bind_never_upgrades_existing_six_scope_subject(env):
    from core.web.services.external_management.contracts import SCOPES
    from core.web.services.external_management.service import ManagementError
    assert SCOPES[9:13] == ("platform:describe", "sessions:read", "sessions:pin", "sessions:parameters:read")
    assert SCOPES[13] == "legacy:receipts:read" and "tasks:read" in SCOPES
    payload = {"client_id": "prototype-six", "expected_binding": env.binding, "scopes": list(SCOPES[:6])}
    env.service.bind(payload)
    with pytest.raises(ManagementError, match="SUBJECT_GRANT_CONFLICT"):
        env.service.bind({**payload, "scopes": list(SCOPES)})


def test_documentation_scope_does_not_grant_mutation_or_change_native_binding(env, monkeypatch):
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management.service import ManagementError
    grant = env.service.bind({"client_id": "documentation-only", "expected_binding": env.binding, "scopes": ["platform:describe"]})
    headers = {**env.headers, route.SUBJECT_HEADER: grant["subject_id"], route.CAPABILITY_HEADER: grant["subject_capability"]}
    response = env.client.post(PREFIX.removesuffix("/api-documentation") + "/actions/agent_create", headers=headers,
        json={"request_id": "not-authorized", "expected_binding": env.binding,
              "parameters": {"display_name": "Forbidden", "model_id": "not-used"}})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "SCOPE_DENIED"
    assert not env.calls

    def wrong_owner():
        raise ManagementError("TARGET_BINDING_CHANGED", 409)

    monkeypatch.setattr(env.native, "_owners", wrong_owner)
    monkeypatch.setattr(env.catalog, "get_spec", lambda: pytest.fail("wrong owner cannot read documentation"))
    assert env.client.get(PREFIX + "/catalog", headers=headers).status_code == 409


def test_public_entry_dto_cannot_reintroduce_legacy_execution_claims(env):
    from pydantic import ValidationError

    from core.web.services.external_management.contracts import DocumentationEntry
    raw = env.client.get(PREFIX + "/catalog", headers=env.headers).json()["operations"][0]
    for injected in ({"tool": "personal_assistant_platform_api_tool"}, {"execution": {"path": "/api/private"}},
                     {"executable": True, "access": "native_action", "action": "agent_create"}):
        with pytest.raises(ValidationError):
            DocumentationEntry.model_validate({**raw, **injected})


def test_real_router_registry_spec_is_read_only_without_lifespan_or_builtin_bootstrap(monkeypatch, private_operator_environment):
    import os
    import sys
    import time

    from core.web.services.agent_directory import bootstrap
    from core.web.services.external_management import documentation
    from core.web.services.personal_assistant_platform_api import catalog
    monkeypatch.setattr(bootstrap, "initialize_builtin_agent_catalog", lambda: pytest.fail("documentation must not bootstrap native assets"))
    monkeypatch.setattr(catalog, "get_spec", lambda: pytest.fail("legacy discovery must not bootstrap"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(documentation, "_SPEC_APP", None, raising=False)
    auditing = [True]
    writes = []

    def audit(event, args):
        if not auditing[0]:
            return
        writing = event in {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.chmod", "os.truncate", "os.utime", "sqlite3.connect"}
        if event == "open":
            _, mode, flags = args
            writing = bool((flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            writing = writing or (isinstance(mode, str) and any(char in mode for char in "wax+"))
        if writing:
            writes.append(event)
            raise AssertionError("documentation must not write directory/config/runtime data: " + event)
        if event == "socket.connect":
            raise AssertionError("documentation must not perform network I/O")

    sys.addaudithook(audit)
    try:
        started = time.perf_counter()
        first = documentation.api_catalog(query="agent", limit=3)
        cold_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        second = documentation.api_catalog(query="agent", limit=3)
        warm_ms = (time.perf_counter() - started) * 1000
        paths = documentation._get_spec()["paths"]
        for path, method in (("/api/agents", "post"), ("/api/agents/{agent_id}", "patch"), ("/api/agents/{agent_id}/avatar", "patch")):
            operation_id = paths[path][method]["operationId"]
            detail = documentation.api_describe(operation_id)
            assert detail["ok"] and detail["operation"]["executable"] and detail["requestBody"]
        assert first["operations"] == second["operations"] and first["total"] > 3
        print("DOCS_REAL_REGISTRY_TIMINGS", json.dumps({"coldMs": round(cold_ms, 2), "warmMs": round(warm_ms, 2), "pathCount": len(paths)}))
        assert cold_ms < 20000 and warm_ms < 5000
    finally:
        auditing[0] = False
    assert not writes
