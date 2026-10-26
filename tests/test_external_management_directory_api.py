"""Closed directory transport and independent read grants in an isolated backend."""
from types import SimpleNamespace

import pytest


PREFIX = "/v1/launcher-assistant-management"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    calls = []
    team = {"id": "team-a", "name": "Example", "status": "active", "purpose": "Fictional work"}
    room = {"id": "room-a", "title": "Example room", "status": "ready"}
    class Native:
        def read_session(self, session_id):
            return {"session": {"id": session_id, "title": "Visible", "agentId": "agent-a", "pinned": False,
                "pinnedAtMs": None, "status": "ready", "archived": False}, "untrustedContent": True}
        def read_session_parameters(self, session_id):
            calls.append(("session_parameters_get", session_id))
            return {"source": "native-current-agent-runtime-parameters", "catalogState": "absent", "untrustedContent": True,
                "parameters": {"sessionId": session_id, "agentId": "agent-a", "configRevision": 3,
                    "currentModelId": "provider/model", "currentReasoningEffort": "none", "reasoningEffortValues": ["none"],
                    "contextWindow": 32000, "maxContextWindow": 64000, "budget": {"revision": 3, "maxCallsPerTurn": 0}}}
        def read_teams(self, query):
            calls.append(("team_list", query.model_dump()))
            return {"teams": [{**team, "memberCount": 1}], "total": 1, "offset": query.offset,
                "nextOffset": None, "untrustedContent": True}
        def read_team(self, team_id, query):
            calls.append(("team_get", team_id, query.model_dump()))
            return {"team": {**team, "members": [{"agentId": "agent-a"}], "memberOffset": query.member_offset,
                "memberTotal": 1, "nextMemberOffset": None}, "untrustedContent": True}
        def read_rooms(self, query):
            calls.append(("room_list", query.model_dump()))
            return {"rooms": [room], "total": 1, "offset": query.offset, "nextOffset": None, "untrustedContent": True}
        def read_room(self, room_id):
            calls.append(("room_get", room_id))
            return {"room": room, "untrustedContent": True}
    binding = {"projectId": "p", "instanceId": "i"}
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(binding, "root"), native=Native())
    monkeypatch.setattr(route, "_SERVICE", service)
    app = FastAPI()
    app.include_router(route.router)
    base = {CONTROL_TOKEN_HEADER: get_control_token()}
    def headers(scopes):
        grant = service.bind({"client_id": "directory-" + str(len(scopes)) + "-" + "-".join(scopes).replace(":", "_"),
            "expected_binding": binding, "scopes": scopes})
        return {**base, route.SUBJECT_HEADER: grant["subject_id"], route.CAPABILITY_HEADER: grant["subject_capability"]}
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, calls=calls, headers=headers, native=service.native, service=service, binding=binding)


def _connect_sdk_http(sdk, env, monkeypatch):
    from core.external_agent.backend_client import BackendClientError
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    async def request(method, path, **kwargs):
        headers = {CONTROL_TOKEN_HEADER: get_control_token()}
        if kwargs.get("management_auth"):
            subject, capability = kwargs["management_auth"]
            headers.update({"X-Vibelution-Management-Subject": subject, "X-Vibelution-Management-Capability": capability})
        response = env.client.request(method, path.removeprefix("/api"), headers=headers, json=kwargs.get("json_payload"))
        if response.status_code >= 400:
            raise BackendClientError("Synthetic backend refused request", code=response.json()["detail"]["code"])
        return response.json()
    monkeypatch.setattr(sdk, "_request_json", request)
    return request


@pytest.mark.parametrize("path,scope,operation", [
    ("/directory/teams", "teams:directory:read", "team_list"),
    ("/directory/teams/team-a", "teams:directory:read", "team_get"),
    ("/directory/rooms", "rooms:read", "room_list"),
    ("/directory/rooms/room-a", "rooms:read", "room_get"),
])
def test_directory_http_closed_reads(env, path, scope, operation):
    result = env.client.get(PREFIX + path, headers=env.headers([scope]))
    assert result.status_code == 200, result.text
    assert result.json()["untrustedContent"] is True
    assert env.calls[0][0] == operation
    assert not any(key in result.text for key in ("messages", "canvas", "config", "prompt", "storage"))


@pytest.mark.parametrize("path", ["/directory/teams", "/directory/teams/team-a", "/directory/rooms", "/directory/rooms/room-a"])
def test_legacy_grant_does_not_gain_directory_visibility(env, path):
    result = env.client.get(PREFIX + path, headers=env.headers(["teams:read", "sessions:read"]))
    assert result.status_code == 403 and result.json()["detail"]["code"] == "SCOPE_DENIED"
    assert env.calls == []


