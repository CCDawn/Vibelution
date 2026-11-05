from __future__ import annotations

import json
import ssl
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from core.external_agent.backend_client import (
    BackendClientError,
    ManagedAgentBackendClient,
)


@pytest.mark.anyio
@pytest.mark.parametrize("eligibility", [None, {"eligible": True, "reason": "ordinary_agent"},
    {"eligible": False, "reason": "protected_agent"}, {"eligible": "yes", "reason": "ordinary_agent"}])
async def test_management_agent_archive_eligibility_is_optional_and_validated(tmp_path, monkeypatch, eligibility):
    client = ManagedAgentBackendClient(tmp_path)
    agent = {"agentId": "legacy-agent", "directSessionId": "session", "displayName": "Legacy",
             "configRevision": 3, "updatedAt": "now", "modelId": "model", "avatarImagePath": ""}
    async def grant(**_kwargs):
        return {"subjectId": "subject", "capability": "private-capability"}
    async def request(*_args, **_kwargs):
        return {"agent": agent, **({"archiveEligibility": eligibility} if eligibility is not None else {})}
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    if eligibility is not None and eligibility["eligible"] == "yes":
        with pytest.raises(BackendClientError) as invalid:
            await client.management_agent(agent_id="legacy-agent")
        assert invalid.value.code == "BACKEND_PROTOCOL_ERROR"
    else:
        result = await client.management_agent(agent_id="legacy-agent")
        assert result["agent"]["agentId"] == "legacy-agent"
        assert result.get("archiveEligibility") == eligibility


@pytest.fixture
def default_httpx_transport(tmp_path, monkeypatch):
    """Exercise real HTTPX construction while replacing only network I/O."""
    from httpx._transports import default

    calls, contexts = [], []
    wire = _transport(tmp_path, calls)
    create_context = default.create_ssl_context

    def record_context(*args, **kwargs):
        context = create_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def send(_transport, request):
        return await wire.handle_async_request(request)

    monkeypatch.setattr(default, "create_ssl_context", record_context)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    return calls, contexts


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["http://127.0.0.1:8123", "http://localhost:8123", "http://[::1]:8123"])
async def test_http_client_does_not_load_unused_ca_for_handshake_or_requests(
    tmp_path, monkeypatch, default_httpx_transport, url,
):
    _runtime_state(tmp_path, url=url)
    calls, contexts = default_httpx_transport

    def unused_ca(*args, **kwargs):
        raise AssertionError("plain HTTP must not load a TLS trust store")

    monkeypatch.setattr(ssl, "create_default_context", unused_ca)
    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", unused_ca)
    monkeypatch.setenv("HTTP_PROXY", "http://foreign.invalid:9999")
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "state.json")
    assert (await client.list_agents())["agents"] == []
    assert (await client.list_agents())["agents"] == []
    assert len(calls) == 4 and all(str(request.url).startswith(url + "/") for request in calls)
    assert len(contexts) == 3 and len({id(context) for context in contexts}) == 3
    # An unexpected TLS use would still fail closed, rather than disabling
    # certificate or hostname checks for a transport that only needs HTTP.
    assert all(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
               and context.cert_store_stats()["x509_ca"] == 0 for context in contexts)


@pytest.mark.anyio
async def test_https_client_keeps_default_ca_and_hostname_verification(
    tmp_path, monkeypatch, default_httpx_transport,
):
    _runtime_state(tmp_path, url="https://127.0.0.1:8123")
    calls, contexts = default_httpx_transport
    create_context = ssl.create_default_context
    trust_loads = []

    def load_default_trust(*args, **kwargs):
        trust_loads.append(kwargs)
        return create_context(*args, **kwargs)

    monkeypatch.setattr(ssl, "create_default_context", load_default_trust)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "state.json")
    assert (await client.list_agents())["agents"] == []
    assert len(calls) == 3 and len(trust_loads) == len(contexts) == 2
    assert all(load.get("cafile") for load in trust_loads)
    assert all(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
               and context.cert_store_stats()["x509_ca"] > 0 for context in contexts)


@pytest.mark.anyio
@pytest.mark.parametrize("redirect_stage", ["control-token", "info", "agents"])
@pytest.mark.parametrize("target", ["http://foreign.invalid/private", "https://127.0.0.1:8123/private"])
async def test_http_client_never_follows_handshake_or_request_redirects(tmp_path, redirect_stage, target):
    _runtime_state(tmp_path)
    calls = []
    ordinary = _transport(tmp_path, [])

    def handler(request):
        calls.append(request)
        if request.url.path.rsplit("/", 1)[-1] == redirect_stage:
            return httpx.Response(307, headers={"Location": target}, json={"agents": []})
        assert request.url.host == "127.0.0.1" and request.url.path != "/private"
        return ordinary.handle_request(request)

    client = ManagedAgentBackendClient(
        tmp_path, state_path=tmp_path / "state.json", transport=httpx.MockTransport(handler),
    )
    if redirect_stage == "agents":
        assert await client.list_agents() == {"agents": []}
    else:
        with pytest.raises(BackendClientError):
            await client.list_agents()
    assert len(calls) == {"control-token": 1, "info": 2, "agents": 3}[redirect_stage]


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["http://foreign.invalid:8123", "https://foreign.invalid:8123",
                                  "http://127.0.0.1.foreign.invalid:8123", "ftp://127.0.0.1:8123"])
async def test_foreign_runtime_descriptor_is_rejected_before_client_construction(tmp_path, monkeypatch, url):
    _runtime_state(tmp_path, url=url)

    def forbidden_client(*args, **kwargs):
        raise AssertionError("untrusted runtime must be rejected before constructing a transport")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", forbidden_client)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "state.json")
    with pytest.raises(BackendClientError) as rejected:
        await client.list_agents()
    assert rejected.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_bound_preview_uses_original_task_capability_and_rejects_oversize(tmp_path, monkeypatch):
    requests = []
    too_large = False
    def handler(request):
        requests.append(request)
        if too_large:
            return httpx.Response(200, content=b'{' + b' ' * (4 * 1024 * 1024) + b'}')
        return httpx.Response(200, json={"taskId": "task-1", "requestId": "approval-1"})
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "state.json", transport=httpx.MockTransport(handler))
    client._verified, client._base_url, client._control_token = True, "http://127.0.0.1", "control"
    async def task_state(task_id):
        assert task_id == "task-1"
        return {"taskCapability": "original-capability"}
    monkeypatch.setattr(client, "_task_state", task_state)
    await client.preview_bound_approval(task_id="task-1", approval_id="approval-1")
    assert requests[-1].headers["X-Vibelution-External-Agent-Task-Capability"] == "original-capability"
    assert requests[-1].url.path.endswith("/tasks/task-1/approvals/approval-1/preview")
    too_large = True
    with pytest.raises(BackendClientError) as failure:
        await client.preview_bound_approval(task_id="task-1", approval_id="approval-1")
    assert failure.value.code == "BACKEND_RESPONSE_TOO_LARGE"


@pytest.fixture
def directory_client(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "directory-credentials.json")
    state = {"calls": [], "payload": {}}
    async def grant(**kwargs):
        return {"subjectId": "subject", "capability": "test-capability"}
    async def request(method, path, **kwargs):
        state["calls"].append((method, path))
        if path.endswith("/sessions/session-a"):
            return {"session": {"id": "session-a", "title": "Visible", "agentId": "agent-a",
                "pinned": False, "pinnedAtMs": None, "status": "ready", "archived": False}, "untrustedContent": True}
        return deepcopy(state["payload"])
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    return client, state


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["team", "room"])
async def test_directory_sdk_pages_and_closed_queries(directory_client, kind):
    client, state = directory_client
    item = ({"id": "team-a", "name": "Name", "purpose": "Goal", "status": "active", "memberCount": 1}
        if kind == "team" else {"id": "room-a", "title": "Title", "status": "ready"})
    key = kind + "s"
    state["payload"] = {key: [item], "total": 1, "offset": 0, "nextOffset": None, "untrustedContent": True}
    call = getattr(client, "management_" + kind + "_list")
    assert await call(limit=1) == state["payload"]
    assert "/directory/" + key + "?" in state["calls"][-1][1]
    count = len(state["calls"])
    for parameters in ({"limit": 7}, {"limit": True}, {"offset": "0"}, {"archived": 1}, {"query": "line\nbody"}, {"path": "private"}):
        with pytest.raises(BackendClientError) as denied:
            await call(**parameters)
        assert denied.value.code == "INVALID_MANAGEMENT_REQUEST"
    assert len(state["calls"]) == count
    for patch in ({"offset": 1}, {"untrustedContent": 1}, {"messages": ["PRIVATE"]}, {"total": 0}):
        original = deepcopy(state["payload"])
        state["payload"].update(patch)
        with pytest.raises(BackendClientError) as denied:
            await call(limit=1)
        assert denied.value.code == "BACKEND_PROTOCOL_ERROR"
        state["payload"] = original


@pytest.mark.anyio
async def test_directory_sdk_details_bind_identity_and_member_offset(directory_client):
    client, state = directory_client
    state["payload"] = {"team": {"id": "team-a", "name": "Name", "purpose": "Goal", "status": "active",
        "members": [{"agentId": "agent-a"}], "memberOffset": 1, "memberTotal": 2, "nextMemberOffset": None}, "untrustedContent": True}
    assert (await client.management_team(team_id="team-a", member_offset=1, limit=1))["team"]["memberOffset"] == 1
    for patch in ({"id": "team-b"}, {"memberOffset": 0, "nextMemberOffset": 1}, {"prompt": "PRIVATE"}):
        original = deepcopy(state["payload"])
        state["payload"]["team"].update(patch)
        with pytest.raises(BackendClientError):
            await client.management_team(team_id="team-a", member_offset=1, limit=1)
        state["payload"] = original
    state["payload"] = {"room": {"id": "room-a", "title": "Title", "status": "ready"}, "untrustedContent": True}
    assert (await client.management_room(room_id="room-a"))["room"]["id"] == "room-a"
    state["payload"]["room"]["id"] = "room-b"
    with pytest.raises(BackendClientError):
        await client.management_room(room_id="room-a")


