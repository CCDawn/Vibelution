"""Team management authority survives HTTP, SDK and Launcher boundaries."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchError, DispatchService
from core.assistant_runtime.management import ManagementAdapter
from core.external_agent.backend_client import BackendClientError
from core.web.control import CONTROL_TOKEN_HEADER
from core.web.routes import launcher_assistant_management as route
from core.web.services.external_management import service as management_module
from core.web.services.external_management.contracts import ACTION_MODELS, contracts
from core.web.services.external_management.team_lifecycle_contracts import TEAM_ARCHIVE_EFFECTS
from core.web.services.external_management.team_lifecycle_control import TeamLifecycleControl
from tests.test_external_agent_backend_client import directory_client
from tests.test_launcher_assistant_management import BINDING, PREFIX, harness


HASH = "a" * 64
SCOPES = {"team_create": "teams:create", "team_member_add": "teams:write",
          "team_member_remove": "teams:write", "team_archive": "teams:archive"}
PARAMETERS = {
    "team_create": {"name": "New Team"},
    "team_member_add": {"team_id": "team-a", "expected_team_fingerprint": HASH, "member": {"agentId": "agent-a"}},
    "team_member_remove": {"team_id": "team-a", "expected_team_fingerprint": HASH, "agent_id": "agent-a"},
    "team_archive": {"team_id": "team-a", "expected_team_fingerprint": HASH,
        "expected_member_agent_ids": ["agent-a"], "expected_linked_chat_room_id": "room-a"},
}


def _preview():
    return {"teamId": "team-a", "fingerprint": HASH, "memberAgentIds": ["agent-a", "agent-b"],
            "linkedChatRoomId": "room-a", "effects": list(TEAM_ARCHIVE_EFFECTS), "untrustedContent": True}


def _upgrade(harness, grant, scopes):
    client, _service, _native, _control, _bind, headers, invoke = harness
    current = client.get(PREFIX + "/authorization", headers=headers(grant)).json()["scopes"]
    missing = sorted(set(scopes) - set(current))
    assert missing
    result = invoke(grant, action="authorization_upgrade", request_id="upgrade-" + str(len(current)),
                    parameters={"expected_scopes": current, "add_scopes": missing})
    assert result.status_code == 200 and result.json()["status"] == "completed"


def test_all_four_actions_are_discoverable_governed_and_reject_authority_injection():
    descriptions = contracts()
    for action, scope in SCOPES.items():
        assert descriptions[action]["governed"] is True
        assert descriptions[action]["scope"] == scope
        assert descriptions[action]["parameters"]["additionalProperties"] is False
        ACTION_MODELS[action].model_validate(PARAMETERS[action])
        for injection in ({"governed": True}, {"subject_id": "forged"}, {"team_source": "manual"}):
            with pytest.raises(ValidationError):
                ACTION_MODELS[action].model_validate({**PARAMETERS[action], **injection})


def test_new_create_and_archive_powers_require_explicit_upgrade_of_original_subject(harness):
    from core.external_agent.backend_client import _MANAGEMENT_SCOPES
    client, service, native, _control, bind, headers, invoke = harness
    grant = bind(scopes=["teams:read"]).json()
    additions = {"teams:create", "teams:archive"}
    assert additions.isdisjoint(service.binding()["scopes"])
    assert additions.isdisjoint(_MANAGEMENT_SCOPES)
    assert additions.isdisjoint(grant["scopes"])
    fresh = bind(client_id="cannot-bootstrap-new-team-powers", scopes=["teams:read", *sorted(additions)])
    assert fresh.status_code == 403 and fresh.json()["detail"]["code"] == "SCOPE_DENIED"
    for action in ("team_create", "team_archive"):
        rejected = invoke(grant, action=action, request_id="denied-" + action, parameters=PARAMETERS[action])
        assert rejected.status_code == 403 and rejected.json()["detail"]["code"] == "SCOPE_DENIED"
        key = service._request_key(grant["subject_id"], action, "denied-" + action)
        assert not service.store.path("requests", key).exists()
    _upgrade(harness, grant, additions)
    current = client.get(PREFIX + "/authorization", headers=headers(grant)).json()
    assert additions.issubset(current["scopes"])
    rebound = bind(scopes=current["scopes"])
    assert rebound.status_code == 200 and rebound.json()["subject_id"] == grant["subject_id"]
    assert rebound.json()["subject_capability"] == grant["subject_capability"]
    assert native.calls == []


def test_archive_requires_agent_archive_power_before_durable_intent_or_native_call(harness, monkeypatch):
    _client, service, _native, _control, bind, _headers, invoke = harness
    grant = bind(scopes=["teams:read"]).json()
    _upgrade(harness, grant, ["teams:archive"])
    calls = []
    def execute(_native, action, parameters, marker):
        calls.append((action, deepcopy(parameters), deepcopy(marker)))
        return {"action": action, "resourceId": parameters["team_id"], "fingerprint": HASH,
                "verified": True, "untrustedContent": True}
    monkeypatch.setattr(management_module, "execute_platform_action", execute)
    request_id = "native-cascade-needs-both-powers"
    denied = invoke(grant, action="team_archive", request_id=request_id, parameters=PARAMETERS["team_archive"])
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "SCOPE_DENIED"
    key = service._request_key(grant["subject_id"], "team_archive", request_id)
    assert not service.store.path("requests", key).exists() and calls == []
    _upgrade(harness, grant, ["agents:archive"])
    accepted = invoke(grant, action="team_archive", request_id=request_id, parameters=PARAMETERS["team_archive"])
    assert accepted.status_code == 200 and accepted.json()["status"] == "completed"
    assert len(calls) == 1 and calls[0][0] == "team_archive"


def test_http_archive_preview_requires_control_capability_scope_and_closed_query(harness, monkeypatch):
    client, _service, _native, control, bind, headers, _invoke = harness
    reads = []
    def read(_control, team_id):
        reads.append(team_id)
        return _preview()
    monkeypatch.setattr(TeamLifecycleControl, "read_archive_preview", read)
    grant = bind(scopes=["teams:read"]).json()
    path = PREFIX + "/assets/team-archive?team_id=team-a"
    for credentials in ({}, {CONTROL_TOKEN_HEADER: "wrong"}, control,
                        {**headers(grant), route.CAPABILITY_HEADER: "wrong"}):
        response = client.get(path, headers=credentials)
        assert response.status_code == 403
    response = client.get(path, headers=headers(grant))
    assert response.status_code == 403
    assert reads == []
    _upgrade(harness, grant, ["teams:manage:read"])
    for query in ("team_id=team-a&team_id=team-b", "team_id=team-a&force=true", "team_id=../other", ""):
        response = client.get(PREFIX + "/assets/team-archive?" + query, headers=headers(grant))
        assert response.status_code == 422
    assert reads == []
    response = client.get(path, headers=headers(grant))
    assert response.status_code == 200 and response.json() == _preview()
    assert reads == ["team-a"]


def test_http_archive_preview_drops_invalid_native_projection_without_leaking_extra_fields(harness, monkeypatch):
    client, _service, _native, _control, bind, headers, _invoke = harness
    grant = bind(scopes=["teams:read"]).json()
    _upgrade(harness, grant, ["teams:manage:read"])
    monkeypatch.setattr(TeamLifecycleControl, "read_archive_preview", lambda *_args, **_kwargs: _preview())
    path = PREFIX + "/assets/team-archive?team_id=team-a"
    baseline = client.get(path, headers=headers(grant))
    assert baseline.status_code == 200
    monkeypatch.setattr(TeamLifecycleControl, "read_archive_preview",
                        lambda *_args, **_kwargs: {**_preview(), "privateNativeData": "do-not-release"})
    safe_client = TestClient(client.app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
    response = safe_client.get(path, headers=headers(grant))
    assert response.status_code >= 400 and "do-not-release" not in response.text


@pytest.mark.anyio
async def test_sdk_archive_preview_uses_fixed_route_and_rejects_target_or_schema_changes(directory_client):
    client, state = directory_client
    state["payload"] = _preview()
    assert await client.management_asset("team-archive", team_id="team-a") == _preview()
    assert state["calls"] == [("GET", PREFIX + "/assets/team-archive?team_id=team-a")]
    before = len(state["calls"])
    with pytest.raises(BackendClientError) as invalid:
        await client.management_asset("team-archive", team_id="team-a", force=True)
    assert invalid.value.code == "INVALID_MANAGEMENT_REQUEST" and len(state["calls"]) == before
    for patch in ({"teamId": "team-b"}, {"untrustedContent": False}, {"untrustedContent": None},
                  {"privateNativeData": "do-not-release"}):
        state["payload"] = {**_preview(), **patch}
        with pytest.raises(BackendClientError) as changed:
            await client.management_asset("team-archive", team_id="team-a")
        assert changed.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
async def test_sdk_member_and_archive_receipts_bind_the_original_team_target(directory_client, monkeypatch):
    client, _state = directory_client
    calls, target = [], {"id": "team-a"}
    async def grant(**_kwargs):
        return {"subjectId": "operator", "capability": "capability", "binding": BINDING}
    async def request(method, path, **kwargs):
        calls.append((method, path, deepcopy(kwargs)))
        action = path.rsplit("/", 1)[-1]
        return {"status": "completed", "action": action, "requestId": "team-request", "verified": True, "reused": False,
                "asset": {"action": action, "resourceId": target["id"], "fingerprint": HASH,
                          "verified": True, "untrustedContent": True}}
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    for action in ("team_member_add", "team_member_remove", "team_archive"):
        target["id"] = "team-a"
        result = await client.management_action(action=action, request_id="team-request", parameters=PARAMETERS[action])
        assert result["asset"]["resourceId"] == "team-a"
        method, path, body = calls[-1]
        assert (method, path) == ("POST", PREFIX + "/actions/" + action)
        assert body["json_payload"]["expected_binding"] == BINDING
        assert body["management_auth"] == ("operator", "capability")
        target["id"] = "different-team"
        with pytest.raises(BackendClientError) as mismatch:
            await client.management_action(action=action, request_id="team-request", parameters=PARAMETERS[action])
        assert mismatch.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
async def test_runtime_preview_is_project_bound_paged_read_without_mutation_intent(tmp_path):
    reads = []
    def factory(_root, **_kwargs):
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}
            async def management_asset(self, operation, **query):
                reads.append((operation, deepcopy(query)))
                return _preview()
        return Client()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=factory)
    bind_actions(service, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(execute_action, "team_archive_preview", {
            "project_id": "p", "team_id": "team-a", "document_pointer": "/asset/memberAgentIds", "limit": 1})
        assert result["projectId"] == "p" and result["source"] == "managed-assets"
        assert result["untrustedContent"] is True and result["pointer"] == "/asset/memberAgentIds"
        assert result["total"] == 2 and result["nextOffset"] == 1 and len(result["items"]) == 1
        assert reads == [("team-archive", {"team_id": "team-a"})]
        assert not (tmp_path / "profile" / "assistant_management").exists()
        with pytest.raises(DispatchError) as denied:
            await service.management.asset("foreign", "team-archive", team_id="team-a")
        assert denied.value.code == "PROJECT_NOT_AUTHORIZED" and len(reads) == 1
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_runtime_archive_preview_drops_results_when_project_authority_changes_during_read(tmp_path):
    for change in ("revoked", "root", "revision"):
        projects, version = {"p": tmp_path / "project"}, {"revision": 1}
        async def call(project_id, _reader):
            if change == "revoked":
                projects.clear()
            elif change == "root":
                projects[project_id] = tmp_path / "different-project"
            else:
                version["revision"] += 1
            return _preview()
        owner = ManagementAdapter(tmp_path / change, lambda: projects, call,
            read_binding=lambda key: (projects.get(key), version["revision"]))
        with pytest.raises(DispatchError) as changed:
            await owner.asset("p", "team-archive", team_id="team-a")
        assert changed.value.code == "PROJECT_BINDING_CHANGED"


@pytest.mark.anyio
async def test_runtime_team_mutations_require_approval_and_restart_reads_original_requests_without_replay(tmp_path):
    writes, reads = [], []
    def receipt(values, reused):
        return {"status": "unknown", "action": values["action"], "requestId": values["request_id"],
                "verified": False, "reused": reused, "code": "OPERATION_UNCONFIRMED"}
    def factory(_root, **_kwargs):
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}
            async def management_action(self, **values):
                writes.append(deepcopy(values))
                return receipt(values, False)
            async def management_receipt(self, **values):
                reads.append(deepcopy(values))
                return receipt(values, True)
        return Client()
    profile, projects = tmp_path / "profile", {"p": tmp_path / "project"}
    service = DispatchService(profile, projects, client_factory=factory)
    bind_actions(service, asyncio.get_running_loop())
    normalized = {}
    try:
        for action, scope in SCOPES.items():
            description = execute_action("describe", {"action": action})
            assert description["governed"] is True and description["scope"] == scope
            normalized[action] = ACTION_MODELS[action].model_validate(PARAMETERS[action]).model_dump()
            parameters = {"project_id": "p", "request_id": "original-" + action, **normalized[action]}
            before = len(writes)
            denied = await asyncio.to_thread(execute_action, action, parameters)
            assert denied["status"] == "approval_required" and len(writes) == before
            result = await asyncio.to_thread(execute_action, action, parameters, governed=True)
            assert result["status"] == "unknown" and result["projectId"] == "p"
    finally:
        unbind_actions(service)
    restarted = DispatchService(profile, projects, client_factory=factory)
    for action in SCOPES:
        result = await restarted.management.invoke("p", action=action, request_id="original-" + action,
                                                   parameters=normalized[action])
        assert result["status"] == "unknown"
        with pytest.raises(DispatchError) as conflict:
            await restarted.management.invoke("p", action=action, request_id="original-" + action,
                                               parameters={**normalized[action], "name": "different request"})
        assert conflict.value.code == "MANAGEMENT_CONFLICT"
    assert len(writes) == 4 and len(reads) == 4
    assert {(row["action"], row["request_id"]) for row in reads} == {
        (action, "original-" + action) for action in SCOPES}
