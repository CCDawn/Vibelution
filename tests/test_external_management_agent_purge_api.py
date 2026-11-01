"""Operator transport exposes preview and separately authorized purge."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_external_agent_agent_purge_client import preview

PREFIX = "/v1/launcher-assistant-management"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    class Native:
        def __init__(self):
            self.agent = {**preview()["agent"], "status": "archived", "metadata": {}, "llmBindings": {}}
            self.calls = 0
        def read_purge_preview(self, agent_id): return deepcopy(self.agent)
        def read_archive_state(self, agent_id): return deepcopy(self.agent)
        def purge(self, parameters, marker):
            self.calls += 1
            self.agent = None
            return {"agentId": parameters["agent_id"], "status": "purged", "cleanupPending": False}
    native, binding = Native(), {"projectId": "p", "instanceId": "i"}
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(binding, "root"), native=native)
    grant = service.bind({"client_id": "purge-client", "expected_binding": binding, "scopes": ["agents:read"]})
    monkeypatch.setattr(route, "_SERVICE", service)
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant["subject_id"],
        route.CAPABILITY_HEADER: grant["subject_capability"]}
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, native=native, headers=headers, binding=binding, service=service)


def test_preview_then_explicit_upgrade_and_purge_history(env):
    response = env.client.get(PREFIX + "/agents/agent-1/purge-preview", headers=env.headers)
    assert response.status_code == 200 and response.json()["agent"]["configRevision"] == 3
    assert response.json()["irreversible"] is True and env.native.calls == 0
    payload = {"request_id": "purge-1", "expected_binding": env.binding,
        "parameters": {"agent_id": "agent-1", "expected_config_revision": 3}}
    denied = env.client.post(PREFIX + "/actions/agent_purge", json=payload, headers=env.headers)
    assert denied.status_code == 403 and env.native.calls == 0
    assert "agents:purge" not in env.service.binding()["scopes"]
    upgraded = env.client.post(PREFIX + "/actions/authorization_upgrade", headers=env.headers,
        json={"request_id": "purge-scope", "expected_binding": env.binding,
            "parameters": {"expected_scopes": ["agents:read"], "add_scopes": ["agents:purge"]}})
    assert upgraded.status_code == 200 and upgraded.json()["status"] == "completed"
    result = env.client.post(PREFIX + "/actions/agent_purge", json=payload, headers=env.headers)
    assert result.status_code == 200 and result.json()["verified"] is True
    assert result.json()["purge"]["agentId"] == "agent-1" and "agent" not in result.json()
    repeated = env.client.post(PREFIX + "/actions/agent_purge", json=payload, headers=env.headers)
    assert repeated.status_code == 200 and repeated.json()["reused"] is True and env.native.calls == 1


def test_preview_requires_operator_control_and_closed_query(env):
    assert env.client.get(PREFIX + "/agents/agent-1/purge-preview").status_code == 403
    response = env.client.get(PREFIX + "/agents/agent-1/purge-preview?force=true", headers=env.headers)
    assert response.status_code == 422 and env.native.calls == 0