@pytest.mark.anyio
async def test_parameter_sdk_binds_session_agent_and_closed_effective_snapshot(directory_client):
    client, state = directory_client
    state["payload"] = {"source": "native-current-agent-runtime-parameters", "catalogState": "absent", "untrustedContent": True,
        "parameters": {"sessionId": "session-a", "agentId": "agent-a", "configRevision": 3,
            "currentModelId": "provider/model", "currentReasoningEffort": "high", "reasoningEffortValues": ["low", "high"],
            "contextWindow": 32000, "maxContextWindow": 64000, "budget": {"revision": 3, "maxCallsPerTurn": 0}}}
    assert (await client.management_session_parameters(session_id="session-a"))["parameters"]["budget"]["maxCallsPerTurn"] == 0
    for patch in ({"agentId": "agent-b"}, {"sessionId": "session-b"}, {"configRevision": True},
        {"budget": {"revision": 4, "maxCallsPerTurn": 0}}, {"contextWindow": 128000}, {"provider": {"api_key": "PRIVATE"}}):
        original = deepcopy(state["payload"])
        state["payload"]["parameters"].update(patch)
        with pytest.raises(BackendClientError):
            await client.management_session_parameters(session_id="session-a")
        state["payload"] = original


@pytest.mark.anyio
async def test_session_pin_sdk_allowlist_and_closed_session_receipt(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    calls = []
    payload = {"status": "completed", "action": "session_pin", "requestId": "pin-1", "verified": True,
        "reused": False, "session": {"id": "session-a", "title": "Visible", "agentId": "agent-a",
            "pinnedAtMs": 123, "pinned": True, "status": "ready", "archived": False}}
    async def grant(**kwargs):
        return {"subjectId": "subject", "capability": "capability", "binding": {"projectId": "p", "instanceId": "i"}}
    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return deepcopy(payload)
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    result = await client.management_action(action="session_pin", request_id="pin-1",
        parameters={"session_id": "session-a", "pinned": True})
    assert result == payload and calls[0][0] == "POST"
    assert calls[0][2]["json_payload"]["parameters"] == {"session_id": "session-a", "pinned": True}
    for patch in ({"pinned": "true"}, {"pinned": 1}, {"agentId": "foreign"}, {"actor": "operator"}):
        with pytest.raises(BackendClientError) as invalid:
            await client.management_action(action="session_pin", request_id="pin-1",
                parameters={"session_id": "session-a", "pinned": True, **patch})
        assert invalid.value.code == "INVALID_MANAGEMENT_REQUEST" and len(calls) == 1
    payload["session"]["id"] = "other"
    with pytest.raises(BackendClientError) as mismatch:
        await client.management_action(action="session_pin", request_id="pin-1",
            parameters={"session_id": "session-a", "pinned": True})
    assert mismatch.value.code == "BACKEND_PROTOCOL_ERROR"
    payload["session"]["id"] = "session-a"
    await client.management_receipt(action="session_pin", request_id="pin-1")
    assert calls[-1][0] == "GET"
    for patch in ({"pinned": 1}, {"prompt": "PRIVATE"}, {"pinnedAtMs": "123"}):
        original = deepcopy(payload["session"])
        payload["session"].update(patch)
        with pytest.raises(BackendClientError) as invalid:
            await client.management_receipt(action="session_pin", request_id="pin-1")
        assert invalid.value.code == "BACKEND_PROTOCOL_ERROR"
        payload["session"] = original
    payload.pop("session")
    with pytest.raises(BackendClientError):
        await client.management_receipt(action="session_pin", request_id="pin-1")


@pytest.mark.anyio
async def test_management_legacy_subject_retains_original_scope_set(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    binding = {"projectId": "p", "instanceId": "i"}
    client._state["management"] = {"clientId": "legacy_client_1234567890", "binding": binding,
        "subjectId": "ops-1234567890abcdef", "capability": "a" * 48}
    calls = []
    async def request(method, path, **kwargs):
        if path.endswith("/binding"):
            return {"protocolVersion": 1, "binding": binding}
        body = kwargs["json_payload"]
        calls.append(body)
        assert "sessions:pin" not in body["scopes"] and "agents:archive" not in body["scopes"] and len(body["scopes"]) == 8
        return {"protocolVersion": 1, "binding": binding, "scopes": body["scopes"],
            "subject_id": "ops-1234567890abcdef", "subject_capability": "a" * 48}
    monkeypatch.setattr(client, "_request_json", request)
    await client._management_grant(require_existing=True)
    assert len(calls) == 1 and calls[0]["client_id"] == "legacy_client_1234567890"
    assert "sessions:pin" not in client._state["management"]["scopes"]


@pytest.fixture
def management_agent_client(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    binding = {"projectId": "project-1", "instanceId": "instance-1"}
    saved = {"clientId": "saved_client_1234567890", "binding": binding,
        "subjectId": "ops-1234567890abcdef", "capability": "a" * 48,
        "scopes": ["agents:read", "agents:update"]}
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"projectRoot": str(tmp_path.resolve()), "management": saved}), encoding="utf-8")
    state = {"calls": [], "saves": [], "binding": deepcopy(binding), "status": 200,
        "payload": {"agent": {"agentId": "agent-1", "name": "Visible"}}}
    ordinary = _transport(tmp_path, [])

    def handler(request):
        if not request.url.path.startswith("/api/v1/launcher-assistant-management/"):
            return ordinary.handle_request(request)
        state["calls"].append(request)
        if request.url.path.endswith("/binding"):
            if "binding_error" in state:
                return httpx.Response(403, json={"detail": {"code": state["binding_error"]}})
            return httpx.Response(200, json=state.get("binding_response", {"protocolVersion": 1, "binding": state["binding"]}))
        if request.url.path.endswith("/subjects/bind"):
            body = json.loads(request.content)
            return httpx.Response(200, json={"protocolVersion": 1, "binding": state["binding"],
                "subject_id": saved["subjectId"], "subject_capability": saved["capability"], "scopes": body["scopes"]})
        assert request.url.path.endswith("/agents/agent-1")
        assert request.headers["X-Vibelution-Management-Subject"] == saved["subjectId"]
        assert request.headers["X-Vibelution-Management-Capability"] == saved["capability"]
        return httpx.Response(state["status"], json=state["payload"])

    client = ManagedAgentBackendClient(tmp_path, state_path=path, transport=httpx.MockTransport(handler))
    save = client._save_state_locked

    def record_save():
        state["saves"].append(deepcopy(client._state["management"]))
        save()

    monkeypatch.setattr(client, "_save_state_locked", record_save)
    return client, state


@pytest.mark.anyio
@pytest.mark.parametrize("legacy_scopes", [False, True])
async def test_management_agent_reuses_saved_grant_without_bind_or_save(management_agent_client, legacy_scopes):
    client, state = management_agent_client
    if legacy_scopes:
        client._state["management"].pop("scopes")
        client.state_path.write_text(json.dumps(client._state), encoding="utf-8")
    original = deepcopy(client._state["management"])
    persisted = client.state_path.read_bytes()

    for _ in range(2):
        result = await client.management_agent(agent_id="agent-1")
        assert result["agent"]["agentId"] == "agent-1"

    assert [(request.method, request.url.path.rsplit("/", 1)[-1]) for request in state["calls"]] == [
        ("GET", "binding"), ("GET", "agent-1"), ("GET", "binding"), ("GET", "agent-1")]
    assert state["saves"] == []
    assert client._state["management"] == original
    assert client.state_path.read_bytes() == persisted


@pytest.mark.anyio
@pytest.mark.parametrize("missing", ["fresh", "clientId", "binding", "capability", "legacy-capability"])
async def test_management_agent_incomplete_grant_keeps_original_bind_flow(management_agent_client, missing):
    from core.external_agent.backend_client import _LEGACY_MANAGEMENT_SCOPES, _MANAGEMENT_SCOPES
    client, state = management_agent_client
    original = deepcopy(client._state["management"])
    if missing == "fresh":
        client._state["management"] = {}
    elif missing == "legacy-capability":
        client._state["management"].pop("capability")
        client._state["management"].pop("scopes")
    else:
        client._state["management"].pop(missing)

    assert (await client.management_agent(agent_id="agent-1"))["agent"]["agentId"] == "agent-1"
    assert [(request.method, request.url.path.rsplit("/", 1)[-1]) for request in state["calls"]] == [
        ("GET", "binding"), ("POST", "bind"), ("GET", "agent-1")]
    body = json.loads(state["calls"][1].content)
    assert body["expected_binding"] == original["binding"]
    if missing in {"fresh", "clientId"}:
        assert body["client_id"] != original["clientId"]
    else:
        assert body["client_id"] == original["clientId"]
    assert body["scopes"] == (_MANAGEMENT_SCOPES if missing == "fresh" else
        _LEGACY_MANAGEMENT_SCOPES if missing == "legacy-capability" else original["scopes"])
    assert len(state["saves"]) == 2
    assert state["saves"][0]["clientId"] == state["saves"][1]["clientId"] == body["client_id"]
    assert json.loads(client.state_path.read_text(encoding="utf-8"))["management"] == client._state["management"]


@pytest.mark.anyio
@pytest.mark.parametrize("complete", [False, True])
async def test_management_agent_known_revoked_grant_never_remints(management_agent_client, complete):
    client, state = management_agent_client
    client._state["management"]["revoked"] = True
    if not complete:
        client._state["management"].pop("capability")
    original = deepcopy(client._state["management"])
    with pytest.raises(BackendClientError) as denied:
        await client.management_agent(agent_id="agent-1")
    assert denied.value.code == "SUBJECT_REVOKED"
    assert state["calls"] == state["saves"] == []
    assert client._state["management"] == original


