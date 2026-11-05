from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from core.assistant_runtime.local_project_client import LocalAssistantBackendClient
from core.external_agent import backend_client as sdk
from core.external_agent.contracts import API_PROTOCOL_VERSION, SERVER_VERSION
from core.infrastructure import launcher_assistant_authority as authority

TOKEN = "test_only_" + "a" * 43
EXTERNAL = "/api/v1/external-agent"
LOCAL = "/api/local-assistant/v1/external-agent"


@pytest.mark.anyio
@pytest.mark.parametrize("namespace", [None, "external", "local"])
async def test_cleanup_uses_explicit_legacy_route_without_retagging_old_capabilities(tmp_path, monkeypatch, namespace):
    client, _, business = _client(tmp_path, monkeypatch)
    client._state["tasks"] = {"eat-legacy": {"taskCapability": "original-task-capability"}}
    if namespace:
        client._state["transportNamespaces"] = {_digest("original-task-capability"): namespace}
    before = json.loads(json.dumps(client._state))
    await client.preview_task_cleanup("eat-legacy")
    await client.cleanup_task("eat-legacy", 7, "a" * 64)
    task_prefix = LOCAL + ("/tasks/" if namespace == "local" else "/legacy-tasks/") + "eat-legacy"
    assert [request.url.path for request in business] == [task_prefix + "/cleanup/preview", task_prefix + "/cleanup"]
    assert client._state == before
    for request in business:
        assert request.headers["X-Vibelution-Management-Capability"] == TOKEN
        assert request.headers[sdk.TASK_CAPABILITY_HEADER] == "original-task-capability"
    assert json.loads(business[-1].content) == {"revision": 7, "fingerprint": "a" * 64}
    # Cleanup is the only compatibility operation; ordinary reads stay external.
    await client._request_json("GET", EXTERNAL + "/tasks/eat-legacy", task_capability="original-task-capability")
    assert business[-1].url.path == (LOCAL if namespace == "local" else EXTERNAL) + "/tasks/eat-legacy"


@pytest.mark.anyio
@pytest.mark.parametrize("has_task,authority_token,code", [
    (False, TOKEN, "TASK_CAPABILITY_UNAVAILABLE"), (True, "", "LAUNCHER_AUTHORITY_REQUIRED")])
async def test_legacy_cleanup_never_recovers_missing_credentials_or_bypasses_launcher_authority(
        tmp_path, monkeypatch, has_task, authority_token, code):
    client, calls, _ = _client(tmp_path, monkeypatch, capability=authority_token)
    if has_task:
        client._state["tasks"] = {"eat-legacy": {"taskCapability": "original-task-capability"}}
    with pytest.raises(sdk.BackendClientError) as exc:
        await client.preview_task_cleanup("eat-legacy")
    assert exc.value.code == code and calls == []


@pytest.fixture(autouse=True)
def process_authority():
    authority.install_launcher_authority(None)
    yield
    authority.install_launcher_authority(None)


def _client(tmp_path, monkeypatch, *, capability=TOKEN, retry=False, ordinary=False, responder=None):
    calls = []
    business_calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == "/api/control-token":
            return httpx.Response(200, json={"controlToken": "fresh-control"})
        if request.url.path == EXTERNAL + "/info":
            assert "X-Vibelution-Management-Capability" not in request.headers
            return httpx.Response(200, json={"apiProtocolVersion": API_PROTOCOL_VERSION,
                "serverVersion": SERVER_VERSION, "projectRoot": str(tmp_path.resolve()),
                "runtimeSourceRevision": "rev-1"})
        business_calls.append(request)
        if retry and len(business_calls) == 1:
            return httpx.Response(403, json={"detail": "missing or invalid web control token"})
        if responder is not None:
            return responder(request)
        return httpx.Response(200, json={"ok": True})
    kwargs = {"state_path": tmp_path / "sdk-state.json", "transport": httpx.MockTransport(handler)}
    client = (sdk.ManagedAgentBackendClient(tmp_path, **kwargs) if ordinary
              else LocalAssistantBackendClient(tmp_path, capability=capability, **kwargs))
    monkeypatch.setattr(client, "_runtime_descriptor", lambda: {
        "baseUrl": "http://127.0.0.1:8123", "runtimeSourceRevision": "rev-1"})
    monkeypatch.setattr(sdk, "_checkout_revision", lambda root: "rev-1")
    return client, calls, business_calls


