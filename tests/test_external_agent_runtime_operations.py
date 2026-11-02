"""Operator HTTP, SDK and durable Launcher associations share closed contracts."""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from core.assistant_runtime.dispatch import DispatchError
from core.assistant_runtime.management import ManagementAdapter
from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient


PREFIX = "/v1/launcher-assistant-management"
DIGEST = "a" * 64
READ_SCOPES = {"operations:read", "teams:manage:read", "agents:tool-policy:read", "knowledge:acl:read", "teams:flows:read"}
WRITE_SCOPES = {"operations:control", "teams:write", "agents:tool-policy:write", "knowledge:acl:write",
                "teams:flows:write", "teams:flows:run", "agents:purge"}
OPERATION = {"kind": "research_run", "resourceId": "run-a", "status": "running", "revision": "1",
             "teamId": "team-a", "flowId": "flow-a", "commands": ["stop", "pause"]}
RUNTIME = {"kind": "research_run", "resource_id": "run-a", "team_id": "team-a", "flow_id": "flow-a",
           "command": "stop", "expected_revision": "1"}
FLOW = {"id": "flow-a", "name": "Native flow", "steps": []}
PARAMETERS = {
    "runtime_command": RUNTIME,
    "team_update": {"team_id": "team-a", "expected_team_fingerprint": DIGEST, "updates": {"name": "New name"}},
    "agent_tool_policy_update": {"agent_id": "agent-a", "expected_config_revision": 1,
        "expected_agent_updated_at": "v1", "expected_policy_fingerprint": DIGEST,
        "expected_registry_version": "registry-v1", "expected_registry_fingerprint": DIGEST,
        "updates": {"maxCallsPerTurn": 8}},
    "knowledge_acl_grant": {"knowledge_base_id": "team:team-a:kb-a", "target_agent_id": "agent-a",
        "permissions": ["read"], "expected_acl_fingerprint": DIGEST},
    "knowledge_acl_revoke": {"knowledge_base_id": "team:team-a:kb-a", "target_agent_id": "agent-a",
        "permissions": ["read"], "expected_acl_fingerprint": DIGEST},
    "flow_save": {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 0, "flow": FLOW},
    "flow_start": {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1, "values": {}},
    "agent_purge": {"agent_id": "agent-a", "expected_config_revision": 1},
}


def _proof(action):
    if action == "runtime_command":
        return {"operation": {**OPERATION, "status": "cancelled", "revision": "2", "commands": []},
                "command": "stop", "accepted": True, "stopRequested": True,
                "revisionCheck": "native_cas", "untrustedContent": True}
    if action.startswith("flow_"):
        result = {"action": action, "teamId": "team-a", "flowId": "flow-a", "revision": 1,
                  "status": "saved" if action == "flow_save" else "running", "verified": True,
                  "untrustedContent": True}
        if action == "flow_start":
            result["runId"] = "native-run"
        return result
    return {"action": action, "resourceId": "team-a" if action == "team_update" else
            "team:team-a:kb-a" if action.startswith("knowledge_acl") else "agent-a",
            "fingerprint": DIGEST, "verified": True, "untrustedContent": True}