@pytest.mark.anyio
@pytest.mark.parametrize("patch,code", [
    ({"clientId": "short"}, "UNKNOWN_MANAGEMENT_SUBJECT"),
    ({"clientId": "invalid!client_1234567890"}, "UNKNOWN_MANAGEMENT_SUBJECT"),
    *[({"scopes": scopes}, "UNKNOWN_MANAGEMENT_SUBJECT") for scopes in (
        None, [], "agents:read", [1], ["unknown:scope"], ["agents:read", "agents:read"], ["agents:update", "agents:read"])],
    ({"subjectId": "invalid-subject"}, "MANAGEMENT_IDENTITY_ROTATED"),
    ({"capability": "invalid-capability"}, "MANAGEMENT_IDENTITY_ROTATED"),
    ({"binding": {"projectId": "project-1"}}, "MANAGEMENT_IDENTITY_ROTATED"),
])
async def test_management_agent_malformed_grant_never_remints(management_agent_client, patch, code):
    client, state = management_agent_client
    client._state["management"].update(deepcopy(patch))
    original = deepcopy(client._state["management"])
    persisted = client.state_path.read_bytes()
    with pytest.raises(BackendClientError) as denied:
        await client.management_agent(agent_id="agent-1")
    assert denied.value.code == code
    assert state["calls"] == state["saves"] == []
    assert client._state["management"] == original
    assert client.state_path.read_bytes() == persisted


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["invalid-json", "foreign-root", "invalid-management"])
async def test_management_agent_unreadable_credentials_never_remints(management_agent_client, fault):
    client, state = management_agent_client
    payload = deepcopy(client._state)
    if fault == "foreign-root":
        payload["projectRoot"] = str(client.project_root / "foreign")
    elif fault == "invalid-management":
        payload["management"] = []
    client.state_path.write_text("{" if fault == "invalid-json" else json.dumps(payload), encoding="utf-8")
    persisted = client.state_path.read_bytes()
    reloaded = ManagedAgentBackendClient(client.project_root, state_path=client.state_path, transport=client.transport)
    with pytest.raises(BackendClientError) as denied:
        await reloaded.management_agent(agent_id="agent-1")
    assert denied.value.code == "UNKNOWN_MANAGEMENT_SUBJECT"
    assert state["calls"] == state["saves"] == []
    assert client.state_path.read_bytes() == persisted


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["projectId", "instanceId"])
async def test_management_agent_binding_rotation_keeps_original_credentials(management_agent_client, field):
    client, state = management_agent_client
    original = deepcopy(client._state["management"])
    persisted = client.state_path.read_bytes()
    state["binding"][field] = "rotated"
    with pytest.raises(BackendClientError) as denied:
        await client.management_agent(agent_id="agent-1")
    assert denied.value.code == "MANAGEMENT_IDENTITY_ROTATED"
    assert "management_reset_credentials" in str(denied.value)
    assert len(state["calls"]) == 1 and state["calls"][0].url.path.endswith("/binding")
    assert state["saves"] == [] and client._state["management"] == original
    assert client.state_path.read_bytes() == persisted


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["agent", "original"])
@pytest.mark.parametrize("response", [
    {"protocolVersion": 2, "binding": {"projectId": "project-1", "instanceId": "instance-1"}},
    {"binding": {"projectId": "project-1", "instanceId": "instance-1"}},
    *[{"protocolVersion": 1, "binding": binding} for binding in (
        None, [], {"projectId": "project-1"},
        {"projectId": "project-1", "instanceId": "instance-1", "extra": "invalid"},
        {"projectId": "", "instanceId": "instance-1"}, {"projectId": 1, "instanceId": "instance-1"},
        {"projectId": "x" * 161, "instanceId": "instance-1"})],
])
async def test_management_agent_malformed_live_binding_keeps_error_semantics(management_agent_client, operation, response):
    client, state = management_agent_client
    original = deepcopy(client._state["management"])
    state["binding_response"] = response
    with pytest.raises(BackendClientError) as denied:
        if operation == "agent":
            await client.management_agent(agent_id="agent-1")
        else:
            await client._original_management_grant(require_original=False)
    assert denied.value.code == ("BACKEND_PROTOCOL_ERROR" if operation == "agent" else "MANAGEMENT_IDENTITY_ROTATED")
    assert len(state["calls"]) == 1 and state["calls"][0].url.path.endswith("/binding")
    assert state["saves"] == [] and client._state["management"] == original


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["binding", "agent"])
@pytest.mark.parametrize("code", ["SUBJECT_REVOKED", "UNKNOWN_MANAGEMENT_SUBJECT", "SCOPE_DENIED", "RUNTIME_IDENTITY_MISMATCH"])
async def test_management_agent_server_denial_never_rebinds(management_agent_client, stage, code):
    client, state = management_agent_client
    original = deepcopy(client._state["management"])
    persisted = client.state_path.read_bytes()
    if stage == "binding":
        state["binding_error"] = code
    else:
        state.update(status=403, payload={"detail": {"code": code}})
    with pytest.raises(BackendClientError) as denied:
        await client.management_agent(agent_id="agent-1")
    assert denied.value.code == code
    assert len(state["calls"]) == (1 if stage == "binding" else 2)
    assert all(request.method == "GET" for request in state["calls"])
    assert state["saves"] == [] and client._state["management"] == original
    assert client.state_path.read_bytes() == persisted


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [{}, {"agent": []}, {"agent": {"agentId": "other-agent"}}, []])
async def test_management_agent_invalid_response_never_rebinds(management_agent_client, payload):
    client, state = management_agent_client
    original = deepcopy(client._state["management"])
    state["payload"] = payload
    with pytest.raises(BackendClientError) as denied:
        await client.management_agent(agent_id="agent-1")
    assert denied.value.code == "BACKEND_PROTOCOL_ERROR"
    assert len(state["calls"]) == 2 and all(request.method == "GET" for request in state["calls"])
    assert state["saves"] == [] and client._state["management"] == original


@pytest.mark.anyio
async def test_explicit_file_scope_is_accepted_only_as_saved_grant(tmp_path, monkeypatch):
    from core.external_agent.backend_client import _MANAGEMENT_SCOPES
    assert "agents:create:files" not in _MANAGEMENT_SCOPES
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    binding = {"projectId": "p", "instanceId": "i"}
    scopes = sorted(["agents:create", "agents:create:files"])
    client._state["management"] = {"clientId": "existing_client_1234567890", "binding": binding, "scopes": scopes,
        "subjectId": "ops-1234567890abcdef", "capability": "a" * 48}
    async def request(method, path, **kwargs):
        if path.endswith("/binding"):
            return {"protocolVersion": 1, "binding": binding}
        assert kwargs["json_payload"]["scopes"] == scopes
        return {"protocolVersion": 1, "binding": binding, "scopes": scopes,
            "subject_id": "ops-1234567890abcdef", "subject_capability": "a" * 48}
    monkeypatch.setattr(client, "_request_json", request)
    grant = await client._management_grant(require_existing=True)
    assert grant["scopes"] == scopes