@pytest.mark.anyio
async def test_local_client_keeps_identity_gate_and_preserves_request_and_private_state(tmp_path, monkeypatch):
    client, calls, business = _client(tmp_path, monkeypatch)
    client._state["transportNamespaces"] = {_digest("task-private"): "local"}
    payload = {"client_request_id": "stable-request", "agent_id": "agent-1", "task": "test"}
    await client._request_json("POST", EXTERNAL + "/tasks?source=assistant", task_capability="task-private",
        json_payload=payload, timeout_seconds=12.0, max_response_bytes=2048)
    assert [r.url.path for r in calls] == ["/api/control-token", EXTERNAL + "/info", LOCAL + "/tasks"]
    request = business[0]
    assert request.url.query == b"source=assistant"
    assert request.headers["X-Vibelution-Management-Subject"] == "launcher-local"
    assert request.headers["X-Vibelution-Management-Capability"] == TOKEN
    assert request.headers[sdk.TASK_CAPABILITY_HEADER] == "task-private"
    assert json.loads(request.content) == payload
    assert request.extensions["timeout"]["read"] == 12.0
    assert TOKEN not in repr(client._state)
    client._save_state_locked()
    assert TOKEN not in client.state_path.read_text(encoding="utf-8")


@pytest.mark.anyio
@pytest.mark.parametrize("ordinary,capability", [(True, TOKEN), (False, ""), (False, None)])
async def test_ordinary_client_and_missing_capability_keep_external_path(tmp_path, monkeypatch, ordinary, capability):
    if ordinary:
        authority.install_launcher_authority(TOKEN)
    client, _, business = _client(tmp_path, monkeypatch, capability=capability, ordinary=ordinary)
    await client.list_agents()
    assert business[0].url.path == EXTERNAL + "/agents"
    assert "X-Vibelution-Management-Capability" not in business[0].headers


@pytest.mark.anyio
async def test_process_accessor_can_inject_capability_but_explicit_empty_stays_external(tmp_path, monkeypatch):
    authority.install_launcher_authority(TOKEN)
    client, _, business = _client(tmp_path, monkeypatch, capability=None)
    await client.list_agents()
    assert business[0].url.path == LOCAL + "/agents"
    other, _, other_business = _client(tmp_path, monkeypatch, capability="")
    await other.list_agents()
    assert other_business[0].url.path == EXTERNAL + "/agents"


@pytest.mark.anyio
async def test_management_and_similar_prefixes_are_unchanged(tmp_path, monkeypatch):
    client, _, business = _client(tmp_path, monkeypatch)
    original_auth = ("ordinary-subject", "ordinary-private")
    for path in ("/api/v1/launcher-assistant-management/binding", "/api/v1/external-agent-other/tasks"):
        await client._request_json("GET", path, management_auth=original_auth)
        assert business[-1].url.path == path
        assert business[-1].headers["X-Vibelution-Management-Capability"] == original_auth[1]


@pytest.mark.anyio
@pytest.mark.parametrize("capability", [TOKEN, ""])
async def test_complete_directory_context_is_selected_by_local_identity_not_model(tmp_path, monkeypatch, capability):
    from tests.test_external_agent_agent_directory_client import directory_page

    payload = directory_page()
    if capability:
        payload["dispatchContext"] = "launcher_local"
    client, _, business = _client(tmp_path, monkeypatch, capability=capability,
        responder=lambda _request: httpx.Response(200, json=payload))
    async def grant(**_kwargs):
        return {"subjectId": "native-subject", "capability": "native-management-capability"}
    monkeypatch.setattr(client, "_management_grant", grant)
    result = await client.management_agent_list(dispatch_context="external" if capability else "launcher_local")
    assert result.get("dispatchContext", "external") == ("launcher_local" if capability else "external")
    request = business[0]
    assert request.url.params.get("dispatch_context") == ("launcher_local" if capability else None)
    assert request.headers["X-Vibelution-Management-Subject"] == "native-subject"
    assert request.headers["X-Vibelution-Management-Capability"] == "native-management-capability"
    assert TOKEN not in repr(client._state)
    assert not client.state_path.exists()