def _flow_page(operation, query):
    common = {"source": "native-flow-definition", "teamId": query["team_id"], "digest": DIGEST,
              "offset": query.get("offset", 0), "limit": query.get("limit", 5 if operation == "list" else 512),
              "total": 1, "nextOffset": None, "untrustedContent": True}
    if operation == "list":
        return {**common, "flows": [{"flowId": "flow-a", "available": True, "name": "Native flow",
            "revision": 1, "fieldCount": 0, "stepCount": 0}], "complete": True, "truncated": False, "unavailableCount": 0}
    return {**common, "flowId": query["flow_id"], "revision": 1, "pointer": query.get("pointer", ""),
            "nodeType": "object", "items": [{"pointer": "/name", "kind": "string", "value": "Native flow"}]}


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management import asset_control, flow_control
    from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity
    from core.web.services.team_workflow.research_runtime.operator_authorization import current_server_operator

    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ID", "actual-server-operator")
    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ROLES", "operator")
    state = SimpleNamespace(writes=[], reads=[], contexts=[], transport=[], lose_ack=False, receipt_error=None,
                            transform=None, native_transform=None)
    def observe(action, value, *, write=False):
        operator = current_server_operator()
        state.contexts.append((action, operator.operator_id if operator else None, operator.roles if operator else ()))
        (state.writes if write else state.reads).append((action, deepcopy(value)))
    class Native:
        def __init__(self):
            self.agent = {"agentId": "agent-a", "directSessionId": "session-a", "displayName": "Agent",
                          "configRevision": 1, "updatedAt": "v1", "llmBindings": {}, "metadata": {}, "status": "archived"}
        def read_runtime_operations(self, query):
            observe("runtime_list", query.model_dump())
            rows = [deepcopy(OPERATION)] if query.offset == 0 else []
            return {"snapshot": DIGEST, "operations": rows, "offset": query.offset, "total": 1, "nextOffset": None,
                "coverage": [{"source": "research_run", "state": "available", "complete": True}],
                "complete": True, "untrustedContent": True}
        def read_runtime_operation(self, query):
            observe("runtime_get", query.model_dump())
            return {"operation": deepcopy(OPERATION), "untrustedContent": True}
        def runtime_command(self, parameters, marker):
            from core.web.services.team_workflow.research_runtime.operator_authorization import require_privileged_server_operator
            try:
                require_privileged_server_operator(command="cancel_run")
            except PermissionError:
                raise ManagementError("command_forbidden", 403) from None
            observe("runtime_command", parameters, write=True)
            result = _proof("runtime_command")
            return state.native_transform(result) if state.native_transform else result
        def purge(self, parameters, marker):
            observe("agent_purge", parameters, write=True)
            self.agent = None
            return {"agentId": "agent-a", "status": "purged", "cleanupPending": False}
        def read_archive_state(self, agent_id):
            return deepcopy(self.agent)
    class Assets:
        def __init__(self, native): pass
        def read_team(self, **query):
            observe("team_asset_get", query)
            return {"teamId": "team-a", "name": "Team", "description": "", "purpose": "", "status": "active",
                    "members": [], "updatedAt": "v1", "fingerprint": DIGEST, "untrustedContent": True}
        def read_tool_policy(self, **query):
            observe("agent_tool_policy_get", query)
            return {"agentId": "agent-a", "configRevision": 1, "agentUpdatedAt": "v1", "policyFingerprint": DIGEST,
                "registryVersion": "registry-v1", "registryFingerprint": DIGEST, "compiledMatches": True,
                "policy": {"maxCallsPerTurn": 4}, "visibleTools": [], "executableTools": [], "untrustedContent": True}
        def read_knowledge_acl(self, **query):
            observe("knowledge_acl_get", query)
            return {"knowledgeBaseId": "kb-a", "scopedKnowledgeBaseId": "team:team-a:kb-a", "ownerType": "team",
                "ownerId": "team-a", "status": "active", "updatedAt": "v1",
                "acl": {"read": "members", "propose": "members", "review": "owner", "grants": {}},
                "fingerprint": DIGEST, "untrustedContent": True}
        def update_team(self, parameters, marker): return mutate("team_update", parameters)
        def update_tool_policy(self, parameters, marker): return mutate("agent_tool_policy_update", parameters)
        def grant_knowledge_acl(self, parameters, marker): return mutate("knowledge_acl_grant", parameters)
        def revoke_knowledge_acl(self, parameters, marker): return mutate("knowledge_acl_revoke", parameters)
    def mutate(action, parameters):
        observe(action, parameters, write=True)
        return _proof(action)
    class Flows:
        def __init__(self, native): pass
        def list_flows(self, query):
            observe("flow_list", query.model_dump())
            return _flow_page("list", query.model_dump())
        def read_flow(self, query):
            observe("flow_get", query.model_dump())
            return _flow_page("get", query.model_dump())
        def save_flow(self, parameters, *, marker=None): return mutate("flow_save", parameters)
        def start_flow(self, parameters, *, request_id, marker=None): return mutate("flow_start", parameters)
    native, binding = Native(), {"projectId": "project-a", "instanceId": "instance-a"}
    service = ManagementService(tmp_path / "target-management", identity=lambda: TargetIdentity(binding, "authority"), native=native)
    grant = service.bind({"client_id": "integration-client", "expected_binding": binding, "scopes": ["agents:read"]})
    monkeypatch.setattr(route, "_SERVICE", service)
    monkeypatch.setattr(asset_control, "AssetControl", Assets)
    monkeypatch.setattr(flow_control, "FlowControl", Flows)
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant["subject_id"],
               route.CAPABILITY_HEADER: grant["subject_capability"]}
    app = FastAPI()
    app.include_router(route.router)
    sdk = ManagedAgentBackendClient(tmp_path / "project", state_path=tmp_path / "sdk.json")
    sdk._state["management"] = {"clientId": "integration-client", "subjectId": grant["subject_id"],
        "capability": grant["subject_capability"], "binding": binding, "scopes": ["agents:read"]}
    async def sdk_grant(**kwargs):
        return deepcopy(sdk._state["management"])
    monkeypatch.setattr(sdk, "_management_grant", sdk_grant)
    with TestClient(app) as client:
        async def request(method, path, **kwargs):
            state.transport.append((method, path, deepcopy(kwargs.get("json_payload"))))
            if method == "GET" and "/requests/" in path and state.receipt_error:
                raise BackendClientError("Authenticated target refused receipt.", code=state.receipt_error)
            request_headers = {CONTROL_TOKEN_HEADER: get_control_token()}
            if kwargs.get("management_auth"):
                subject, capability = kwargs["management_auth"]
                request_headers.update({route.SUBJECT_HEADER: subject, route.CAPABILITY_HEADER: capability})
            response = client.request(method, path.removeprefix("/api"), headers=request_headers, json=kwargs.get("json_payload"))
            if response.status_code >= 400:
                raise BackendClientError("Target refused request.", code=response.json()["detail"]["code"])
            payload = response.json()
            if state.lose_ack and method == "POST" and not path.endswith("/authorization_upgrade"):
                state.lose_ack = False
                raise BackendClientError("Native action acknowledgement was lost.", code="BACKEND_UNAVAILABLE")
            return state.transform(payload) if state.transform else payload
        monkeypatch.setattr(sdk, "_request_json", request)
        yield SimpleNamespace(client=client, service=service, sdk=sdk, state=state, headers=headers,
                              grant=grant, binding=binding, native=native, root=tmp_path)