@pytest.mark.anyio
async def test_archive_sdk_strict_local_parameters_and_target_receipt(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    calls = []
    payload = {"status": "completed", "action": "agent_archive", "requestId": "archive-1", "verified": True,
        "reused": False, "agent": {"agentId": "agent-a", "directSessionId": "session-a", "displayName": "A",
            "configRevision": 3, "updatedAt": "v3", "modelId": "provider/model", "avatarImagePath": ""}}
    async def grant(**kwargs):
        return {"subjectId": "subject", "capability": "capability", "binding": {"projectId": "p", "instanceId": "i"}}
    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return deepcopy(payload)
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    parameters = {"agent_id": "agent-a", "expected_config_revision": 3}
    assert await client.management_action(action="agent_archive", request_id="archive-1", parameters=parameters) == payload
    for extra in ({"expected_config_revision": True}, {"expected_config_revision": "3"}, {"force": True}, {"purge": True}):
        with pytest.raises(BackendClientError) as invalid:
            await client.management_action(action="agent_archive", request_id="archive-1", parameters={**parameters, **extra})
        assert invalid.value.code == "INVALID_MANAGEMENT_REQUEST" and len(calls) == 1
    payload["agent"]["agentId"] = "foreign"
    with pytest.raises(BackendClientError) as mismatch:
        await client.management_action(action="agent_archive", request_id="archive-1", parameters=parameters)
    assert mismatch.value.code == "BACKEND_PROTOCOL_ERROR"
    payload["agent"]["agentId"] = "agent-a"
    for extra in ({"verified": False}, {"session": {}}, {"private": "secret"}, {"agent": None}):
        original = deepcopy(payload)
        payload.update(extra)
        with pytest.raises(BackendClientError) as invalid:
            await client.management_receipt(action="agent_archive", request_id="archive-1")
        assert invalid.value.code == "BACKEND_PROTOCOL_ERROR"
        payload.clear()
        payload.update(original)


@pytest.mark.anyio
@pytest.mark.parametrize("saved_scopes", [None, ["agents:avatar", "agents:create", "agents:read", "agents:update",
    "platform:describe", "sessions:pin", "sessions:read", "teams:read", "teams:run"],
    ["agents:archive", "agents:avatar", "agents:create", "agents:read", "agents:update",
     "platform:describe", "sessions:pin", "sessions:read", "teams:read", "teams:run"]])
async def test_archive_scope_never_expands_saved_grants(tmp_path, monkeypatch, saved_scopes):
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    binding = {"projectId": "p", "instanceId": "i"}
    saved = {"clientId": "saved_client_1234567890", "binding": binding, "subjectId": "ops-1234567890abcdef", "capability": "a" * 48}
    if saved_scopes is not None:
        saved["scopes"] = saved_scopes
    client._state["management"] = saved
    async def request(method, path, **kwargs):
        if path.endswith("/binding"):
            return {"protocolVersion": 1, "binding": binding}
        body = kwargs["json_payload"]
        expected = saved_scopes or ["agents:avatar", "agents:create", "agents:read", "agents:update", "platform:describe", "sessions:read", "teams:read", "teams:run"]
        assert body["scopes"] == expected and body["client_id"] == saved["clientId"]
        return {"protocolVersion": 1, "binding": binding, "scopes": body["scopes"],
            "subject_id": saved["subjectId"], "subject_capability": saved["capability"]}
    monkeypatch.setattr(client, "_request_json", request)
    grant = await client._management_grant(require_existing=True)
    assert grant["scopes"] == (saved_scopes or ["agents:avatar", "agents:create", "agents:read", "agents:update",
        "platform:describe", "sessions:read", "teams:read", "teams:run"])
    assert grant["subjectId"] == saved["subjectId"]


@pytest.mark.anyio
async def test_fresh_grant_lost_bind_ack_reuses_persisted_client_and_exact_fourteen_scopes(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    path = tmp_path / "credentials.json"
    binding = {"projectId": "p", "instanceId": "i"}
    calls = []
    client = ManagedAgentBackendClient(tmp_path, state_path=path)
    async def request(method, route, **kwargs):
        if route.endswith("/binding"):
            return {"protocolVersion": 1, "binding": binding}
        body = kwargs["json_payload"]
        persisted = json.loads(path.read_text())["management"]
        assert persisted["clientId"] == body["client_id"] and persisted["scopes"] == body["scopes"]
        assert len(body["scopes"]) == 14 and {"agents:archive", "teams:directory:read", "rooms:read", "sessions:parameters:read", "legacy:receipts:read"} <= set(body["scopes"])
        calls.append(deepcopy(body))
        if len(calls) == 1:
            raise BackendClientError("lost bind ack", code="BACKEND_UNAVAILABLE")
        return {"protocolVersion": 1, "binding": binding, "scopes": body["scopes"],
            "subject_id": "ops-1234567890abcdef", "subject_capability": "a" * 48}
    monkeypatch.setattr(client, "_request_json", request)
    with pytest.raises(BackendClientError):
        await client._management_grant(require_existing=False)
    restarted = ManagedAgentBackendClient(tmp_path, state_path=path)
    monkeypatch.setattr(restarted, "_request_json", request)
    assert (await restarted._management_grant(require_existing=True))["subjectId"] == "ops-1234567890abcdef"
    assert calls[0] == calls[1]


@pytest.mark.anyio
async def test_session_list_sdk_closed_page_query_binding_and_no_query_injection(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    good = {"source": "native-session-directory", "untrustedContent": True,
        "sessions": [{"id": "session-1", "agentId": "agent-1", "titlePreview": "Visible", "titleTruncated": False}],
        "offset": 0, "limit": 1, "total": 1, "nextOffset": None}
    payload, calls = deepcopy(good), []
    async def grant(**kwargs): return {"subjectId": "subject", "capability": "capability"}
    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return deepcopy(payload)
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    assert await client.management_session_list(agent_id="agent-1", query="Visible &agent_id=hidden", limit=1) == good
    assert calls[0][0] == "GET" and calls[0][2]["management_auth"] == ("subject", "capability")
    query = parse_qs(urlsplit(calls[0][1]).query)
    assert query["agent_id"] == ["agent-1"] and query["query"] == ["Visible &agent_id=hidden"]
    for patch in ({"offset": 1}, {"limit": 2}, {"nextOffset": 1}, {"untrustedContent": False}, {"untrustedContent": 1},
                  {"sessions": [{**good["sessions"][0], "prompt": "SECRET"}]},
                  {"sessions": [{**good["sessions"][0], "agentId": "foreign"}]},
                  {"sessions": [good["sessions"][0]] * 2, "limit": 2, "total": 2},
                  {"sessions": [], "limit": 0}):
        payload.clear(); payload.update(deepcopy({**good, **patch}))
        with pytest.raises(BackendClientError) as invalid:
            await client.management_session_list(agent_id="agent-1", limit=1)
        assert invalid.value.code == "BACKEND_PROTOCOL_ERROR"
    count = len(calls)
    for query in ({"limit": 7}, {"offset": True}, {"query": "bad\nquery"}, {"agent_id": "../private"}, {"include_hidden": True}):
        with pytest.raises(BackendClientError) as invalid:
            await client.management_session_list(**query)
        assert invalid.value.code == "INVALID_MANAGEMENT_REQUEST"
    assert len(calls) == count


def _comparison_payload():
    return {"source": "session_agent_config_comparison", "untrustedContent": True, "sessionId": "session-1", "agentId": "agent-1",
        "pinned": {"agentConfigRevisionId": "agent-1:" + "a" * 64, "modelId": "provider/model", "contextWindow": 32768, "reasoningEffort": "low"},
        "current": {"agentConfigRevisionId": "agent-1:" + "b" * 64, "modelId": "provider/model", "contextWindow": 65536, "reasoningEffort": "high"},
        "sameRevision": False, "changedFields": ["contextWindow", "reasoningEffort"]}


@pytest.mark.parametrize("fault", ["same-flipped", "missing-difference", "extra-difference", "wrong-order", "duplicate",
    "unknown-field", "bool-coerced", "wrong-pinned-actor", "wrong-current-actor", "same-id-different-values",
    "missing-current", "private-field", "number-coerced", "effort-coerced"])
def test_comparison_dto_rejects_inconsistent_or_unbounded_projections(fault):
    from pydantic import ValidationError
    from core.web.services.external_management.contracts import SessionConfigComparisonResponse
    value = _comparison_payload()
    if fault == "same-flipped": value["sameRevision"] = True
    elif fault == "missing-difference": value["changedFields"] = []
    elif fault == "extra-difference": value["changedFields"] = ["modelId", "contextWindow", "reasoningEffort"]
    elif fault == "wrong-order": value["changedFields"].reverse()
    elif fault == "duplicate": value["changedFields"] = ["contextWindow", "contextWindow", "reasoningEffort"]
    elif fault == "unknown-field": value["changedFields"] = ["budget"]
    elif fault == "bool-coerced": value["sameRevision"] = 0
    elif fault == "wrong-pinned-actor": value["pinned"]["agentConfigRevisionId"] = "other:" + "a" * 64
    elif fault == "wrong-current-actor": value["current"]["agentConfigRevisionId"] = "other:" + "b" * 64
    elif fault == "same-id-different-values":
        value["current"]["agentConfigRevisionId"] = value["pinned"]["agentConfigRevisionId"]
        value["sameRevision"] = True
    elif fault == "missing-current": value.pop("current")
    elif fault == "private-field": value["current"]["metadata"] = {"secret": "must not leak"}
    elif fault == "number-coerced": value["current"]["contextWindow"] = "65536"
    elif fault == "effort-coerced": value["pinned"]["reasoningEffort"] = "LOW"
    with pytest.raises(ValidationError):
        SessionConfigComparisonResponse.model_validate(value)


@pytest.mark.anyio
async def test_comparison_client_uses_bound_get_and_checks_session_actor_and_derived_fields(tmp_path, monkeypatch):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    metadata = {"session": {"id": "session-1", "title": "public", "agentId": "agent-1", "pinnedAtMs": None,
        "pinned": False, "status": "ready", "archived": False}, "untrustedContent": True}
    payload, calls = _comparison_payload(), []
    async def grant(**kwargs):
        assert kwargs == {"require_existing": False}
        return {"subjectId": "subject", "capability": "capability"}
    async def request(method, path, **kwargs):
        assert method == "GET" and "?" not in path and kwargs == {"management_auth": ("subject", "capability")}
        calls.append(path)
        return deepcopy(payload if path.endswith("/config-comparison") else metadata)
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    assert await client.management_session_config_compare(session_id="session-1") == payload
    assert calls[-2:] == ["/api/v1/launcher-assistant-management/sessions/session-1",
                         "/api/v1/launcher-assistant-management/sessions/session-1/config-comparison"]
    for fault in ("session", "actor", "same", "differences", "private"):
        payload = _comparison_payload()
        if fault == "session": payload["sessionId"] = "other-session"
        elif fault == "actor":
            payload["agentId"] = "other"
            for side, char in (("pinned", "a"), ("current", "b")): payload[side]["agentConfigRevisionId"] = "other:" + char * 64
        elif fault == "same": payload["sameRevision"] = True
        elif fault == "differences": payload["changedFields"] = []
        else: payload["current"]["prompt"] = "SECRET"
        with pytest.raises(BackendClientError) as error:
            await client.management_session_config_compare(session_id="session-1")
        assert error.value.code == "BACKEND_PROTOCOL_ERROR"
    before = len(calls)
    for bad_id in ("../session", "session?query=true", "session/config", True):
        with pytest.raises(BackendClientError) as error:
            await client.management_session_config_compare(session_id=bad_id)
        assert error.value.code == "INVALID_MANAGEMENT_REQUEST"
    assert len(calls) == before and not (tmp_path / "credentials.json").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["same", "differences", "actor", "same-id-different-values"])
async def test_comparison_sdk_recomputes_relations_independently_of_dto_decoder(tmp_path, monkeypatch, fault):
    from types import SimpleNamespace
    from core.web.services.external_management.contracts import SessionConfigComparisonResponse
    value = _comparison_payload()
    if fault == "same": value["sameRevision"] = True
    elif fault == "differences": value["changedFields"] = []
    elif fault == "actor": value["current"]["agentConfigRevisionId"] = "other:" + "b" * 64
    else:
        value["sameRevision"] = True
        value["current"]["agentConfigRevisionId"] = value["pinned"]["agentConfigRevisionId"]
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    async def metadata(**kwargs): return {"session": {"agentId": "agent-1"}}
    async def grant(**kwargs): return {"subjectId": "subject", "capability": "capability"}
    async def request(*_a, **_k): return value
    monkeypatch.setattr(client, "management_session", metadata)
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    # Decoder is deliberately bypassed: this must still fail in SDK logic.
    monkeypatch.setattr(SessionConfigComparisonResponse, "model_validate", lambda _v: SimpleNamespace(model_dump=lambda: value))
    with pytest.raises(BackendClientError) as error:
        await client.management_session_config_compare(session_id="session-1")
    assert error.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
async def test_session_config_client_strict_projection_and_independent_owner_binding(tmp_path, monkeypatch):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    session = {"session": {"id": "session-1", "title": "public", "agentId": "agent-1", "pinnedAtMs": None,
                          "pinned": False, "status": "ready", "archived": False}, "untrustedContent": True}
    good = {"source": "session_agent_config_revision", "untrustedContent": True, "config": {
        "sessionId": "session-1", "agentId": "agent-1", "agentConfigRevisionId": "agent-1:" + "a" * 64,
        "modelId": "opaque/model with space", "contextWindow": 32000, "reasoningEffort": ""}}
    payload, calls = deepcopy(good), []
    async def grant(**kwargs):
        assert kwargs == {"require_existing": False}
        return {"subjectId": "subject", "capability": "capability"}
    async def request(method, path, **kwargs):
        assert method == "GET" and "?" not in path
        assert kwargs == {"management_auth": ("subject", "capability")}
        calls.append(path)
        return deepcopy(payload if path.endswith("/config") else session)
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    assert await client.management_session_config(session_id="session-1") == good
    assert calls[-2:] == ["/api/v1/launcher-assistant-management/sessions/session-1",
                          "/api/v1/launcher-assistant-management/sessions/session-1/config"]
    for patch in ({"sessionId": "other"}, {"agentId": "other", "agentConfigRevisionId": "other:" + "a" * 64},
                  {"agentConfigRevisionId": "other:" + "a" * 64}, {"contextWindow": True}, {"contextWindow": "32000"},
                  {"contextWindow": 2**53}, {"modelId": " model"}, {"reasoningEffort": "HIGH"},
                  {"prompt": "SECRET"}, {"budget": 99}):
        payload = {**good, "config": {**good["config"], **patch}}
        with pytest.raises(BackendClientError) as error:
            await client.management_session_config(session_id="session-1")
        assert error.value.code == "BACKEND_PROTOCOL_ERROR"
    for patch in ({"source": "current_agent"}, {"untrustedContent": False}, {"metadata": "SECRET"}):
        payload = {**good, **patch}
        with pytest.raises(BackendClientError) as error:
            await client.management_session_config(session_id="session-1")
        assert error.value.code == "BACKEND_PROTOCOL_ERROR"
    before = len(calls)
    for invalid in ("session-1?private=true", "../session-1", "session-1/config", 1):
        with pytest.raises(BackendClientError) as error:
            await client.management_session_config(session_id=invalid)
        assert error.value.code == "INVALID_MANAGEMENT_REQUEST"
    assert len(calls) == before and not (tmp_path / "credentials.json").exists()


@pytest.mark.anyio
async def test_avatar_options_client_validates_closed_query_and_response(tmp_path, monkeypatch):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / 'credentials.json')
    payload = {'options': [{'filename': 'choice.png', 'path': 'workspace/avatars/choice.png'}],
        'offset': 2, 'total': 4, 'nextOffset': 3, 'untrustedContent': True}
    calls = []
    async def grant(**kwargs):
        assert kwargs == {'require_existing': False}
        return {'subjectId': 'private-subject', 'capability': 'private-capability'}
    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return payload
    monkeypatch.setattr(client, '_management_grant', grant)
    monkeypatch.setattr(client, '_request_json', request)
    assert await client.management_avatar_options(offset=2, limit=1) == payload
    assert calls[0][:2] == ('GET', '/api/v1/launcher-assistant-management/avatar-options?offset=2&limit=1')
    for patch in ({'offset': True}, {'offset': 50001}, {'limit': 31}):
        with pytest.raises(BackendClientError) as error:
            await client.management_avatar_options(**patch)
        assert error.value.code == 'INVALID_MANAGEMENT_REQUEST'
    assert len(calls) == 1
    original = dict(payload)
    for patch in ({'offset': 3}, {'total': True}, {'total': 50001}, {'nextOffset': 2}, {'nextOffset': None},
        {'options': [], 'nextOffset': None}, {'total': 3, 'nextOffset': 3}, {'untrustedContent': 1},
        {'directory': '/private'}, {'options': [{'filename': 'choice.png', 'path': 'workspace/avatars/choice.png', 'url': '/private'}]}):
        payload.clear(); payload.update({**original, **patch})
        with pytest.raises(BackendClientError) as error:
            await client.management_avatar_options(offset=2, limit=1)
        assert error.value.code == 'BACKEND_PROTOCOL_ERROR'
    payload.clear(); payload.update(original); payload.pop('nextOffset')
    with pytest.raises(BackendClientError) as missing:
        await client.management_avatar_options(offset=2, limit=1)
    assert missing.value.code == 'BACKEND_PROTOCOL_ERROR'
    assert not (tmp_path / 'credentials.json').exists()


@pytest.mark.anyio
async def test_lost_start_response_can_be_recovered_without_resubmitting_prompt(tmp_path):
    _runtime_state(tmp_path)
    calls = []
    ordinary = _transport(tmp_path, calls)
    starts = []
    def handler(request):
        if request.method == "POST" and request.url.path.endswith("/tasks"):
            starts.append(request)
            raise httpx.ReadTimeout("ack lost", request=request)
        if request.url.path.endswith("/task-request"):
            calls.append(request)
            assert request.url.params["client_request_id"] == "stable-request"
            return httpx.Response(200, json={"taskId": "eat-1", "status": "running", "_leaseId": "lease-1"})
        return ordinary.handle_request(request)
    transport = httpx.MockTransport(handler)
    state = tmp_path / "launcher-credentials.json"
    before = ManagedAgentBackendClient(tmp_path, state_path=state, transport=transport)
    with pytest.raises(BackendClientError):
        await before.start_task(agent_id="coder", task="private task", permission_profile="read_only",
                                client_request_id="stable-request", title="")
    resumed = ManagedAgentBackendClient(tmp_path, state_path=state, transport=transport)
    receipt = await resumed.get_task_for_request(client_request_id="stable-request")
    assert receipt["taskId"] == "eat-1" and "_leaseId" not in receipt
    assert len(starts) == 1
    assert json.loads(state.read_text())["tasks"]["eat-1"]["leaseId"] == "lease-1"
    assert starts[0].headers["X-Vibelution-External-Agent-Task-Capability"] == calls[-1].headers["X-Vibelution-External-Agent-Task-Capability"]
    with pytest.raises(BackendClientError) as absent:
        await resumed.get_task_for_request(client_request_id="credential-never-created")
    assert absent.value.code == "UNKNOWN_REQUEST"


def _runtime_state(
    root: Path,
    *,
    url: str = "http://127.0.0.1:8123",
    source_commit: str | None = "rev-1",
    include_project_root: bool = True,
) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("rev-1\n", encoding="utf-8")
    path = root / ".runtime" / "launcher" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"url": url}
    if include_project_root:
        payload["runtimeProjectRoot"] = str(root.resolve())
    if source_commit is not None:
        payload["runtimeSourceCommit"] = source_commit
    path.write_text(json.dumps(payload), encoding="utf-8")


