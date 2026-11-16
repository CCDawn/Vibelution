"""Launcher Session creation is restricted to the verified, scoped caller."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.test_configured_agent_creation import configured_env  # noqa: F401 -- isolated native store
from tests.test_external_management_workspace import env  # noqa: F401 -- isolated native authorities

ACTION = "/v1/launcher-assistant-management/actions/session_create"
LAUNCHER_AUTHORITY_HEADER = "X-Vibelution-Launcher-Authority"
TOKEN = "verified-launcher-authority"


def create(env, *, request_id="create-1", parameters=None, headers=None):
    default_parameters = {"agent_id": getattr(env, "agent_id", "agent-a"), "title": "New Workspace"}
    return env.client.post(ACTION, headers=env.headers if headers is None else headers,
        json={"request_id": request_id, "expected_binding": env.identity,
              "parameters": default_parameters if parameters is None else parameters})


def test_session_creation_requires_scope_and_launcher_authority(env, monkeypatch):
    from core.infrastructure import launcher_assistant_authority

    monkeypatch.setattr(launcher_assistant_authority, "verify_launcher_authority", lambda token: token == TOKEN)
    without_launcher = create(env)
    assert without_launcher.status_code == 403 and without_launcher.json()["detail"]["code"] == "LAUNCHER_AUTHORITY_REQUIRED"
    without_scope = create(env, headers={**env.headers, LAUNCHER_AUTHORITY_HEADER: TOKEN})
    assert without_scope.status_code == 403 and without_scope.json()["detail"]["code"] == "SCOPE_DENIED"
    assert env.calls == []


def _scope(service, grant):
    result = service.invoke(grant["subject_id"], grant["subject_capability"], "authorization_upgrade",
        {"request_id": "add-session-create", "expected_binding": grant["binding"],
         "parameters": {"expected_scopes": grant["scopes"], "add_scopes": ["sessions:create"]}})
    assert result["verified"] and result["authorization"]["scopes"] == sorted([*grant["scopes"], "sessions:create"])
    return grant


def _headers(client_grant):
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes.launcher_assistant_management import CAPABILITY_HEADER, SUBJECT_HEADER

    return {CONTROL_TOKEN_HEADER: get_control_token(), SUBJECT_HEADER: client_grant["subject_id"],
            CAPABILITY_HEADER: client_grant["subject_capability"], LAUNCHER_AUTHORITY_HEADER: TOKEN}


@pytest.fixture
def native_env(configured_env, monkeypatch, request):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.infrastructure import launcher_assistant_authority
    from core.web.routes import launcher_assistant_management as route
    from core.web.services import agent_operation_service
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    from core.web.services.session import directory_runtime
    from core.web.services.team import team_store

    root, directory, sessions, store = (configured_env[key] for key in ("root", "directory", "sessions", "store"))
    monkeypatch.setattr(directory_runtime, "_STORE", store)
    monkeypatch.setattr(directory_runtime, "_PROJECT_ROOT", root)
    config = directory.CONFIG_PATH
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    roster = team_store._teams_index_path(seed=False)
    roster.parent.mkdir(parents=True, exist_ok=True)
    roster.write_text('{"teams":[]}', encoding="utf-8")
    agent_options = {"display_name": "Session creation target", "primary_mode": "chat", "role_key": "assistant_worker",
                     "prompt_template_id": "prompt-chat-default", "llm_bindings": {"dialogue": {"modelId": "model-primary"}},
                     "tool_policy": {"allowedTools": []}, "source": "session-create-test"}
    agent = agent_operation_service.create_configured_agent_with_session(
        **{**agent_options, "role_key": getattr(request, "param", "assistant_worker")})
    other = agent_operation_service.create_configured_agent_with_session(**{**agent_options, "display_name": "Selected"})
    sessions.select_chat_session(other["directSessionId"], lightweight=True)
    identity = {"projectId": "target", "instanceId": "backend"}
    native = NativeAgentGateway(root)
    service = ManagementService(root / "management", identity=lambda: TargetIdentity(identity, "control"), native=native)
    grant = _scope(service, service.bind({"client_id": "launcher-test", "expected_binding": identity, "scopes": ["sessions:read"]}))
    monkeypatch.setattr(launcher_assistant_authority, "verify_launcher_authority", lambda token: token == TOKEN)
    monkeypatch.setattr(route, "_SERVICE", service)
    app = FastAPI()
    app.include_router(route.router)
    return SimpleNamespace(root=root, directory=directory, sessions=sessions, store=store, native=native, service=service,
        client=TestClient(app), identity=identity, grant=grant, headers=_headers(grant), roster=roster,
        agent_id=agent["agentId"], main_id=agent["directSessionId"], selected_id=other["directSessionId"])


@pytest.mark.parametrize("native_env", ["assistant_worker", ""], indirect=True)
def test_real_session_writer_creates_visible_workspace_and_never_recreates_deleted_session(native_env, monkeypatch):
    e = native_env
    before_main = e.store.repository.get_session_runtime_state(e.main_id)
    before_selected = e.store.repository.get_session_runtime_state(e.selected_id)
    before_registry = e.directory._workspace_path("agents", "agents.json", intent="state", seed=False).read_bytes()
    writes = []
    writer = e.sessions.create_chat_session

    def observed(**kwargs):
        writes.append(kwargs)
        return writer(**kwargs)

    monkeypatch.setattr(e.sessions, "create_chat_session", observed)
    first = create(e)
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["status"] == "completed" and receipt["verified"] is True, first.text
    new_id = receipt["session"]["id"]
    assert new_id not in {e.main_id, e.selected_id}
    assert receipt["session"]["agentId"] == e.agent_id and receipt["session"]["title"] == "New Workspace"
    assert "pinnedAtMs" not in receipt["session"]
    assert writes[0]["activate"] is False and writes[0]["lightweight"] is True
    assert writes[0]["created_by"] == "launcher_assistant"
    assert e.sessions.load_active_conversation_id(e.root) == e.selected_id
    assert e.directory.get_agent(e.agent_id)["directSessionId"] == e.main_id
    assert e.store.repository.get_session_runtime_state(e.main_id) == before_main
    assert e.store.repository.get_session_runtime_state(e.selected_id) == before_selected
    assert e.directory._workspace_path("agents", "agents.json", intent="state", seed=False).read_bytes() == before_registry
    assert e.store.repository.get_session(new_id)["sessionRole"] == "workspace"
    native_index = {item["id"]: item for item in e.sessions.list_sessions()}
    assert native_index[new_id]["title"] == receipt["session"]["title"]

    e.sessions.delete_chat_session(new_id)
    assert e.store.repository.get_session(new_id, include_archived=False) is None
    assert create(e).json() == {**receipt, "reused": True}
    assert e.store.repository.get_session(new_id, include_archived=False) is None and len(writes) == 1
    assert e.sessions.load_active_conversation_id(e.root) == e.selected_id
    conflict = create(e, parameters={"agent_id": e.agent_id, "title": "Changed"})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("target", ["missing", "archived", "hidden", "protected", "personal-assistant", "team", "companion"])
def test_native_writer_rejects_nonordinary_or_inactive_agent(native_env, monkeypatch, target):
    e = native_env
    registry = e.directory._workspace_path("agents", "agents.json", intent="state", seed=False)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    agent = next(row for row in payload["agents"] if row["agentId"] == e.agent_id)
    target_id = e.agent_id
    if target == "missing":
        target_id = "absent-agent"
    elif target == "archived":
        agent["status"] = "archived"
    elif target == "hidden":
        agent["metadata"]["conversationIndexVisibility"] = "hidden"
    elif target == "protected":
        agent["metadata"]["fixedRole"] = True
    elif target == "personal-assistant":
        agent["roleKey"] = "personal-assistant"
    elif target == "team":
        e.roster.write_text(json.dumps({"teams": [{"teamId": "team", "members": [{"agentId": e.agent_id}]}]}), encoding="utf-8")
    else:
        agent["metadata"]["virtualHumanCompanion"] = True
    registry.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(e.sessions, "create_chat_session", lambda **_: pytest.fail("Private or missing target reached the writer"))
    response = create(e, parameters={"agent_id": target_id, "title": "New Workspace"})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "AGENT_UNAVAILABLE", response.text
    assert e.sessions.load_active_conversation_id(e.root) == e.selected_id
    assert e.store.repository.get_session(e.main_id)["agentId"] == e.agent_id


@pytest.mark.parametrize("write_applied", [False, True])
def test_lost_native_ack_reconciles_read_only_after_restart(native_env, monkeypatch, write_applied):
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management.service import ManagementService

    e = native_env
    writes = []
    writer = e.sessions.create_chat_session

    def lost_ack(**kwargs):
        writes.append(kwargs)
        if write_applied:
            writer(**kwargs)
        raise TimeoutError("uncertain native acknowledgement")

    monkeypatch.setattr(e.sessions, "create_chat_session", lost_ack)
    first = create(e).json()
    assert first == {"status": "unknown", "action": "session_create", "requestId": "create-1",
                     "verified": False, "reused": False, "code": "OPERATION_UNCONFIRMED"}
    restarted = ManagementService(e.service.root, identity=e.service.identity, native=e.native)
    monkeypatch.setattr(route, "_SERVICE", restarted)
    target = e.client.get(ACTION + "/requests/create-1/reconciliation", headers=e.headers)
    assert target.status_code == 200, target.text
    assert target.json()["verified"] is write_applied
    assert target.json()["target"] == {"agent_id": e.agent_id}
    receipt = e.client.get(ACTION + "/requests/create-1", headers=e.headers).json()
    assert receipt["status"] == ("completed" if write_applied else "unknown")
    assert create(e).json() == receipt and len(writes) == 1


@pytest.mark.parametrize("extra", [{"activate": True}, {"session_id": "existing"}, {"agent_id": "Missing/agent"},
    {"title": "   "}, {"title": "multi\nline"}, {"title": "a\u202eb"}, {"title": "x" * 121}])
def test_session_creation_parameters_are_closed_and_strict(env, monkeypatch, extra):
    from core.infrastructure import launcher_assistant_authority

    monkeypatch.setattr(launcher_assistant_authority, "verify_launcher_authority", lambda token: token == TOKEN)
    headers = _headers(_scope(env.service, env.grant))
    response = create(env, headers=headers, parameters={"agent_id": "agent-a", "title": "New Workspace", **extra})
    assert response.status_code == 422 and env.calls == []


def test_grant_is_explicit_and_receipt_is_bound_to_original_subject(env, monkeypatch):
    from core.infrastructure import launcher_assistant_authority
    from core.web.services.external_management.service import ManagementError

    monkeypatch.setattr(launcher_assistant_authority, "verify_launcher_authority", lambda token: token == TOKEN)
    assert "sessions:create" not in env.service.binding()["scopes"]
    assert env.service.binding()["actions"]["session_create"]["scope"] == "sessions:create"
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service.bind({"client_id": "fresh", "expected_binding": env.identity, "scopes": ["sessions:create"]})
    headers = _headers(_scope(env.service, env.grant))
    other = _headers(_scope(env.service, env.service.bind({"client_id": "other", "expected_binding": env.identity,
                                                          "scopes": ["sessions:read"]})))
    forged = {**headers, "X-Vibelution-Management-Capability": other["X-Vibelution-Management-Capability"]}
    assert create(env, headers=forged).json()["detail"]["code"] == "SUBJECT_DENIED"
    assert create(env, headers={**headers, LAUNCHER_AUTHORITY_HEADER: "stale"}).json()["detail"]["code"] == "LAUNCHER_AUTHORITY_REQUIRED"
    with monkeypatch.context() as patch:
        patch.setattr(env.native, "create_session", lambda *_args: None)
        patch.setattr(env.native, "confirm_session_creation", lambda *_args: None)
        assert create(env, headers=headers).json()["status"] == "unknown"
        assert env.client.get(ACTION + "/requests/create-1", headers=other).json()["detail"]["code"] == "REQUEST_UNAVAILABLE"
    assert env.calls == []


def test_receipt_rejects_an_intent_with_a_replaced_request_identity(env, monkeypatch):
    from core.infrastructure import launcher_assistant_authority

    monkeypatch.setattr(launcher_assistant_authority, "verify_launcher_authority", lambda token: token == TOKEN)
    headers = _headers(_scope(env.service, env.grant))
    monkeypatch.setattr(env.native, "create_session", lambda *_args: None)
    monkeypatch.setattr(env.native, "confirm_session_creation", lambda *_args: None)
    assert create(env, headers=headers).json()["status"] == "unknown"
    key = env.service._request_key(env.grant["subject_id"], "session_create", "create-1")
    path = env.service.store.path("requests", key)
    record = env.service.store.read(path)
    record["marker"]["requestKey"] = "other-request"
    env.service.store.write(path, record)
    monkeypatch.setattr(env.native, "confirm_session_creation", lambda *_args: pytest.fail("Wrong intent reached readback"))
    assert create(env, headers=headers).json()["detail"]["code"] == "TARGET_BINDING_CHANGED"
    assert env.client.get(ACTION + "/requests/create-1", headers=headers).json()["detail"]["code"] == "TARGET_BINDING_CHANGED"


@pytest.mark.anyio
async def test_sdk_launcher_authority_is_sent_only_on_creation_and_receipt_is_agent_bound(tmp_path, monkeypatch):
    import httpx

    from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient

    requests = []
    binding = {"projectId": "p", "instanceId": "i"}
    result = {"status": "completed", "action": "session_create", "requestId": "new-1", "verified": True,
              "reused": False, "session": {"id": "new-session", "title": "New Workspace", "agentId": "agent-a",
                                           "archived": False, "status": "ready", "pinned": False}}

    def handle(request):
        requests.append(request)
        if request.method == "POST" and LAUNCHER_AUTHORITY_HEADER not in request.headers:
            return httpx.Response(403, json={"detail": {"code": "LAUNCHER_AUTHORITY_REQUIRED"}})
        return httpx.Response(200, json=result)

    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "sdk-state.json", transport=httpx.MockTransport(handle))

    async def local_binding():
        client._base_url = "http://127.0.0.1:1234"

    async def subject(**_):
        return {"subjectId": "subject-auth", "capability": "subject-capability", "binding": binding}

    monkeypatch.setattr(client, "_ensure_connected", local_binding)
    monkeypatch.setattr(client, "_management_grant", subject)
    parameters = {"agent_id": "agent-a", "title": "New Workspace"}
    with pytest.raises(BackendClientError, match="LAUNCHER_AUTHORITY_REQUIRED"):
        await client.management_action(action="session_create", request_id="new-1", parameters=parameters)
    monkeypatch.setattr(client, "_session_create_launcher_authority", lambda: TOKEN)
    completed = await client.management_action(action="session_create", request_id="new-1", parameters=parameters)
    assert completed["session"]["id"] == "new-session"
    assert await client.management_receipt(action="session_create", request_id="new-1") == completed
    assert [request.headers.get(LAUNCHER_AUTHORITY_HEADER) for request in requests] == [None, TOKEN, None]
    assert requests[1].headers["X-Vibelution-Management-Capability"] == "subject-capability"
    result["session"]["agentId"] = "foreign-agent"
    with pytest.raises(BackendClientError) as invalid:
        await client.management_action(action="session_create", request_id="new-1", parameters=parameters)
    assert invalid.value.code == "BACKEND_PROTOCOL_ERROR"