def upgrade(api, scopes):
    current = api.client.get(PREFIX + "/authorization", headers=api.headers).json()["scopes"]
    result = api.client.post(PREFIX + "/actions/authorization_upgrade", headers=api.headers,
        json={"request_id": "grant-" + str(len(current)), "expected_binding": api.binding,
              "parameters": {"expected_scopes": current, "add_scopes": sorted(set(scopes) - set(current))}})
    assert result.status_code == 200 and result.json()["status"] == "completed"


def envelope(api, action, request_id="request-a"):
    return {"request_id": request_id, "expected_binding": api.binding, "parameters": deepcopy(PARAMETERS[action])}


async def adapter_call(api, project_id, operation):
    assert project_id == "project-a"
    try:
        return await operation(api.sdk)
    except BackendClientError as error:
        raise DispatchError("Target operation failed.", code=error.code) from None


def adapter(api):
    return ManagementAdapter(api.root / "launcher-profile", {"project-a": api.root / "project"},
        lambda project, operation: adapter_call(api, project, operation))


def forget_target_receipt(api, action, request_id):
    key = api.service._request_key(api.grant["subject_id"], action, request_id)
    api.service.store.path("requests", key).unlink()


def test_new_scopes_are_not_bootstrap_grants_and_upgrade_enables_real_http_reads_and_control(api):
    from core.external_agent.backend_client import _MANAGEMENT_SCOPES
    scopes = READ_SCOPES | WRITE_SCOPES
    assert not scopes.intersection(api.service.binding()["scopes"])
    assert not scopes.intersection(_MANAGEMENT_SCOPES)
    for suffix in ("/runtime/operations", "/assets/team?team_id=team-a", "/team-flows?team_id=team-a"):
        assert api.client.get(PREFIX + suffix, headers=api.headers).status_code == 403
    denied = api.client.post(PREFIX + "/actions/runtime_command", headers=api.headers, json=envelope(api, "runtime_command"))
    assert denied.status_code == 403 and api.state.writes == []
    upgrade(api, scopes)
    assert api.client.get(PREFIX + "/runtime/operations", headers=api.headers).status_code == 200
    assert api.client.get(PREFIX + "/assets/team?team_id=team-a", headers=api.headers).status_code == 200
    assert api.client.get(PREFIX + "/team-flows?team_id=team-a", headers=api.headers).status_code == 200
    first = api.client.post(PREFIX + "/actions/runtime_command", headers=api.headers, json=envelope(api, "runtime_command"))
    repeated = api.client.post(PREFIX + "/actions/runtime_command", headers=api.headers, json=envelope(api, "runtime_command"))
    assert first.status_code == 200 and first.json()["verified"] is True
    assert repeated.json()["reused"] is True and len(api.state.writes) == 1