def _running_code_fingerprint(root: Path, *, project_root: Path | None = None) -> None:
    path = root / ".runtime" / "running-code-fingerprint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "projectRoot": str((project_root or root).resolve()),
                "runningHead": "rev-1",
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_management_lost_response_retains_operator_subject_and_recovers_without_recreation(tmp_path):
    _runtime_state(tmp_path)
    calls, writes, binds = [], [], []
    ordinary = _transport(tmp_path, calls)
    binding = {"projectId": "project-1", "instanceId": "instance-1"}
    capability = "private-capability-" + "a" * 40
    prefix = "/api/v1/launcher-assistant-management"
    def handler(request):
        if request.url.path == prefix + "/binding":
            return httpx.Response(200, json={"protocolVersion": 1, "binding": binding})
        if request.url.path == prefix + "/subjects/bind":
            body = json.loads(request.content)
            binds.append(body)
            assert request.headers["X-Vibelution-Control-Token"] == "control-1"
            assert "X-Vibelution-External-Agent-Task-Capability" not in request.headers
            return httpx.Response(200, json={"protocolVersion": 1, "subject_id": "ops-1234567890abcdef",
                "subject_capability": capability, "binding": binding, "scopes": body["scopes"]})
        if request.url.path.startswith(prefix + "/actions/"):
            assert request.headers["X-Vibelution-Management-Capability"] == capability
            assert request.headers["X-Vibelution-Management-Subject"] == "ops-1234567890abcdef"
            if request.method == "POST":
                writes.append(request)
                raise httpx.ReadTimeout("lost response", request=request)
            return httpx.Response(200, json={"status": "completed", "action": "agent_create", "requestId": "create-1",
                "verified": True, "reused": True, "agent": {"agentId": "native-agent", "metadata": {"private": "omit"}},
                "subject_capability": capability})
        return ordinary.handle_request(request)
    state = tmp_path / "management-state.json"
    transport = httpx.MockTransport(handler)
    before = ManagedAgentBackendClient(tmp_path, state_path=state, transport=transport)
    with pytest.raises(BackendClientError):
        await before.management_action(action="agent_create", request_id="create-1", parameters={"display_name": "Worker"})
    after = ManagedAgentBackendClient(tmp_path, state_path=state, transport=transport)
    receipt = await after.management_receipt(action="agent_create", request_id="create-1")
    assert receipt["agent"] == {"agentId": "native-agent"}
    assert capability not in json.dumps(receipt)
    assert len(writes) == 1 and binds[0]["client_id"] == binds[1]["client_id"]


@pytest.mark.anyio
async def test_missing_management_credentials_cannot_mint_new_owner_for_a_retry(tmp_path):
    _runtime_state(tmp_path)
    calls = []
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "absent.json", transport=_transport(tmp_path, calls))
    with pytest.raises(BackendClientError) as missing:
        await client.management_action(action="agent_create", request_id="old-operation", parameters={}, require_existing_subject=True)
    assert missing.value.code == "UNKNOWN_MANAGEMENT_SUBJECT" and calls == []
    client.state_path.write_text("not json", encoding="utf-8")
    corrupt = ManagedAgentBackendClient(tmp_path, state_path=client.state_path, transport=_transport(tmp_path, calls))
    with pytest.raises(BackendClientError) as invalid:
        await corrupt.management_action(action="agent_create", request_id="new-operation", parameters={})
    assert invalid.value.code == "UNKNOWN_MANAGEMENT_SUBJECT" and calls == []


