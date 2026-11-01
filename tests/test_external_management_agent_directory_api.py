"""Directory access requires an explicit independent grant and closed queries."""
from types import SimpleNamespace

import pytest

PREFIX = "/v1/launcher-assistant-management"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management.service import (
        ManagementService,
        TargetIdentity,
    )
    calls = []
    class Native:
        def read_agents(self, query):
            calls.append(query.model_dump())
            return {"scope": "all_registered_agents", "agents": [{"agentId": "agent-a", "agentCode": "AG-A",
                "displayName": "Example", "status": "active", "ownership": {"kind": "personal", "mode": "chat", "teams": [],
                    "recordedTeams": [], "createdBy": "", "templateId": "", "ownerAgentId": "", "ownerAgentName": ""},
                "dispatchable": True, "dispatchReason": "eligible"}], "total": 1, "registryTotal": 1,
                "counts": {"active": 1, "archived": 0, "dispatchable": 1}, "offset": 0,
                "nextOffset": None, "revision": "a" * 64, "untrustedContent": True}
    binding = {"projectId": "project", "instanceId": "instance"}
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(binding, "root"), native=Native())
    grant = service.bind({"client_id": "directory-test", "expected_binding": binding, "scopes": ["agents:read"]})
    monkeypatch.setattr(route, "_SERVICE", service)
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant["subject_id"],
               route.CAPABILITY_HEADER: grant["subject_capability"]}
    app = FastAPI()
    app.include_router(route.router)
    def upgrade(client):
        response = client.post(PREFIX + "/actions/authorization_upgrade", headers=headers,
            json={"request_id": "explicit-directory", "expected_binding": binding,
                  "parameters": {"expected_scopes": ["agents:read"], "add_scopes": ["agents:directory:read"]}})
        assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, calls=calls, headers=headers, service=service, grant=grant,
                              binding=binding, native=service.native, upgrade=lambda: upgrade(client))


def test_old_scope_is_denied_until_explicit_subject_upgrade(env):
    response = env.client.get(PREFIX + "/directory/agents", headers=env.headers)
    assert response.status_code == 403 and response.json()["detail"]["code"] == "SCOPE_DENIED"
    assert env.calls == []
    assert "agents:directory:read" not in env.client.get(PREFIX + "/binding", headers=env.headers).json()["scopes"]
    old = env.client.get(PREFIX + "/authorization", headers=env.headers).json()
    assert old["scopes"] == ["agents:read"]
    env.upgrade()
    response = env.client.get(PREFIX + "/directory/agents", headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "all_registered_agents" and response.json()["untrustedContent"] is True
    assert len(env.calls) == 1
    current = env.client.get(PREFIX + "/authorization", headers=env.headers).json()
    assert current["subjectId"] == old["subjectId"] and current["scopes"] == ["agents:directory:read", "agents:read"]


def test_new_subject_cannot_implicitly_bind_complete_directory(env):
    response = env.client.post(PREFIX + "/subjects/bind", headers=env.headers,
        json={"client_id": "implicit", "expected_binding": env.binding, "scopes": ["agents:directory:read"]})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "SCOPE_DENIED"


@pytest.mark.parametrize("suffix", ["?query=a&query=b", "?offset=0&offset=1", "?expected_revision=" + "a" * 64 + "&expected_revision=" + "b" * 64,
    "?unknown=true", "?archived=false", "?offset=-1", "?offset=1.0", "?offset=100001", "?offset=1", "?limit=7", "?limit=0",
    "?query=a%0Ab", "?query=" + "a" * 65, "?expected_revision=no"])
def test_http_rejects_duplicate_unknown_and_invalid_queries(env, suffix):
    env.upgrade()
    response = env.client.get(PREFIX + "/directory/agents" + suffix, headers=env.headers)
    assert response.status_code == 422 and env.calls == []


def test_endpoint_requires_control_and_opaque_original_credentials(env):
    from core.web.control import CONTROL_TOKEN_HEADER
    from core.web.routes.launcher_assistant_management import CAPABILITY_HEADER
    env.upgrade()
    for headers in ({key: value for key, value in env.headers.items() if key != CONTROL_TOKEN_HEADER},
                    {**env.headers, CAPABILITY_HEADER: "z" * 48}):
        response = env.client.get(PREFIX + "/directory/agents", headers=headers)
        assert response.status_code == 403
    assert env.calls == []


def test_directory_revision_conflict_is_exposed_without_internal_detail(env, monkeypatch):
    from core.web.services.external_management.service import ManagementError
    env.upgrade()
    def unavailable(query):
        assert query.offset == 6 and query.expected_revision == "a" * 64
        raise ManagementError("AGENT_DIRECTORY_REVISION_CONFLICT", 409)
    monkeypatch.setattr(env.native, "read_agents", unavailable)
    response = env.client.get(PREFIX + "/directory/agents?offset=6&expected_revision=" + "a" * 64, headers=env.headers)
    assert response.status_code == 409 and response.json() == {"detail": {"code": "AGENT_DIRECTORY_REVISION_CONFLICT"}}


def test_backend_validates_closed_response(env, monkeypatch):
    env.upgrade()
    original = env.native.read_agents
    monkeypatch.setattr(env.native, "read_agents", lambda query: {**original(query), "prompt": "SECRET"})
    response = env.client.get(PREFIX + "/directory/agents", headers=env.headers)
    assert response.status_code == 503 and "SECRET" not in response.text