def test_operator_context_comes_from_control_token_and_server_principal_not_claimed_headers(api, monkeypatch):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    forged = {"X-Vibelution-Operator-Id": "forged-admin", "X-Vibelution-Operator-Roles": "admin"}
    assert api.client.get(PREFIX + "/runtime/operations", headers=forged).status_code == 403
    assert api.state.reads == []
    response = api.client.get(PREFIX + "/runtime/operations", headers={**api.headers, **forged})
    assert response.status_code == 200
    assert api.state.contexts[-1] == ("runtime_list", "actual-server-operator", ("operator",))
    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ROLES", "reader")
    denied = api.client.post(PREFIX + "/actions/runtime_command", headers={**api.headers, **forged},
                             json=envelope(api, "runtime_command"))
    assert denied.status_code == 403 and api.state.writes == []


@pytest.mark.parametrize("suffix", ["/runtime/operations?kind=research_run&kind=team_run", "/runtime/operations?path=x",
    "/runtime/operation?kind=research_run&resource_id=run-a&team_id=team-a&flow_id=flow-a&session_id=wrong",
    "/assets/team?team_id=team-a&team_id=team-b", "/assets/team?team_id=team-a&force=true",
    "/team-flows?team_id=team-a&offset=0&offset=1", "/team-flow?team_id=team-a&flow_id=flow-a&unexpected=x"])
def test_http_queries_are_closed_and_duplicate_values_do_not_reach_owner(api, suffix):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    response = api.client.get(PREFIX + suffix, headers=api.headers)
    assert response.status_code == 422 and api.state.reads == [] and api.state.writes == []


@pytest.mark.parametrize("fault", ["extra", "duplicate_json", "query"])
def test_mutation_rejects_unknown_or_ambiguous_inputs_before_native_control(api, fault):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    payload = envelope(api, "runtime_command")
    path = PREFIX + "/actions/runtime_command"
    if fault == "extra":
        payload["parameters"]["actor"] = "forged-admin"
        response = api.client.post(path, headers=api.headers, json=payload)
    elif fault == "duplicate_json":
        raw = json.dumps(payload).replace('"command": "stop"', '"command": "stop", "command": "pause"')
        response = api.client.post(path, headers={**api.headers, "Content-Type": "application/json"}, content=raw)
    else:
        response = api.client.post(path + "?force=true", headers=api.headers, json=payload)
    assert response.status_code == 422 and api.state.writes == []