@pytest.mark.anyio
async def test_management_binding_rotation_fails_closed_until_explicit_reset(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    path = tmp_path / "credentials.json"
    old_binding = {"projectId": "project-old", "instanceId": "instance-1"}
    new_binding = {"projectId": "project-new", "instanceId": "instance-1"}
    saved_scopes = ["agents:read", "agents:update"]
    client = ManagedAgentBackendClient(tmp_path, state_path=path)
    client._state["management"] = {"clientId": "saved_client_1234567890", "binding": old_binding,
        "subjectId": "ops-1234567890abcdef", "capability": "a" * 48, "scopes": saved_scopes}
    binds = []
    async def request(method, route, **kwargs):
        if route.endswith("/binding"):
            return {"protocolVersion": 1, "binding": new_binding}
        binds.append(kwargs["json_payload"])
        return {"protocolVersion": 1, "binding": new_binding, "scopes": kwargs["json_payload"]["scopes"],
            "subject_id": "ops-fedcba0987654321", "subject_capability": "b" * 48}
    monkeypatch.setattr(client, "_request_json", request)

    with pytest.raises(BackendClientError) as rotated:
        await client._management_grant(require_existing=True)
    assert rotated.value.code == "MANAGEMENT_IDENTITY_ROTATED"
    assert "management_reset_credentials" in str(rotated.value)
    assert binds == []  # Refused before asking the server to bind anything.

    await client.management_reset_credentials()
    assert json.loads(path.read_text(encoding="utf-8"))["management"] == {}

    grant = await client._management_grant(require_existing=False)
    assert grant["subjectId"] == "ops-fedcba0987654321" and grant["binding"] == new_binding
    assert binds[0]["expected_binding"] == new_binding
    assert binds[0]["client_id"] != "saved_client_1234567890"
    # A fresh client explicitly requests the full modern scope set (not the
    # frozen legacy eight), and the server echo must match it exactly.
    assert "sessions:pin" in binds[0]["scopes"] and "agents:archive" in binds[0]["scopes"]
    assert binds[0]["scopes"] == sorted(set(binds[0]["scopes"]))
    persisted = json.loads(path.read_text(encoding="utf-8"))["management"]
    assert persisted["subjectId"] == "ops-fedcba0987654321" and persisted["binding"] == new_binding
    assert persisted["clientId"] == binds[0]["client_id"]


@pytest.mark.anyio
async def test_management_reminted_subject_requires_explicit_reset_then_recovers(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    path = tmp_path / "credentials.json"
    binding = {"projectId": "project-1", "instanceId": "instance-1"}
    client = ManagedAgentBackendClient(tmp_path, state_path=path)
    client._state["management"] = {"clientId": "saved_client_1234567890", "binding": binding,
        "subjectId": "ops-1234567890abcdef", "capability": "a" * 48,
        "scopes": ["agents:read", "agents:update"]}
    binds = []
    async def request(method, route, **kwargs):
        if route.endswith("/binding"):
            return {"protocolVersion": 1, "binding": binding}
        binds.append(kwargs["json_payload"])
        # Runtime store was rebuilt: the server re-mints a different subject
        # for the (re-created) client record.
        return {"protocolVersion": 1, "binding": binding, "scopes": kwargs["json_payload"]["scopes"],
            "subject_id": "ops-fedcba0987654321", "subject_capability": "b" * 48}
    monkeypatch.setattr(client, "_request_json", request)

    with pytest.raises(BackendClientError) as rotated:
        await client._management_grant(require_existing=True)
    assert rotated.value.code == "MANAGEMENT_IDENTITY_ROTATED"
    assert "management_reset_credentials" in str(rotated.value)
    persisted = json.loads(path.read_text(encoding="utf-8"))["management"]
    assert persisted["subjectId"] == "ops-1234567890abcdef"  # Old credentials stay untouched.

    await client.management_reset_credentials()
    grant = await client._management_grant(require_existing=False)
    assert grant["subjectId"] == "ops-fedcba0987654321" and grant["binding"] == binding
    assert grant["scopes"] == binds[-1]["scopes"] and grant["capability"] == "b" * 48
    assert json.loads(path.read_text(encoding="utf-8"))["management"]["subjectId"] == "ops-fedcba0987654321"


@pytest.mark.anyio
async def test_management_rejects_bind_response_contradicting_current_binding(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    path = tmp_path / "credentials.json"
    binding = {"projectId": "project-1", "instanceId": "instance-1"}
    foreign_binding = {"projectId": "project-other", "instanceId": "instance-1"}
    client = ManagedAgentBackendClient(tmp_path, state_path=path)
    saved = {"clientId": "saved_client_1234567890", "binding": binding,
        "subjectId": "ops-1234567890abcdef", "capability": "a" * 48,
        "scopes": ["agents:read", "agents:update"]}
    client._state["management"] = dict(saved)
    async def request(method, route, **kwargs):
        if route.endswith("/binding"):
            return {"protocolVersion": 1, "binding": binding}
        # Malicious/buggy server answers a bind bound to a different binding.
        return {"protocolVersion": 1, "binding": foreign_binding, "scopes": kwargs["json_payload"]["scopes"],
            "subject_id": "ops-fedcba0987654321", "subject_capability": "b" * 48}
    monkeypatch.setattr(client, "_request_json", request)

    with pytest.raises(BackendClientError) as rejected:
        await client._management_grant(require_existing=False)
    assert rejected.value.code == "BACKEND_PROTOCOL_ERROR"
    assert "contradicts" in str(rejected.value)
    persisted = json.loads(path.read_text(encoding="utf-8"))["management"]
    assert persisted["subjectId"] == saved["subjectId"] and persisted["capability"] == saved["capability"]


def test_team_receipt_preserves_native_progress_and_redacts_nested_private_data():
    receipt = ManagedAgentBackendClient._management_public_receipt({
        "action": "team_run", "requestId": "team-1", "status": "completed", "verified": True, "reused": True,
        "phase": "started", "resumeAllowed": False, "subject_capability": "private-secret",
        "teamRun": {"teamId": "team-native", "flowId": "flow-native", "runId": "run-native", "status": "running",
                    "current": 1, "attempts": [{"nodeId": "plan", "number": 1, "agentId": "planner",
                    "sessionId": "session-1", "turnId": "turn-1", "status": "running", "prompt": "private-secret"}],
                    "artifactRefs": [], "values": {"goal": "private-secret"}}}, action="team_run", request_id="team-1")
    assert receipt["status"] == "completed" and receipt["teamRun"]["status"] == "running"
    assert receipt["phase"] == "started" and receipt["resumeAllowed"] is False
    assert "private-secret" not in json.dumps(receipt)
    malformed = {**receipt, "teamRun": {**receipt["teamRun"], "attempts": receipt["teamRun"]["attempts"] * 21}}
    with pytest.raises(BackendClientError) as invalid:
        ManagedAgentBackendClient._management_public_receipt(malformed, action="team_run", request_id="team-1")
    assert invalid.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
async def test_team_client_uses_operator_envelope_and_same_read_only_receipt(tmp_path):
    _runtime_state(tmp_path)
    calls, mutations = [], []
    ordinary = _transport(tmp_path, calls)
    binding = {"projectId": "project-1", "instanceId": "instance-1"}
    prefix = "/api/v1/launcher-assistant-management"
    receipt = {"action": "team_run", "requestId": "team-1", "status": "completed", "verified": True,
               "reused": False, "phase": "started", "resumeAllowed": False,
               "teamRun": {"teamId": "team-native", "flowId": "flow-native", "runId": "run-native", "status": "running"}}
    def handler(request):
        if request.url.path == prefix + "/binding":
            return httpx.Response(200, json={"protocolVersion": 1, "binding": binding})
        if request.url.path == prefix + "/subjects/bind":
            body = json.loads(request.content)
            assert body["scopes"] == ["agents:archive", "agents:avatar", "agents:create", "agents:read", "agents:update", "legacy:receipts:read", "platform:describe", "rooms:read", "sessions:parameters:read", "sessions:pin", "sessions:read", "teams:directory:read", "teams:read", "teams:run"]
            return httpx.Response(200, json={"protocolVersion": 1, "binding": binding, "scopes": body["scopes"],
                "subject_id": "ops-1234567890abcdef", "subject_capability": "a" * 48})
        if request.url.path.startswith(prefix + "/actions/team_run"):
            assert request.headers["X-Vibelution-Management-Subject"] == "ops-1234567890abcdef"
            if request.method == "POST":
                mutations.append(json.loads(request.content))
            return httpx.Response(200, json=receipt)
        return ordinary.handle_request(request)
    state = tmp_path / "credentials.json"
    before = ManagedAgentBackendClient(tmp_path, state_path=state, transport=httpx.MockTransport(handler))
    params = {"name": "Team", "goal": "Goal", "template_id": "dev-team"}
    started = await before.management_action(action="team_run", request_id="team-1", parameters=params)
    after = ManagedAgentBackendClient(tmp_path, state_path=state, transport=httpx.MockTransport(handler))
    restored = await after.management_receipt(action="team_run", request_id="team-1")
    assert restored == started and len(mutations) == 1
    assert mutations[0] == {"request_id": "team-1", "expected_binding": binding, "parameters": params}


@pytest.mark.anyio
async def test_session_metadata_uses_bound_read_and_rejects_private_or_changed_response(tmp_path):
    _runtime_state(tmp_path)
    calls, reads = [], []
    ordinary = _transport(tmp_path, calls)
    binding = {"projectId": "project-1", "instanceId": "instance-1"}
    prefix = "/api/v1/launcher-assistant-management"
    session = {"id": "session-1", "title": "Untrusted title", "agentId": "agent-1",
               "pinnedAtMs": None, "pinned": False, "status": "ready", "archived": False}
    payload = {"session": session, "untrustedContent": True}

    def handler(request):
        if request.url.path == prefix + "/binding":
            return httpx.Response(200, json={"protocolVersion": 1, "binding": binding})
        if request.url.path == prefix + "/subjects/bind":
            body = json.loads(request.content)
            assert "sessions:read" in body["scopes"]
            return httpx.Response(200, json={"protocolVersion": 1, "binding": binding, "scopes": body["scopes"],
                "subject_id": "ops-1234567890abcdef", "subject_capability": "a" * 48})
        if request.url.path == prefix + "/sessions/session-1":
            assert request.method == "GET" and not request.url.query
            assert request.headers["X-Vibelution-Control-Token"] == "control-1"
            assert request.headers["X-Vibelution-Management-Subject"] == "ops-1234567890abcdef"
            reads.append(request)
            return httpx.Response(200, json=payload)
        return ordinary.handle_request(request)

    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json",
                                      transport=httpx.MockTransport(handler))
    assert await client.management_session(session_id="session-1") == payload
    payload["session"] = {**session, "id": "another-session"}
    with pytest.raises(BackendClientError) as mismatch:
        await client.management_session(session_id="session-1")
    assert mismatch.value.code == "BACKEND_PROTOCOL_ERROR"
    payload["session"] = {**session, "prompt": "private"}
    with pytest.raises(BackendClientError) as private:
        await client.management_session(session_id="session-1")
    assert private.value.code == "BACKEND_PROTOCOL_ERROR"
    with pytest.raises(BackendClientError) as invalid:
        await client.management_session(session_id="../session-1")
    assert invalid.value.code == "INVALID_MANAGEMENT_REQUEST" and len(reads) == 3


def _transport(
    root: Path,
    calls: list[httpx.Request],
    *,
    get_status: str = "running",
    server_version: str = "0.3.1",
    api_protocol_version: str = "1.0",
    source_identity: dict | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/control-token":
            return httpx.Response(
                200,
                json={
                    "header": "X-Vibelution-Control-Token",
                    "controlToken": "control-1",
                },
            )
        if request.url.path == "/api/v1/external-agent/info":
            return httpx.Response(
                200,
                content=json.dumps({
                    "apiProtocolVersion": api_protocol_version,
                    "serverVersion": server_version,
                    "projectRoot": str(root.resolve()),
                    "runtimeSourceRevision": "rev-1",
                    **({"runtimeSourceIdentity": source_identity} if source_identity is not None else {}),
                }),
                headers={"Content-Type": "application/json"},
            )
        if request.url.path == "/api/v1/external-agent/agents":
            return httpx.Response(200, json={"status": "ok", "agents": []})
        if request.url.path == "/api/v1/external-agent/connections/shutdown":
            return httpx.Response(200, json={"status": "ok"})
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/external-agent/tasks"
        ):
            return httpx.Response(
                201,
                json={"taskId": "eat-1", "status": "running", "_leaseId": "lease-1"},
            )
        if (
            request.method == "GET"
            and request.url.path == "/api/v1/external-agent/tasks/eat-1"
        ):
            return httpx.Response(
                200,
                json={"taskId": "eat-1", "status": get_status},
            )
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(
                200,
                json={"taskId": "eat-1", "status": "running", "_leaseId": "lease-1"},
            )
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"taskId": "eat-1", "status": "cancelled"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_client_verifies_runtime_and_strips_private_fields(tmp_path) -> None:
    _runtime_state(tmp_path)
    calls: list[httpx.Request] = []
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-1",
    )

    result = await client.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )
    fetched = await client.get_task(task_id="eat-1")

    assert result == {"taskId": "eat-1", "status": "running"}
    assert fetched == {"taskId": "eat-1", "status": "running"}
    start = next(
        request
        for request in calls
        if request.method == "POST" and request.url.path.endswith("/tasks")
    )
    get = next(
        request
        for request in calls
        if request.method == "GET" and request.url.path.endswith("/tasks/eat-1")
    )
    capability = start.headers["X-Vibelution-External-Agent-Task-Capability"]
    assert capability
    assert get.headers["X-Vibelution-External-Agent-Task-Capability"] == capability
    assert start.headers["X-Vibelution-Control-Token"] == "control-1"
    assert "_leaseId" not in result


