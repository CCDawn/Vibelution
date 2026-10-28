"""Scoped Team result transport exercises only temporary native fixtures."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import launcher_assistant_management as route
from core.web.services.external_management import team_result
from core.web.services.external_management.service import ManagementError
from tests.test_external_management_team import BINDING, env
from tests.test_external_management_team_result import result_env


PREFIX = "/api/v1/launcher-assistant-management"
SCOPE = "teams:results:read"


def upgrade(env, args, request_id="upgrade-result"):
    old = env.service._authorize(*args, None)
    return env.service.invoke(*args, "authorization_upgrade", {
        "request_id": request_id, "expected_binding": BINDING,
        "parameters": {"expected_scopes": old["scopes"], "add_scopes": [SCOPE]}})


def test_only_explicit_upgrade_allows_original_subject_result(result_env, monkeypatch):
    c, env = result_env, result_env.env
    env.service.native = SimpleNamespace(project_root=env.root)
    subject, capability = env.args
    assert SCOPE not in env.service.binding()["scopes"]
    assert SCOPE not in env.service._authorize(subject, capability, None)["scopes"]
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service.team_result(subject, capability, "request-1")
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service.bind({"client_id": "new-sensitive", "expected_binding": BINDING, "scopes": [SCOPE]})
    receipt = upgrade(env, env.args)
    assert receipt["verified"] and receipt["authorization"]["addedScopes"] == [SCOPE]
    assert env.service.team_result(*env.args, "request-1") == {
        "status": "available", "text": "Verified result", "truncated": False, "untrustedContent": True}
    other = env.service.bind({"client_id": "other", "expected_binding": BINDING, "scopes": ["teams:read"]})
    other_args = (other["subject_id"], other["subject_capability"])
    upgrade(env, other_args, "upgrade-other")
    assert env.service.team_result(*other_args, "request-1")["status"] == "unavailable"
    assert env.service.team_result(*env.args, "unknown")["status"] == "unavailable"


def test_http_operator_control_and_query_rejection(result_env, monkeypatch):
    env = result_env.env
    env.service.native = SimpleNamespace(project_root=env.root)
    upgrade(env, env.args)
    monkeypatch.setattr(route, "_SERVICE", env.service)
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    headers = {route.SUBJECT_HEADER: env.args[0], route.CAPABILITY_HEADER: env.args[1]}
    path = PREFIX + "/team-runs/requests/request-1/result"
    with TestClient(app) as client:
        assert client.get(path, headers=headers).status_code == 403
        headers[CONTROL_TOKEN_HEADER] = get_control_token()
        response = client.get(path, headers=headers)
        assert response.status_code == 200 and response.json()["text"] == "Verified result"
        assert client.get(path + "?unused=1", headers=headers).status_code == 422
        assert client.get(path, headers={**headers, route.CAPABILITY_HEADER: "invalid"}).status_code == 403


def test_authorization_revocation_during_read_never_returns_text(result_env, monkeypatch):
    env = result_env.env
    env.service.native = SimpleNamespace(project_root=env.root)
    upgrade(env, env.args)
    original = team_result.read_team_result
    def revoked(*args):
        result = original(*args)
        path = env.service.store.path("subjects", env.args[0])
        grant = env.service.store.read(path)
        grant["scopes"].remove(SCOPE)
        env.service.store.write(path, grant)
        return result
    monkeypatch.setattr(team_result, "read_team_result", revoked)
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service.team_result(*env.args, "request-1")


def test_target_binding_change_during_read_never_returns_text(result_env, monkeypatch):
    from core.web.services.external_management.service import TargetIdentity
    env = result_env.env
    env.service.native = SimpleNamespace(project_root=env.root)
    upgrade(env, env.args)
    original = team_result.read_team_result
    def switched(*args):
        result = original(*args)
        env.service.identity = lambda: TargetIdentity({**BINDING, "instanceId": "changed"}, "native-root")
        return result
    monkeypatch.setattr(team_result, "read_team_result", switched)
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        env.service.team_result(*env.args, "request-1")