@pytest.mark.anyio
async def test_local_directory_refuses_old_external_only_response_without_retry_or_upgrade(tmp_path, monkeypatch):
    from tests.test_external_agent_agent_directory_client import directory_page

    client, _, business = _client(tmp_path, monkeypatch,
        responder=lambda _request: httpx.Response(200, json=directory_page()))
    async def grant(**_kwargs):
        return {"subjectId": "native-subject", "capability": "native-management-capability"}
    monkeypatch.setattr(client, "_management_grant", grant)
    with pytest.raises(sdk.BackendClientError) as failure:
        await client.management_agent_list()
    assert failure.value.code == "BACKEND_PROTOCOL_ERROR"
    assert len(business) == 1 and business[0].method == "GET"
    assert not client.state_path.exists()


@pytest.mark.anyio
async def test_control_token_retry_preserves_capability_task_parameters_and_idempotency(tmp_path, monkeypatch):
    client, calls, business = _client(tmp_path, monkeypatch, retry=True)
    client._state["transportNamespaces"] = {_digest("task-cap"): "local"}
    payload = {"client_request_id": "retry-stable", "agent_id": "agent-1"}
    await client._request_json("POST", EXTERNAL + "/tasks", task_capability="task-cap", json_payload=payload)
    assert len(business) == 2
    assert sum(r.url.path == EXTERNAL + "/info" for r in calls) == 2
    assert business[0].content == business[1].content
    for request in business:
        assert request.url.path == LOCAL + "/tasks"
        assert request.headers["X-Vibelution-Management-Capability"] == TOKEN
        assert request.headers[sdk.TASK_CAPABILITY_HEADER] == "task-cap"
        assert json.loads(request.content) == payload


@pytest.mark.parametrize("capability", ["invalid\nsecret", "x" * 129, 0, False, {}])
def test_invalid_explicit_capability_is_rejected_without_disclosure(tmp_path, capability):
    with pytest.raises(ValueError) as failure:
        LocalAssistantBackendClient(tmp_path, capability=capability)
    assert "secret" not in str(failure.value)


def _digest(capability):
    return hashlib.sha256(capability.encode()).hexdigest()


def _write_state(tmp_path, *, tasks=None, requests=None, namespaces=None):
    (tmp_path / "sdk-state.json").write_text(json.dumps({
        "schemaVersion": 1, "projectRoot": str(tmp_path.resolve()),
        "tasks": tasks or {}, "requests": requests or {},
        **({"transportNamespaces": namespaces} if namespaces is not None else {}),
    }), encoding="utf-8")


async def _start(client, request_id, **kwargs):
    return await client.start_task(agent_id="agent-1", task="development", permission_profile="workspace_write",
        client_request_id=request_id, title="", **kwargs)


@pytest.mark.anyio
async def test_legacy_accepted_task_keeps_external_read_heartbeat_and_cancel(tmp_path, monkeypatch):
    _write_state(tmp_path, tasks={"eat-old": {"taskCapability": "old-task-capability",
        "leaseId": "old-lease", "status": "running"}},
        requests={"old-request": {"taskCapability": "old-task-capability", "taskId": "eat-old"}})
    client, _, business = _client(tmp_path, monkeypatch)
    await client.get_task(task_id="eat-old")
    await client.heartbeat_task(task_id="eat-old")
    await client.cancel_task(task_id="eat-old")
    assert [r.url.path for r in business] == [EXTERNAL + "/tasks/eat-old",
        EXTERNAL + "/tasks/eat-old/heartbeat", EXTERNAL + "/tasks/eat-old/cancel"]
    assert all("X-Vibelution-Management-Capability" not in r.headers for r in business)


@pytest.mark.anyio
@pytest.mark.parametrize("accepted", [False, True])
async def test_old_request_retry_with_launcher_authority_never_starts_in_new_namespace(tmp_path, monkeypatch, accepted):
    old_cap = "old-task-capability"
    _write_state(tmp_path, requests={"old-request": {"taskCapability": old_cap,
        **({"taskId": "eat-old"} if accepted else {})}})
    native_tasks = {(EXTERNAL, "old-request", old_cap): "eat-old"}
    def responder(request):
        prefix = LOCAL if request.url.path.startswith(LOCAL) else EXTERNAL
        key = (prefix, "old-request", request.headers[sdk.TASK_CAPABILITY_HEADER])
        task_id = native_tasks.setdefault(key, "new-native-task")
        return httpx.Response(200, json={"taskId": task_id, "_leaseId": "lease", "status": "running"})
    client, _, business = _client(tmp_path, monkeypatch, responder=responder)
    assert (await _start(client, "old-request", require_existing_capability=True))["taskId"] == "eat-old"
    assert len(native_tasks) == 1
    assert business[-1].url.path == EXTERNAL + "/tasks"