@pytest.mark.anyio
async def test_client_recovers_task_capability_and_lease_after_restart(
    tmp_path,
) -> None:
    _runtime_state(tmp_path)
    state_path = tmp_path / "adapter-state.json"
    calls: list[httpx.Request] = []
    first = ManagedAgentBackendClient(
        tmp_path,
        state_path=state_path,
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-1",
    )
    await first.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )
    second = ManagedAgentBackendClient(
        tmp_path,
        state_path=state_path,
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-2",
    )

    await second.heartbeat_once()
    await second.get_task(task_id="eat-1")

    heartbeat = next(
        request for request in calls if request.url.path.endswith("/heartbeat")
    )
    body = json.loads(heartbeat.content)
    assert body == {"lease_id": "lease-1"}
    assert heartbeat.headers["X-Vibelution-External-Agent-Connection"] == "connection-2"


@pytest.mark.anyio
async def test_client_shutdown_cancels_nonterminal_tasks(tmp_path) -> None:
    _runtime_state(tmp_path)
    calls: list[httpx.Request] = []
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-1",
    )
    await client.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )

    await client.shutdown()

    assert any(request.url.path.endswith("/tasks/eat-1/cancel") for request in calls)
    assert any(request.url.path.endswith("/connections/shutdown") for request in calls)
    persisted = json.loads(
        (tmp_path / "adapter-state.json").read_text(encoding="utf-8")
    )
    assert persisted["tasks"] == {}


@pytest.mark.anyio
async def test_client_keeps_terminal_task_queryable_until_shutdown(tmp_path) -> None:
    _runtime_state(tmp_path)
    calls: list[httpx.Request] = []
    state_path = tmp_path / "adapter-state.json"
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=state_path,
        transport=_transport(tmp_path, calls, get_status="succeeded"),
        adapter_connection_id="connection-1",
    )
    await client.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )

    first = await client.get_task(task_id="eat-1")
    second = await client.get_task(task_id="eat-1")

    assert first["status"] == second["status"] == "succeeded"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["tasks"]["eat-1"]["status"] == "succeeded"

    await client.shutdown()

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["tasks"] == {}
    assert not any(request.url.path.endswith("/tasks/eat-1/cancel") for request in calls)


@pytest.mark.anyio
async def test_client_rejects_non_loopback_or_mismatched_runtime(tmp_path) -> None:
    _runtime_state(tmp_path, url="http://192.168.1.10:8123")
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    with pytest.raises(BackendClientError, match="loopback") as non_loopback:
        await client.list_agents()
    assert non_loopback.value.code == "RUNTIME_IDENTITY_MISMATCH"

    _runtime_state(tmp_path)

    def mismatch(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/control-token":
            return httpx.Response(
                200,
                json={
                    "header": "X-Vibelution-Control-Token",
                    "controlToken": "control-1",
                },
            )
        return httpx.Response(
            200,
            json={
                "apiProtocolVersion": "1.0",
                "serverVersion": "0.3.1",
                "projectRoot": str((tmp_path / "other").resolve()),
                "runtimeSourceRevision": "rev-1",
            },
        )

    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(mismatch),
    )
    with pytest.raises(BackendClientError, match="project root") as mismatch_error:
        await client.list_agents()
    assert mismatch_error.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_rejects_runtime_from_another_source_revision(tmp_path) -> None:
    _runtime_state(tmp_path)
    (tmp_path / ".git" / "HEAD").write_text("rev-2\n", encoding="utf-8")
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, []),
    )

    with pytest.raises(BackendClientError, match="source revision") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"

    assert mismatch.value.reason == "runtime_revision_mismatch"


@pytest.mark.anyio
async def test_missing_runtime_descriptor_has_a_local_diagnostic_reason(tmp_path):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "adapter-state.json")
    with pytest.raises(BackendClientError) as missing:
        await client.diagnostics()
    assert missing.value.code == "BACKEND_UNAVAILABLE"
    assert missing.value.reason == "runtime_descriptor_missing"


@pytest.mark.anyio
@pytest.mark.parametrize("dirty,head,expected,admitted", [
    (False, "rev-1", "rev-1", True),
    (True, "rev-1", "rev-1", False),
    (None, "rev-1", "rev-1", False),
    (False, "other", "rev-1", False),
    (False, "rev-1", "other", False),
])
async def test_equivalent_sources_require_the_original_clean_runtime_identity(tmp_path, monkeypatch, dirty, head, expected, admitted):
    from core.external_agent import runtime_source_identity
    _runtime_state(tmp_path, source_commit=expected)
    (tmp_path / ".git" / "HEAD").write_text("checkout-new\n", encoding="utf-8")
    fingerprint = {"schemaVersion": 1, "projectRoot": str(tmp_path.resolve()), "runningHead": head, "dirty": dirty}
    (tmp_path / ".runtime" / "running-code-fingerprint.json").write_text(json.dumps(fingerprint), encoding="utf-8")
    probes = []
    def equivalent(*args):
        probes.append(args)
        return True
    monkeypatch.setattr(runtime_source_identity, "runtime_sources_match", equivalent)
    calls = []
    proof = {"schemaVersion": 1, "revision": head, "clean": dirty is False, "pid": 1234, "createTime": 123.5}
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "adapter-state.json", transport=_transport(tmp_path, calls, source_identity=proof))
    if admitted:
        assert await client.list_agents() == {"status": "ok", "agents": []}
        assert len(probes) == 1
    else:
        with pytest.raises(BackendClientError) as mismatch:
            await client.list_agents()
        assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"
        assert not probes
        assert not any(request.url.path.endswith("/agents") for request in calls)


@pytest.mark.anyio
@pytest.mark.parametrize("patch", [None, {"createTime": True}, {"createTime": float("nan")}, {"createTime": float("inf")}, {"pid": True}, {"clean": False}])
async def test_shared_files_or_invalid_process_proof_cannot_admit_other_revisions(tmp_path, monkeypatch, patch):
    from core.external_agent import runtime_source_identity
    _runtime_state(tmp_path)
    (tmp_path / ".git" / "HEAD").write_text("other-checkout\n", encoding="utf-8")
    _running_code_fingerprint(tmp_path)
    path = tmp_path / ".runtime" / "running-code-fingerprint.json"
    fingerprint = json.loads(path.read_text())
    fingerprint["dirty"] = False
    path.write_text(json.dumps(fingerprint))
    def forbidden(*_args):
        raise AssertionError("invalid or absent live-process proof must not compare source trees")
    monkeypatch.setattr(runtime_source_identity, "runtime_sources_match", forbidden)
    proof = None if patch is None else {"schemaVersion": 1, "revision": "rev-1", "clean": True, "pid": 1234, "createTime": 123.5, **patch}
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "adapter-state.json", transport=_transport(tmp_path, [], source_identity=proof))
    with pytest.raises(BackendClientError) as mismatch:
        await client.list_agents()
    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_rejects_runtime_from_another_server_version(tmp_path) -> None:
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, [], server_version="0.2.0"),
    )

    with pytest.raises(BackendClientError, match="server version") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"
    message = str(mismatch.value)
    assert "expected 0.3.1" in message and "got 0.2.0" in message
    assert "outdated" in message and "desktop app" in message