@pytest.mark.anyio
async def test_sdk_reads_real_http_runtime_assets_and_flows_with_exact_identity(api):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    assert (await api.sdk.management_runtime("list", kind="research_run"))["operations"][0]["resourceId"] == "run-a"
    assert (await api.sdk.management_runtime("get", **{key: RUNTIME[key] for key in ("kind", "resource_id", "team_id", "flow_id")}))["operation"]["teamId"] == "team-a"
    assert (await api.sdk.management_asset("team", team_id="team-a"))["teamId"] == "team-a"
    assert (await api.sdk.management_asset("tool-policy", agent_id="agent-a"))["policy"]["maxCallsPerTurn"] == 4
    assert (await api.sdk.management_asset("knowledge-acl", knowledge_base_id="team:team-a:kb-a"))["ownerId"] == "team-a"
    assert (await api.sdk.management_flow("list", team_id="team-a"))["flows"][0]["flowId"] == "flow-a"
    assert (await api.sdk.management_flow("get", team_id="team-a", flow_id="flow-a"))["pointer"] == ""


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["team_update", "agent_tool_policy_update"])
async def test_sdk_and_service_preserve_only_explicit_asset_patch_fields(api, action):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    result = await api.sdk.management_action(action=action, request_id="patch-one", parameters=PARAMETERS[action])
    assert result["verified"] is True
    assert api.state.writes[0][1]["updates"] == PARAMETERS[action]["updates"]
    posted = [row[2]["parameters"] for row in api.state.transport if row[0] == "POST" and row[1].endswith("/" + action)]
    assert posted[0]["updates"] == PARAMETERS[action]["updates"]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["kind", "resource", "team", "flow", "command", "action", "request", "extra", "verified"])
async def test_sdk_strictly_rejects_unbound_runtime_receipts(api, fault):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    def corrupt(payload):
        if fault == "kind": payload["operation"]["operation"]["kind"] = "team_run"
        elif fault == "resource": payload["operation"]["operation"]["resourceId"] = "other-run"
        elif fault == "team": payload["operation"]["operation"]["teamId"] = "other-team"
        elif fault == "flow": payload["operation"]["operation"]["flowId"] = "other-flow"
        elif fault == "command": payload["operation"]["command"] = "pause"
        elif fault == "action": payload["action"] = "flow_start"
        elif fault == "request": payload["requestId"] = "another-request"
        elif fault == "extra": payload["operation"]["privatePath"] = "SECRET"
        else: payload["verified"] = False
        return payload
    api.state.transform = corrupt
    with pytest.raises(BackendClientError) as error:
        await api.sdk.management_action(action="runtime_command", request_id="strict-one", parameters=RUNTIME)
    assert error.value.code == "BACKEND_PROTOCOL_ERROR" and len(api.state.writes) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("action,fault", [("team_update", "resource"), ("team_update", "verified"),
    ("flow_save", "team"), ("flow_save", "flow"), ("flow_start", "action"), ("flow_start", "extra")])
async def test_sdk_binds_asset_and_flow_receipt_proofs_to_original_request(api, action, fault):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    def corrupt(payload):
        proof = payload["asset" if action == "team_update" else "flow"]
        if fault == "resource": proof["resourceId"] = "another-team"
        elif fault == "verified": proof["verified"] = False
        elif fault == "team": proof["teamId"] = "another-team"
        elif fault == "flow": proof["flowId"] = "another-flow"
        elif fault == "action": proof["action"] = "flow_save"
        else: proof["privatePath"] = "SECRET"
        return payload
    api.state.transform = corrupt
    with pytest.raises(BackendClientError) as error:
        await api.sdk.management_action(action=action, request_id="strict-one", parameters=PARAMETERS[action])
    assert error.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
