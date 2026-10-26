from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from core.external_agent.backend_client import (
    BackendClientError,
    ManagedAgentBackendClient,
)


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
        assert "sessions:pin" not in body["scopes"]
        return {"protocolVersion": 1, "binding": binding, "scopes": body["scopes"],
            "subject_id": "ops-1234567890abcdef", "subject_capability": "a" * 48}
    monkeypatch.setattr(client, "_request_json", request)
    await client._management_grant(require_existing=True)
    assert len(calls) == 1 and calls[0]["client_id"] == "legacy_client_1234567890"
    assert "sessions:pin" not in client._state["management"]["scopes"]


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


def _runtime_state(root: Path, *, url: str = "http://127.0.0.1:8123") -> None:
    git_dir = root / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("rev-1\n", encoding="utf-8")
    path = root / ".runtime" / "launcher" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "url": url,
                "runtimeProjectRoot": str(root.resolve()),
                "runtimeSourceCommit": "rev-1",
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
            assert body["scopes"] == ["agents:avatar", "agents:create", "agents:read", "agents:update", "platform:describe", "sessions:pin", "sessions:read", "teams:read", "teams:run"]
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
                json={
                    "apiProtocolVersion": "1.0",
                    "serverVersion": server_version,
                    "projectRoot": str(root.resolve()),
                    "runtimeSourceRevision": "rev-1",
                },
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