@pytest.mark.anyio
async def test_client_rejects_runtime_from_another_api_protocol_version(tmp_path) -> None:
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, [], api_protocol_version="2.0"),
    )

    with pytest.raises(BackendClientError, match="protocol version") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"
    message = str(mismatch.value)
    assert "expected 1.0" in message and "got 2.0" in message
    assert "outdated" in message and "desktop app" in message


@pytest.mark.anyio
async def test_client_accepts_runtime_identity_from_running_code_fingerprint(tmp_path) -> None:
    _runtime_state(tmp_path, source_commit=None)
    _running_code_fingerprint(tmp_path)
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, []),
    )

    assert await client.list_agents() == {"status": "ok", "agents": []}


@pytest.mark.anyio
async def test_client_rejects_runtime_without_running_code_fingerprint(tmp_path) -> None:
    _runtime_state(tmp_path, source_commit=None)
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, []),
    )

    with pytest.raises(BackendClientError, match="source revision") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_rejects_running_code_fingerprint_from_another_project(tmp_path) -> None:
    _runtime_state(tmp_path, source_commit=None)
    _running_code_fingerprint(tmp_path, project_root=tmp_path / "elsewhere")
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, []),
    )

    with pytest.raises(BackendClientError, match="source revision") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_accepts_minimal_state_root_from_running_code_fingerprint(tmp_path) -> None:
    _runtime_state(tmp_path, source_commit=None, include_project_root=False)
    _running_code_fingerprint(tmp_path)
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, []),
    )

    assert await client.list_agents() == {"status": "ok", "agents": []}


@pytest.mark.anyio
async def test_client_rejects_minimal_state_with_foreign_fingerprint_root(tmp_path) -> None:
    _runtime_state(tmp_path, source_commit=None, include_project_root=False)
    _running_code_fingerprint(tmp_path, project_root=tmp_path / "elsewhere")
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, []),
    )

    with pytest.raises(BackendClientError, match="project root") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_preserves_backend_stable_error_code(tmp_path) -> None:
    _runtime_state(tmp_path)

    def denied(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/control-token":
            return httpx.Response(
                200,
                json={
                    "header": "X-Vibelution-Control-Token",
                    "controlToken": "control-1",
                },
            )
        if request.url.path == "/api/v1/external-agent/info":
            return httpx.Response(
                200,
                json={
                    "apiProtocolVersion": "1.0",
                    "serverVersion": "0.3.1",
                    "projectRoot": str(tmp_path.resolve()),
                    "runtimeSourceRevision": "rev-1",
                },
            )
        return httpx.Response(
            404,
            json={
                "detail": {
                    "code": "AGENT_NOT_FOUND",
                    "message": "Agent is not available.",
                }
            },
        )

    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(denied),
    )

    with pytest.raises(
        BackendClientError, match="Agent is not available"
    ) as denied_error:
        await client.list_agents()

    assert denied_error.value.code == "AGENT_NOT_FOUND"


def _handshake_response(request: httpx.Request, root: Path) -> httpx.Response | None:
    if request.url.path == "/api/control-token":
        return httpx.Response(
            200,
            json={
                "header": "X-Vibelution-Control-Token",
                "controlToken": "control-1",
            },
        )
    if request.url.path == "/api/v1/external-agent/info":
        return httpx.Response(
            200,
            json={
                "apiProtocolVersion": "1.0",
                "serverVersion": "0.3.1",
                "projectRoot": str(root.resolve()),
                "runtimeSourceRevision": "rev-1",
            },
        )
    return None


@pytest.mark.anyio
async def test_client_reconnects_and_replays_once_after_control_token_rotation(
    tmp_path,
) -> None:
    _runtime_state(tmp_path)
    state = {"tokenFetches": 0, "agentsCalls": 0, "rotated": False}

    def handler(request: httpx.Request) -> httpx.Response:
        handshake = _handshake_response(request, tmp_path)
        if handshake is not None:
            if request.url.path == "/api/control-token":
                state["tokenFetches"] += 1
                token = "control-2" if state["rotated"] else "control-1"
                handshake = httpx.Response(
                    200,
                    json={
                        "header": "X-Vibelution-Control-Token",
                        "controlToken": token,
                    },
                )
            return handshake
        if request.url.path == "/api/v1/external-agent/agents":
            state["agentsCalls"] += 1
            submitted = request.headers.get("X-Vibelution-Control-Token")
            if state["rotated"] and submitted != "control-2":
                return httpx.Response(
                    403,
                    json={"detail": "Missing or invalid web control token"},
                )
            return httpx.Response(200, json={"status": "ok", "agents": []})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(handler),
    )

    first = await client.list_agents()
    assert first["agents"] == []

    # Simulate a backend restart that rotates the control token.
    state["rotated"] = True
    second = await client.list_agents()

    assert second["agents"] == []
    # Initial fetch + one reconnect after the rejected replay.
    assert state["tokenFetches"] == 2
    assert state["agentsCalls"] == 3


@pytest.mark.anyio
async def test_client_persistent_control_token_403_retries_exactly_once(
    tmp_path,
) -> None:
    _runtime_state(tmp_path)
    state = {"tokenFetches": 0, "agentsCalls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        handshake = _handshake_response(request, tmp_path)
        if handshake is not None:
            if request.url.path == "/api/control-token":
                state["tokenFetches"] += 1
            return handshake
        if request.url.path == "/api/v1/external-agent/agents":
            state["agentsCalls"] += 1
            return httpx.Response(
                403,
                json={"detail": "Missing or invalid web control token"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        BackendClientError, match="Missing or invalid web control token"
    ):
        await client.list_agents()

    # One initial call + exactly one replay; the token was fetched twice.
    assert state["agentsCalls"] == 2
    assert state["tokenFetches"] == 2


@pytest.mark.anyio
async def test_client_business_403_does_not_trigger_token_reconnect(tmp_path) -> None:
    _runtime_state(tmp_path)
    state = {"tokenFetches": 0, "agentsCalls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        handshake = _handshake_response(request, tmp_path)
        if handshake is not None:
            if request.url.path == "/api/control-token":
                state["tokenFetches"] += 1
            return handshake
        if request.url.path == "/api/v1/external-agent/agents":
            state["agentsCalls"] += 1
            return httpx.Response(
                403,
                json={
                    "detail": {
                        "code": "CAPABILITY_DENIED",
                        "message": "Task capability is not valid.",
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(BackendClientError, match="Task capability is not valid"):
        await client.list_agents()

    # A business 403 must surface immediately, with no reconnect or replay.
    assert state["agentsCalls"] == 1
    assert state["tokenFetches"] == 1


@pytest.mark.anyio
async def test_management_action_post_uses_dedicated_write_timeout_below_dispatch_bound(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    from core.external_agent.backend_client import _MANAGEMENT_WRITE_TIMEOUT_SECONDS
    from core.assistant_runtime.dispatch import _NATIVE_REQUEST_TIMEOUT
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    seen = {}
    async def grant(**kwargs):
        return {"subjectId": "subject", "capability": "capability", "binding": {"projectId": "p", "instanceId": "i"}}
    async def request(method, path, **kwargs):
        seen.update(method=method, path=path, kwargs=kwargs)
        return {"status": "completed", "action": "agent_create", "requestId": "create-1", "verified": True,
                "reused": False, "agent": {"agentId": "native-agent"}}
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    await client.management_action(action="agent_create", request_id="create-1", parameters={"display_name": "Worker"})
    assert seen["method"] == "POST" and seen["path"].endswith("/actions/agent_create")
    assert seen["kwargs"]["timeout_seconds"] == 25.0
    # The client-layer write timeout must fire before the dispatch outer bound
    # so the error carries the request_id and the receipt can be reconciled.
    assert 0.5 <= _MANAGEMENT_WRITE_TIMEOUT_SECONDS == 25.0 < _NATIVE_REQUEST_TIMEOUT


@pytest.mark.anyio
@pytest.mark.parametrize("transport_error,expected_code", [
    (httpx.ReadTimeout("slow body"), "BACKEND_TIMEOUT"),
    (httpx.WriteTimeout("slow upload"), "BACKEND_TIMEOUT"),
    (httpx.PoolTimeout("pool exhausted"), "BACKEND_TIMEOUT"),
    (httpx.ConnectTimeout("never connected"), "BACKEND_UNAVAILABLE"),
    (httpx.ConnectError("connection refused"), "BACKEND_UNAVAILABLE"),
])
async def test_sent_request_timeouts_split_from_unreachable_on_management_writes(tmp_path, transport_error, expected_code):
    _runtime_state(tmp_path)
    calls = []
    ordinary = _transport(tmp_path, calls)
    binding = {"projectId": "project-1", "instanceId": "instance-1"}
    capability = "private-capability-" + "a" * 40
    prefix = "/api/v1/launcher-assistant-management"
    def handler(request):
        if request.url.path == prefix + "/binding":
            return httpx.Response(200, json={"protocolVersion": 1, "binding": binding})
        if request.url.path == prefix + "/subjects/bind":
            body = json.loads(request.content)
            return httpx.Response(200, json={"protocolVersion": 1, "subject_id": "ops-1234567890abcdef",
                "subject_capability": capability, "binding": binding, "scopes": body["scopes"]})
        if request.url.path.startswith(prefix + "/actions/") and request.method == "POST":
            raise transport_error
        return ordinary.handle_request(request)
    client = ManagedAgentBackendClient(
        tmp_path, state_path=tmp_path / "credentials.json", transport=httpx.MockTransport(handler))
    with pytest.raises(BackendClientError) as failure:
        await client.management_action(action="agent_create", request_id="create-1", parameters={"display_name": "Worker"})
    assert failure.value.code == expected_code
    if expected_code == "BACKEND_TIMEOUT":
        # The request was sent, so the dispatch layer can reconcile read-only
        # through management_receipt with this exact identity.
        assert failure.value.management_action == "agent_create"
        assert failure.value.management_request_id == "create-1"