@pytest.mark.anyio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_new_local_start_persists_namespace_before_post_and_recovers_after_lost_response(tmp_path, monkeypatch, error_type):
    natives = {}
    lost_response = True
    def responder(request):
        nonlocal lost_response
        task_cap = request.headers[sdk.TASK_CAPABILITY_HEADER]
        disk = json.loads((tmp_path / "sdk-state.json").read_text(encoding="utf-8"))
        assert disk["transportNamespaces"][_digest(task_cap)] == "local"
        assert TOKEN not in json.dumps(disk)
        assert request.url.path.startswith(LOCAL + "/")
        if request.method == "POST":
            body = json.loads(request.content)
            key = (body["client_request_id"], task_cap)
            natives.setdefault(key, "local-task")
            if lost_response:
                lost_response = False
                raise error_type("lost acknowledgement", request=request)
        else:
            key = (request.url.params["client_request_id"], task_cap)
        return httpx.Response(200, json={"taskId": natives[key], "_leaseId": "local-lease", "status": "running"})
    first, _, first_business = _client(tmp_path, monkeypatch, responder=responder)
    assert (await _start(first, "new-request"))["taskId"] == "local-task"
    assert [r.method for r in first_business] == ["POST", "GET"]
    assert [r.url.path for r in first_business] == [LOCAL + "/tasks", LOCAL + "/task-request"]
    original_cap = first_business[0].headers[sdk.TASK_CAPABILITY_HEADER]
    resumed, _, resumed_business = _client(tmp_path, monkeypatch, responder=responder)
    assert (await resumed.get_task_for_request(client_request_id="new-request"))["taskId"] == "local-task"
    assert (await _start(resumed, "new-request", require_existing_capability=True))["taskId"] == "local-task"
    assert len(natives) == 1
    assert [r.url.path for r in resumed_business] == [LOCAL + "/task-request", LOCAL + "/tasks"]
    assert all(r.headers[sdk.TASK_CAPABILITY_HEADER] == original_cap for r in resumed_business)