@pytest.mark.parametrize("path,suffix", [
    ("teams", "?limit=7"), ("teams", "?offset=-1"), ("teams", "?offset=1&offset=2"),
    ("rooms", "?archived=1"), ("rooms", "?query=a%0Ab"), ("teams", "?force=true"),
    ("teams/team-a", "?limit=1&limit=2"), ("rooms/room-a", "?query=body"),
])
def test_directory_query_rejects_unknown_duplicate_or_coerced_inputs(env, path, suffix):
    result = env.client.get(PREFIX + "/directory/" + path + suffix,
        headers=env.headers(["teams:directory:read", "rooms:read"]))
    assert result.status_code == 422 and env.calls == []


def test_parameter_http_requires_explicit_parameter_and_session_grants(env):
    for scopes in (["sessions:read"], ["sessions:parameters:read"]):
        result = env.client.get(PREFIX + "/sessions/session-a/parameters", headers=env.headers(scopes))
        assert result.status_code == 403 and env.calls == []
    result = env.client.get(PREFIX + "/sessions/session-a/parameters",
        headers=env.headers(["sessions:read", "sessions:parameters:read"]))
    assert result.status_code == 200 and result.json()["parameters"]["budget"]["maxCallsPerTurn"] == 0


def test_authorization_transport_requires_operator_control_and_original_subject(env):
    from core.web.control import CONTROL_TOKEN_HEADER
    from core.web.routes.launcher_assistant_management import CAPABILITY_HEADER
    headers = env.headers(["platform:describe"])
    payload = {"request_id": "upgrade-security", "expected_binding": env.binding,
        "parameters": {"expected_scopes": ["platform:describe"], "add_scopes": ["rooms:read"]}}
    subjects = list(env.service.store.root.joinpath("subjects").glob("*.json"))
    before = {path: path.read_bytes() for path in subjects}
    for method, path, body in (("GET", "/authorization", None),
        ("POST", "/actions/authorization_upgrade", payload),
        ("GET", "/actions/authorization_upgrade/requests/upgrade-security", None)):
        response = env.client.request(method, PREFIX + path,
            headers={key: value for key, value in headers.items() if key != CONTROL_TOKEN_HEADER}, json=body)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "OPERATOR_CONTROL_REQUIRED"
    wrong_subject = {**headers, CAPABILITY_HEADER: "z" * 48}
    for method, path, body in (("GET", "/authorization", None), ("POST", "/actions/authorization_upgrade", payload)):
        response = env.client.request(method, PREFIX + path, headers=wrong_subject, json=body)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "SUBJECT_DENIED"
    assert {path: path.read_bytes() for path in subjects} == before and env.calls == []


@pytest.mark.parametrize("invalid", ["extra_actor", "duplicate_nested", "duplicate_request", "query"])
def test_authorization_transport_rejects_ambiguous_input_without_mutating_grants(env, invalid):
    import json
    headers = env.headers(["platform:describe"])
    payload = {"request_id": "upgrade-invalid", "expected_binding": env.binding,
        "parameters": {"expected_scopes": ["platform:describe"], "add_scopes": ["rooms:read"]}}
    if invalid == "query":
        response = env.client.get(PREFIX + "/authorization?subject=other", headers=headers)
    else:
        if invalid == "extra_actor":
            payload["parameters"]["subject_id"] = "other"
        content = json.dumps(payload)
        if invalid == "duplicate_nested":
            content = content.replace('"add_scopes": ["rooms:read"]', '"add_scopes": ["rooms:read"], "add_scopes": ["agents:archive"]')
        if invalid == "duplicate_request":
            content = content[:-1] + ', "request_id": "other"}'
        response = env.client.post(PREFIX + "/actions/authorization_upgrade", headers={**headers, "Content-Type": "application/json"}, content=content)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_INPUT"
    current = env.client.get(PREFIX + "/authorization", headers=headers)
    assert current.json()["scopes"] == ["platform:describe"] and current.json()["grantRevision"] == 0


