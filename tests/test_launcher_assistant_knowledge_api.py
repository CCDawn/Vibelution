"""Team knowledge catalog through the real native target and managed SDK."""
from __future__ import annotations

import json
import os
from copy import deepcopy

import pytest
from tests.test_launcher_assistant_knowledge_directory import env as knowledge_env

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows verified source reader")


@pytest.fixture
def target(knowledge_env, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes import launcher_assistant_management as route
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    e = knowledge_env
    monkeypatch.setattr(directory, "PROJECT_ROOT", e.root)
    monkeypatch.setattr(directory, "CONFIG_PATH", e.config)
    monkeypatch.setattr(directory, "_active_project_root", lambda: e.root)
    monkeypatch.setattr(sessions, "PROJECT_ROOT", e.root)
    e.binding = {"projectId": "test-project", "instanceId": e.paths.instance_id}
    e.service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(e.binding, "authority"),
                                  native=NativeAgentGateway(e.root))
    monkeypatch.setattr(route, "_SERVICE", e.service)
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        e.client = client
        yield e


def connect(sdk, target, monkeypatch):
    from core.external_agent.backend_client import BackendClientError
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes.launcher_assistant_management import CAPABILITY_HEADER, SUBJECT_HEADER
    async def request(method, path, **kwargs):
        headers = {CONTROL_TOKEN_HEADER: get_control_token()}
        if kwargs.get("management_auth"):
            subject, capability = kwargs["management_auth"]
            headers.update({SUBJECT_HEADER: subject, CAPABILITY_HEADER: capability})
        response = target.client.request(method, path.removeprefix("/api"), headers=headers, json=kwargs.get("json_payload"))
        if response.status_code >= 400:
            raise BackendClientError("target refused request", code=response.json().get("detail", {}).get("code", "BACKEND_UNAVAILABLE"))
        return response.json()
    monkeypatch.setattr(sdk, "_request_json", request)


def auth_headers(target, client_id, scopes):
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes.launcher_assistant_management import CAPABILITY_HEADER, SUBJECT_HEADER
    grant = target.service.bind({"client_id": client_id, "expected_binding": target.binding, "scopes": sorted(scopes)})
    return {CONTROL_TOKEN_HEADER: get_control_token(), SUBJECT_HEADER: grant["subject_id"], CAPABILITY_HEADER: grant["subject_capability"]}


def test_native_target_requires_both_scopes_and_closed_transport(target):
    prefix = "/v1/launcher-assistant-management/directory/teams/team-a/knowledge-bases"
    for index, scopes in enumerate((["knowledge:catalog:read"], ["teams:directory:read"], ["teams:read"])):
        response = target.client.get(prefix, headers=auth_headers(target, f"client-{index}", scopes))
        assert response.status_code == 403 and response.json()["detail"]["code"] == "SCOPE_DENIED"
    headers = auth_headers(target, "client-both", ["knowledge:catalog:read", "teams:directory:read"])
    response = target.client.get(prefix, headers=headers)
    assert response.status_code == 200
    assert response.json()["knowledgeBases"] == [{"id": "kb-a", "name": "Public name", "status": "active"}]
    assert "PRIVATE" not in response.text and "decoded" in response.json()["coverage"]
    for suffix in ("?limit=7", "?offset=-1", "?offset=0&offset=1", "?path=other"):
        assert target.client.get(prefix + suffix, headers=headers).status_code == 422
    from core.web.control import CONTROL_TOKEN_HEADER
    without_control = {key: value for key, value in headers.items() if key != CONTROL_TOKEN_HEADER}
    assert target.client.get(prefix, headers=without_control).status_code == 403


@pytest.mark.anyio
async def test_sdk_explicit_upgrade_queries_native_target_without_expanding_default(target, tmp_path, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    sdk = ManagedAgentBackendClient(target.root, state_path=tmp_path / "sdk.json")
    connect(sdk, target, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    before = deepcopy(sdk._state["management"])
    assert "knowledge:catalog:read" not in before["scopes"]
    assert "knowledge:catalog:read" not in target.service.binding()["scopes"]
    with pytest.raises(BackendClientError) as error:
        await sdk.management_team_knowledge(team_id="team-a")
    assert error.value.code == "SCOPE_DENIED" and sdk._state["management"] == before
    receipt = await sdk.management_action(action="authorization_upgrade", request_id="knowledge-upgrade-1", parameters={
        "expected_scopes": before["scopes"], "add_scopes": ["knowledge:catalog:read"]})
    assert receipt["authorization"]["addedScopes"] == ["knowledge:catalog:read"]
    assert sdk._state["management"]["subjectId"] == grant["subjectId"]
    page = await sdk.management_team_knowledge(team_id="team-a")
    assert page["teamId"] == "team-a" and page["total"] == 1 and page["nextOffset"] is None
    assert set(page["knowledgeBases"][0]) == {"id", "name", "status"}
    assert "PRIVATE" not in json.dumps(page)
    marker_bytes = target.marker.read_bytes()
    target.marker.unlink()
    with pytest.raises(BackendClientError) as error:
        await sdk.management_team_knowledge(team_id="team-a")
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"
    target.marker.write_bytes(marker_bytes)
    from config.paths import DATA_HOME_ENV
    monkeypatch.setenv(DATA_HOME_ENV, str(tmp_path / "shared-data"))
    with pytest.raises(BackendClientError) as error:
        await sdk.management_team_knowledge(team_id="team-a")
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


@pytest.mark.anyio
async def test_old_target_refuses_new_scope_without_breaking_existing_connection(target, tmp_path, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    sdk = ManagedAgentBackendClient(target.root, state_path=tmp_path / "sdk-old-target.json")
    connect(sdk, target, monkeypatch)
    grant = await sdk._management_grant(require_existing=False)
    before = deepcopy(sdk._state["management"])
    original = sdk._request_json
    async def old_target(method, path, **kwargs):
        if path.endswith("/actions/authorization_upgrade"):
            raise BackendClientError("Old target does not recognize scope", code="INVALID_INPUT")
        return await original(method, path, **kwargs)
    monkeypatch.setattr(sdk, "_request_json", old_target)
    with pytest.raises(BackendClientError) as error:
        await sdk.management_action(action="authorization_upgrade", request_id="upgrade-old", parameters={
            "expected_scopes": before["scopes"], "add_scopes": ["knowledge:catalog:read"]})
    assert error.value.code == "INVALID_INPUT" and sdk._state["management"] == before
    status = await sdk.management_authorization_status()
    assert status["subjectId"] == grant["subjectId"] and status["scopes"] == before["scopes"]