@pytest.mark.parametrize("action", PARAMETERS)
async def test_adapter_lost_ack_then_target_404_never_reposts_platform_or_purge(api, action):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    manager = adapter(api)
    api.state.lose_ack = True
    with pytest.raises(DispatchError) as lost:
        await manager.invoke("project-a", action=action, request_id="lost-one", parameters=PARAMETERS[action])
    assert lost.value.code == "BACKEND_UNAVAILABLE" and len(api.state.writes) == 1
    forget_target_receipt(api, action, "lost-one")
    for current in (manager, adapter(api)):
        with pytest.raises(DispatchError) as unknown:
            await current.invoke("project-a", action=action, request_id="lost-one", parameters=PARAMETERS[action])
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
    assert len(api.state.writes) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["runtime_command", "agent_purge"])
async def test_first_authenticated_scope_denial_allows_original_id_only_after_explicit_upgrade(api, action):
    manager = adapter(api)
    with pytest.raises(DispatchError) as denied:
        await manager.invoke("project-a", action=action, request_id="not-admitted", parameters=PARAMETERS[action])
    assert denied.value.code == "SCOPE_DENIED" and api.state.writes == []
    association = json.loads(next((api.root / "launcher-profile/assistant_management").glob("*.json")).read_text())
    assert association["admissionDenied"] == "SCOPE_DENIED"
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    result = await manager.invoke("project-a", action=action, request_id="not-admitted", parameters=PARAMETERS[action])
    assert result["status"] == "completed" and len(api.state.writes) == 1
    assert (await manager.invoke("project-a", action=action, request_id="not-admitted", parameters=PARAMETERS[action]))["reused"] is True


@pytest.mark.anyio
async def test_receipt_scope_denial_after_lost_ack_cannot_become_not_admitted_proof(api):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    manager = adapter(api)
    api.state.lose_ack = True
    with pytest.raises(DispatchError):
        await manager.invoke("project-a", action="runtime_command", request_id="lost-one", parameters=RUNTIME)
    api.state.receipt_error = "SCOPE_DENIED"
    with pytest.raises(DispatchError) as denied:
        await manager.invoke("project-a", action="runtime_command", request_id="lost-one", parameters=RUNTIME)
    assert denied.value.code == "SCOPE_DENIED"
    association = json.loads(next((api.root / "launcher-profile/assistant_management").glob("*.json")).read_text())
    assert "admissionDenied" not in association
    api.state.receipt_error = None
    forget_target_receipt(api, "runtime_command", "lost-one")
    with pytest.raises(DispatchError) as unknown:
        await manager.invoke("project-a", action="runtime_command", request_id="lost-one", parameters=RUNTIME)
    assert unknown.value.code == "OPERATION_UNCONFIRMED" and len(api.state.writes) == 1