@pytest.mark.anyio
async def test_sdk_management_and_model_actions_share_actual_closed_http(env, tmp_path, monkeypatch):
    import asyncio
    import json
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.assistant_runtime.management import ManagementAdapter
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    sdk = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "sdk-state.json")
    async def request(method, path, **kwargs):
        headers = {CONTROL_TOKEN_HEADER: get_control_token()}
        if kwargs.get("management_auth"):
            subject, capability = kwargs["management_auth"]
            headers.update({"X-Vibelution-Management-Subject": subject, "X-Vibelution-Management-Capability": capability})
        response = env.client.request(method, path.removeprefix("/api"), headers=headers, json=kwargs.get("json_payload"))
        if response.status_code >= 400:
            raise BackendClientError("Synthetic backend refused request", code=response.json()["detail"]["code"])
        return response.json()
    monkeypatch.setattr(sdk, "_request_json", request)
    async def call(project_id, operation):
        assert project_id == "p"
        return await operation(sdk)
    management = ManagementAdapter(tmp_path / "profile", {"p": tmp_path}, call)
    service = SimpleNamespace(management=management, project_ids=lambda: ["p"])
    bind_actions(service, asyncio.get_running_loop())
    try:
        for action, arguments in (("team_list", {}), ("team_get", {"team_id": "team-a"}),
            ("room_list", {}), ("room_get", {"room_id": "room-a"}),
            ("session_parameters_get", {"session_id": "session-a"})):
            result = await asyncio.to_thread(execute_action, action, {"project_id": "p", **arguments})
            assert result["projectId"] == "p" and result["untrustedContent"] is True
            for payload in (result, await asyncio.to_thread(execute_action, "describe", {"action": action})):
                raw, outcome, facts, rendered = _through_native_model_budget(payload)
                assert outcome is None and not facts.truncated
                assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "team_list", {"project_id": "other"})
        assert {entry[0] for entry in env.calls} >= {"team_list", "team_get", "room_list", "room_get", "session_parameters_get"}
        assert not (tmp_path / "profile" / "assistant_management").exists()
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_governed_upgrade_keeps_original_credentials_and_recovers_lost_ack(env, tmp_path, monkeypatch):
    import asyncio
    import json
    from copy import deepcopy
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.assistant_runtime.management import ManagementAdapter
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    original = ["agents:avatar", "agents:create", "agents:read", "agents:update", "platform:describe", "sessions:read", "teams:read", "teams:run"]
    additions = ["rooms:read", "sessions:parameters:read", "teams:directory:read"]
    state_path = tmp_path / "old-sdk.json"
    sdk = ManagedAgentBackendClient(tmp_path, state_path=state_path)
    sdk._state["management"] = {"clientId": "original_client_1234567890", "binding": env.binding, "scopes": original}
    request = _connect_sdk_http(sdk, env, monkeypatch)
    grant = await sdk._management_grant(require_existing=True)
    saved = deepcopy(sdk._state["management"])
    grant_path = env.service.store.path("subjects", grant["subjectId"])
    target = env.service.store.read(grant_path)
    target["existingTaskAssociations"] = {"task-old": "opaque-original-reference"}
    env.service.store.write(grant_path, target)
    clients = [sdk]
    async def call(project, operation):
        return await operation(clients[0])
    manager = ManagementAdapter(tmp_path / "profile", {"p": tmp_path}, call)
    service = SimpleNamespace(management=manager, project_ids=lambda: ["p"])
    lost = []
    async def lose_ack(method, path, **kwargs):
        result = await request(method, path, **kwargs)
        if method == "POST" and path.endswith("/actions/authorization_upgrade") and not lost:
            lost.append(True)
            raise BackendClientError("Synthetic lost acknowledgement", code="BACKEND_UNAVAILABLE")
        return result
    monkeypatch.setattr(sdk, "_request_json", lose_ack)
    args = {"project_id": "p", "request_id": "upgrade-1", "expected_scopes": original, "add_scopes": additions}
    bind_actions(service, asyncio.get_running_loop())
    try:
        denied = await asyncio.to_thread(execute_action, "authorization_upgrade", args)
        assert denied["status"] == "approval_required" and env.service.store.read(grant_path)["scopes"] == original
        with pytest.raises(BackendClientError):
            await asyncio.to_thread(execute_action, "authorization_upgrade", args, governed=True)
        assert sdk._state["management"] == saved
        restarted = ManagedAgentBackendClient(tmp_path, state_path=state_path)
        _connect_sdk_http(restarted, env, monkeypatch)
        clients[0] = restarted
        receipt = await asyncio.to_thread(execute_action, "management_receipt", {
            "project_id": "p", "action": "authorization_upgrade", "request_id": "upgrade-1"})
        assert receipt["status"] == "completed" and receipt["authorization"]["addedScopes"] == additions
        assert restarted._state["management"] == {**saved, "scopes": sorted(original + additions)}
        assert "agents:archive" not in restarted._state["management"]["scopes"] and "sessions:pin" not in restarted._state["management"]["scopes"]
        second = await asyncio.to_thread(execute_action, "authorization_upgrade", {"project_id": "p", "request_id": "upgrade-2",
            "expected_scopes": restarted._state["management"]["scopes"], "add_scopes": ["agents:archive"]}, governed=True)
        assert second["authorization"]["grantRevision"] == 2
        historical = await asyncio.to_thread(execute_action, "management_receipt", {
            "project_id": "p", "action": "authorization_upgrade", "request_id": "upgrade-1"})
        assert historical == receipt
        assert "agents:archive" in restarted._state["management"]["scopes"]
        assert env.service.store.read(grant_path)["existingTaskAssociations"] == target["existingTaskAssociations"]
        assert env.calls == []
        for payload in (receipt, await asyncio.to_thread(execute_action, "authorization_status", {"project_id": "p"}),
            await asyncio.to_thread(execute_action, "describe", {"action": "authorization_upgrade"})):
            raw, outcome, facts, rendered = _through_native_model_budget(payload)
            assert outcome is None and not facts.truncated
            assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
            assert grant["capability"] not in rendered and grant["clientId"] not in rendered
    finally:
        unbind_actions(service)