@pytest.mark.anyio
async def test_failed_start_lookup_retains_original_ambiguous_error_and_credential(tmp_path, monkeypatch):
    def responder(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("private timeout detail", request=request)
        return httpx.Response(404, json={"detail": {"code": "TASK_NOT_FOUND"}})

    client, _, business = _client(tmp_path, monkeypatch, responder=responder)
    with pytest.raises(sdk.BackendClientError) as failure:
        await _start(client, "stable-request")
    assert failure.value.code == "BACKEND_TIMEOUT"
    assert [r.method for r in business] == ["POST", "GET"]
    assert client._state["requests"]["stable-request"]["taskCapability"]
    assert not client._state["tasks"]


@pytest.mark.anyio
@pytest.mark.parametrize("legacy", [False, True])
async def test_ambiguous_external_start_keeps_sdk_behavior_without_local_recovery(tmp_path, monkeypatch, legacy):
    if legacy:
        _write_state(tmp_path, requests={"stable-request": {"taskCapability": "legacy-cap"}})
    def responder(request):
        raise httpx.ReadTimeout("lost external acknowledgement", request=request)
    client, _, business = _client(tmp_path, monkeypatch, capability=TOKEN if legacy else "", responder=responder)
    with pytest.raises(sdk.BackendClientError) as failure:
        await _start(client, "stable-request")
    assert failure.value.code == "BACKEND_TIMEOUT"
    assert len(business) == 1 and business[0].url.path == EXTERNAL + "/tasks"


@pytest.mark.anyio
async def test_explicit_local_start_rejection_does_not_query_or_replay(tmp_path, monkeypatch):
    client, _, business = _client(tmp_path, monkeypatch,
        responder=lambda request: httpx.Response(403, json={"detail": {"code": "AGENT_NOT_FOUND"}}))
    with pytest.raises(sdk.BackendClientError) as failure:
        await _start(client, "stable-request")
    assert failure.value.code == "AGENT_NOT_FOUND"
    assert len(business) == 1 and business[0].method == "POST"


@pytest.mark.anyio
async def test_mixed_state_restores_namespace_after_acceptance_and_keeps_unknown_cap_external(tmp_path, monkeypatch):
    _write_state(tmp_path, tasks={
        "eat-old": {"taskCapability": "old-cap", "leaseId": "old-lease", "status": "running"},
        "local-new": {"taskCapability": "local-cap", "leaseId": "local-lease", "status": "running"}},
        namespaces={_digest("local-cap"): "local"})
    client, _, business = _client(tmp_path, monkeypatch)
    await client.get_task(task_id="eat-old")
    await client.get_task(task_id="local-new")
    await client._request_json("GET", EXTERNAL + "/tasks/unregistered", task_capability="unknown-cap")
    assert [r.url.path for r in business] == [EXTERNAL + "/tasks/eat-old", LOCAL + "/tasks/local-new",
        EXTERNAL + "/tasks/unregistered"]


@pytest.mark.anyio
async def test_local_namespace_without_authority_and_unstable_request_fail_before_network(tmp_path, monkeypatch):
    _write_state(tmp_path, requests={"local-request": {"taskCapability": "local-cap"}},
        namespaces={_digest("local-cap"): "local"})
    client, calls, _ = _client(tmp_path, monkeypatch, capability="")
    with pytest.raises(sdk.BackendClientError) as missing:
        await client.get_task_for_request(client_request_id="local-request")
    assert missing.value.code == "LAUNCHER_AUTHORITY_REQUIRED"
    with pytest.raises(sdk.BackendClientError):
        await _start(client, "")
    assert not calls


@pytest.mark.anyio
async def test_namespace_not_found_never_falls_back_or_mints_replacement(tmp_path, monkeypatch):
    _write_state(tmp_path, requests={"local-request": {"taskCapability": "local-cap"}},
        namespaces={_digest("local-cap"): "local"})
    client, _, business = _client(tmp_path, monkeypatch,
        responder=lambda request: httpx.Response(404, json={"detail": {"code": "TASK_NOT_FOUND"}}))
    with pytest.raises(sdk.BackendClientError) as missing:
        await client.get_task_for_request(client_request_id="local-request")
    assert missing.value.code == "TASK_NOT_FOUND"
    assert [r.url.path for r in business] == [LOCAL + "/task-request"]


@pytest.mark.anyio
async def test_new_task_added_to_legacy_state_pins_both_transports(tmp_path, monkeypatch):
    _write_state(tmp_path, tasks={"eat-old": {"taskCapability": "old-cap", "leaseId": "old-lease", "status": "running"}},
        requests={"old-request": {"taskCapability": "old-cap", "taskId": "eat-old"}})
    def responder(request):
        return httpx.Response(200, json={"taskId": "local-new", "_leaseId": "local-lease", "status": "running"})
    client, _, _ = _client(tmp_path, monkeypatch, responder=responder)
    await _start(client, "new-request")
    resumed, _, business = _client(tmp_path, monkeypatch)
    await resumed.get_task(task_id="eat-old")
    await resumed.get_task(task_id="local-new")
    assert [r.url.path for r in business] == [EXTERNAL + "/tasks/eat-old", LOCAL + "/tasks/local-new"]
    assert "X-Vibelution-Management-Capability" not in business[0].headers


@pytest.mark.anyio
async def test_malformed_transport_metadata_cannot_grant_local_routing(tmp_path, monkeypatch):
    _write_state(tmp_path, namespaces={_digest("bad-cap"): {}, "not-a-digest": "local"})
    client, _, business = _client(tmp_path, monkeypatch)
    await client._request_json("GET", EXTERNAL + "/tasks/unknown", task_capability="bad-cap")
    await client._request_json("POST", EXTERNAL + "/tasks")
    assert client._state["transportNamespaces"] == {}
    assert [r.url.path for r in business] == [EXTERNAL + "/tasks/unknown", EXTERNAL + "/tasks"]
    assert all("X-Vibelution-Management-Capability" not in r.headers for r in business)