@pytest.mark.anyio
async def test_legacy_team_run_may_resume_only_from_existing_native_resume_allowed_proof(tmp_path):
    calls = []
    class Client:
        async def management_action(self, **values):
            calls.append(values)
            return {"status": "unknown", "action": "team_run", "requestId": "team-one", "verified": False}
        async def management_receipt(self, **values):
            return {"status": "unknown", "action": "team_run", "requestId": "team-one", "verified": False,
                "phase": "flow_saved", "resumeAllowed": True, "teamRun": {"teamId": "team-a", "flowId": "flow-a"}}
    async def call(project, operation): return await operation(Client())
    manager = ManagementAdapter(tmp_path, {"project-a": tmp_path / "project"}, call)
    parameters = {"name": "Team", "goal": "Original goal", "template_id": "dev-team"}
    await manager.invoke("project-a", action="team_run", request_id="team-one", parameters=parameters)
    await manager.invoke("project-a", action="team_run", request_id="team-one", parameters=parameters)
    assert len(calls) == 2 and calls[1]["require_existing_subject"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("family,operation,parameters", [
    ("runtime", "list", {"limit": 4}),
    ("runtime", "get", {"kind": "research_run", "resource_id": "run-a", "team_id": "team-a"}),
    ("asset", "team", {"team_id": "team-a", "include_private": True}),
    ("flow", "get", {"team_id": "team-a", "flow_id": "flow-a", "pointer": "not-a-pointer"}),
    ("action", "team_update", {**PARAMETERS["team_update"], "updates": {"name": None}}),
    ("action", "agent_tool_policy_update", {**PARAMETERS["agent_tool_policy_update"], "updates": {"maxCallsPerTurn": None}}),
    ("action", "flow_save", {**PARAMETERS["flow_save"], "flow_id": "another-flow"}),
    ("action", "flow_start", {**PARAMETERS["flow_start"], "idempotencyKey": "model-key"}),
    ("action", "flow_start", {**PARAMETERS["flow_start"], "localIntegration": {"approved": True}}),
])
async def test_sdk_rejects_invalid_or_privilege_bearing_parameters_before_transport(api, family, operation, parameters):
    api.state.transport.clear()
    with pytest.raises(BackendClientError) as error:
        if family == "action":
            await api.sdk.management_action(action=operation, request_id="invalid-one", parameters=parameters)
        else:
            await getattr(api.sdk, "management_" + family)(operation, **parameters)
    assert error.value.code == "INVALID_MANAGEMENT_REQUEST" and api.state.transport == []


@pytest.mark.anyio
@pytest.mark.parametrize("family,operation,fault", [
    ("runtime", "list", "offset"), ("runtime", "list", "kind"), ("runtime", "list", "limit"),
    ("runtime", "get", "resource"), ("runtime", "get", "owner"),
    ("asset", "team", "identity"), ("asset", "tool-policy", "identity"),
    ("asset", "knowledge-acl", "identity"), ("asset", "knowledge-acl", "owner"),
    ("flow", "list", "team"), ("flow", "list", "offset"), ("flow", "list", "digest"), ("flow", "list", "limit"),
    ("flow", "get", "team"), ("flow", "get", "flow"), ("flow", "get", "pointer"), ("flow", "get", "digest"),
])
async def test_sdk_read_responses_remain_bound_to_requested_identity_and_cursor(api, monkeypatch, family, operation, fault):
    if family == "runtime":
        parameters = {"kind": "research_run", "limit": 1} if operation == "list" else {
            key: RUNTIME[key] for key in ("kind", "resource_id", "team_id", "flow_id")}
        payload = ({"operations": [deepcopy(OPERATION)], "offset": 0, "total": 1, "nextOffset": None,
            "coverage": [{"source": "research_run", "state": "available", "complete": True}],
            "complete": True, "untrustedContent": True} if operation == "list" else
            {"operation": deepcopy(OPERATION), "untrustedContent": True})
        if fault == "offset": payload.update(offset=1, total=2)
        elif fault == "kind": payload["operations"][0]["kind"] = "team_run"
        elif fault == "limit":
            payload["operations"].append({**OPERATION, "resourceId": "run-b"})
            payload["total"] = 2
        elif fault == "resource": payload["operation"]["resourceId"] = "another-run"
        else: payload["operation"]["teamId"] = "another-team"
    elif family == "asset":
        from core.web.services.external_management.asset_control import AssetControl
        owner = AssetControl(api.native)
        if operation == "team":
            parameters, payload = {"team_id": "team-a"}, owner.read_team(team_id="team-a")
            payload["teamId"] = "another-team"
        elif operation == "tool-policy":
            parameters, payload = {"agent_id": "agent-a"}, owner.read_tool_policy(agent_id="agent-a")
            payload["agentId"] = "another-agent"
        else:
            parameters = {"knowledge_base_id": "team:team-a:kb-a"}
            payload = owner.read_knowledge_acl(**parameters)
            if fault == "owner": payload["ownerId"] = "another-team"
            else: payload.update(knowledgeBaseId="another-kb", scopedKnowledgeBaseId="team:team-a:another-kb")
    else:
        parameters = {"team_id": "team-a", "limit": 1, "expected_digest": DIGEST}
        if operation == "get": parameters.update(flow_id="flow-a", pointer="")
        payload = _flow_page(operation, parameters)
        if fault == "team": payload["teamId"] = "another-team"
        elif fault == "offset": payload["offset"] = 1
        elif fault == "flow": payload["flowId"] = "another-flow"
        elif fault == "pointer": payload["pointer"] = "/another-node"
        elif fault == "digest": payload["digest"] = "b" * 64
        else:
            payload["limit"] = 2
            payload["flows"].append({**payload["flows"][0], "flowId": "flow-b"})
            payload["total"] = 2
    async def response(method, path, **kwargs): return deepcopy(payload)
    monkeypatch.setattr(api.sdk, "_request_json", response)
    with pytest.raises(BackendClientError) as error:
        await getattr(api.sdk, "management_" + family)(operation, **parameters)
    assert error.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.parametrize("fault", ["kind", "resource", "owner", "command", "extra"])
def test_service_never_verifies_a_mismatched_native_runtime_acknowledgement(api, fault):
    upgrade(api, READ_SCOPES | WRITE_SCOPES)
    def corrupt(result):
        if fault == "kind": result["operation"]["kind"] = "team_run"
        elif fault == "resource": result["operation"]["resourceId"] = "another-run"
        elif fault == "owner": result["operation"]["teamId"] = "another-team"
        elif fault == "command": result["command"] = "pause"
        else: result["privatePath"] = "SECRET"
        return result
    api.state.native_transform = corrupt
    payload = envelope(api, "runtime_command")
    for _ in range(2):
        response = api.client.post(PREFIX + "/actions/runtime_command", headers=api.headers, json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "unknown" and response.json()["verified"] is False
        assert response.json()["code"] == "OPERATION_UNCONFIRMED" and "operation" not in response.json()
    assert len(api.state.writes) == 1


@pytest.mark.anyio
async def test_sdk_flow_point_read_rejects_more_nodes_than_requested(api, monkeypatch):
    query = {"team_id": "team-a", "flow_id": "flow-a", "pointer": "", "limit": 1}
    payload = _flow_page("get", query)
    payload.update(limit=2, total=2)
    payload["items"].append({"pointer": "/description", "kind": "string", "value": "Second node"})
    async def response(method, path, **kwargs): return deepcopy(payload)
    monkeypatch.setattr(api.sdk, "_request_json", response)
    with pytest.raises(BackendClientError) as error:
        await api.sdk.management_flow("get", **query)
    assert error.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
@pytest.mark.parametrize("family,marker", [(family, marker) for family in ("runtime", "asset", "flow")
                                         for marker in (None, False, 1)])
async def test_sdk_requires_explicit_untrusted_marker_on_new_reads(api, monkeypatch, family, marker):
    if family == "runtime":
        operation, query = "get", {key: RUNTIME[key] for key in ("kind", "resource_id", "team_id", "flow_id")}
        payload = {"operation": deepcopy(OPERATION), "untrustedContent": True}
    elif family == "asset":
        from core.web.services.external_management.asset_control import AssetControl
        operation, query = "team", {"team_id": "team-a"}
        payload = AssetControl(api.native).read_team(**query)
    else:
        operation, query = "list", {"team_id": "team-a"}
        payload = _flow_page(operation, query)
    if marker is None:
        payload.pop("untrustedContent")
    else:
        payload["untrustedContent"] = marker
    async def response(method, path, **kwargs): return deepcopy(payload)
    monkeypatch.setattr(api.sdk, "_request_json", response)
    with pytest.raises(BackendClientError) as error:
        await getattr(api.sdk, "management_" + family)(operation, **query)
    assert error.value.code == "BACKEND_PROTOCOL_ERROR"
