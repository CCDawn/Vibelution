"""Team recovery uses original operator grants, management intents and SDK IDs."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import launcher_assistant_management as route
from core.web.services.external_management import team_recovery_control as control
from core.web.services.external_management.service import ManagementError
from tests.test_external_management_team import BINDING, env


PARAMETERS = {"team_id": "team-a", "flow_id": "flow-a", "run_id": "run-a",
    "expected_revision": "3", "evidence_ref": "deployment:original-restart"}


def response():
    from core.web.services.external_management.runtime_operations import _fingerprint
    return {"teamId": "team-a", "flowId": "flow-a", "runId": "run-a", "revision": "4", "runStatus": "failed",
        "recovery": {"issueId": "issue-a", "nodeId": "node-a", "status": "repairing", "reason": "deployment_verification",
            "failureCount": 2, "repairAttempts": 1, "repairRunId": "repair-a", "codeRepairRunId": "",
            "evidenceCount": 2, "evidenceDigest": "0" * 64}, "commands": [], "untrustedContent": True,
        "businessAcceptance": "not_evaluated", "command": "confirm_deployment", "accepted": True,
        "evidenceDigest": _fingerprint(PARAMETERS["evidence_ref"]), "revisionCheck": "native_cas"}


@pytest.fixture
def recovery(env, monkeypatch):
    env.service.native = SimpleNamespace(project_root=env.root)
    existing = env.service._authorize(*env.args, None)
    missing = sorted({"operations:read", "operations:control"} - set(existing["scopes"]))
    if missing:
        env.service.invoke(*env.args, "authorization_upgrade", {"request_id": "recovery-scope",
            "expected_binding": BINDING, "parameters": {"expected_scopes": existing["scopes"], "add_scopes": missing}})
    calls = []
    def confirm(native, parameters):
        calls.append(deepcopy(parameters))
        return response()
    monkeypatch.setattr(control, "confirm_deployment", confirm)
    return env, calls


def test_deployment_intent_replays_original_receipt_without_reexecuting(recovery):
    env, calls = recovery
    envelope = {"request_id": "original-confirm", "expected_binding": BINDING, "parameters": PARAMETERS}
    first = env.service.invoke(*env.args, "team_recovery_confirm_deployment", envelope)
    assert first["status"] == "completed" and first["verified"] is True
    assert first["recovery"]["recovery"]["status"] == "repairing"
    again = env.service.invoke(*env.args, "team_recovery_confirm_deployment", envelope)
    assert again["reused"] is True and calls == [PARAMETERS]
    assert env.service.receipt(*env.args, "team_recovery_confirm_deployment", "original-confirm")["recovery"] == first["recovery"]
    with pytest.raises(ManagementError):
        env.service.invoke(*env.args, "team_recovery_confirm_deployment", {**envelope,
            "parameters": {**PARAMETERS, "evidence_ref": "different-deployment"}})
    assert calls == [PARAMETERS]


def test_unknown_confirmation_remains_original_request_without_replay(recovery, monkeypatch):
    env, calls = recovery
    def uncertain(native, parameters):
        calls.append(parameters)
        raise ManagementError("OPERATION_UNCONFIRMED", 503)
    monkeypatch.setattr(control, "confirm_deployment", uncertain)
    envelope = {"request_id": "lost-ack", "expected_binding": BINDING, "parameters": PARAMETERS}
    first = env.service.invoke(*env.args, "team_recovery_confirm_deployment", envelope)
    assert first["status"] == "unknown" and not first["verified"]
    assert env.service.receipt(*env.args, "team_recovery_confirm_deployment", "lost-ack")["status"] == "unknown"
    assert env.service.invoke(*env.args, "team_recovery_confirm_deployment", envelope)["status"] == "unknown"
    assert len(calls) == 1


def test_recovery_read_and_confirmation_do_not_gain_scopes(env, monkeypatch):
    grant = env.service.bind({"client_id": "minimal", "expected_binding": BINDING, "scopes": ["teams:read"]})
    args = (grant["subject_id"], grant["subject_capability"])
    monkeypatch.setattr(control, "read", lambda *a: pytest.fail("read without scope"))
    monkeypatch.setattr(control, "confirm_deployment", lambda *a: pytest.fail("control without scope"))
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service.read_team_recovery(*args, {key: PARAMETERS[key] for key in ("team_id", "flow_id", "run_id")})
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service.invoke(*args, "team_recovery_confirm_deployment", {"request_id": "denied",
            "expected_binding": BINDING, "parameters": PARAMETERS})
    assert env.service._authorize(*args, None)["scopes"] == ["teams:read"]


def test_recovery_http_requires_control_and_closed_exact_query(recovery, monkeypatch):
    env, _ = recovery
    view = {k: v for k, v in response().items() if k not in {"command", "accepted", "evidenceDigest", "revisionCheck"}}
    monkeypatch.setattr(control, "read", lambda native, parameters: view)
    monkeypatch.setattr(route, "_service", lambda: env.service)
    monkeypatch.setattr(route, "_credentials", lambda request: env.args)
    app = FastAPI(); app.include_router(route.router, prefix="/api")
    with TestClient(app) as client:
        url = "/api/v1/launcher-assistant-management/team-runs/recovery"
        query = {key: PARAMETERS[key] for key in ("team_id", "flow_id", "run_id")}
        assert client.get(url, params=query).status_code == 403
        headers = {CONTROL_TOKEN_HEADER: get_control_token()}
        assert client.get(url, params=query, headers=headers).json() == view
        assert client.get(url, params={**query, "force": "true"}, headers=headers).status_code == 422


@pytest.mark.parametrize("field", ["teamId", "flowId", "runId"])
def test_sdk_rejects_recovery_identity_substitution(tmp_path, monkeypatch, field):
    import asyncio
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "client.json")
    view = {k: v for k, v in response().items() if k not in {"command", "accepted", "evidenceDigest", "revisionCheck"}}
    view[field] = "different"
    async def read(path, model):
        assert path.startswith("/team-runs/recovery?")
        return model.model_validate(view).model_dump()
    monkeypatch.setattr(client, "_management_directory_read", read)
    with pytest.raises(BackendClientError, match="identity changed"):
        asyncio.run(client.management_team_recovery(team_id="team-a", flow_id="flow-a", run_id="run-a"))


@pytest.mark.parametrize("missing", ["clientId", "subjectId", "capability"])
def test_historical_flow_result_never_rebinds_missing_original_credentials(tmp_path, monkeypatch, missing):
    import asyncio
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "client.json")
    client._state["management"] = {"clientId": "client-original", "subjectId": "ops-" + "a" * 32,
        "capability": "c" * 48, "binding": BINDING}
    client._state["management"].pop(missing)
    async def no_request(*a, **kw):
        pytest.fail("Incomplete historical identity must fail before any network call")
    monkeypatch.setattr(client, "_request_json", no_request)
    monkeypatch.setattr(client, "_management_grant", no_request)
    monkeypatch.setattr(client, "_save_state_locked", lambda: pytest.fail("Read attempted credential mutation"))
    with pytest.raises(BackendClientError) as error:
        asyncio.run(client.management_flow_result(request_id="original", team_id="team-a", flow_id="flow-a", run_id="run-a"))
    assert error.value.code == "UNKNOWN_MANAGEMENT_SUBJECT"


@pytest.mark.parametrize("field", ["requestId", "teamId", "flowId", "runId"])
def test_flow_result_sdk_verifies_original_subject_and_each_result_identity(tmp_path, monkeypatch, field):
    import asyncio
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "client.json")
    client._state["management"] = {"clientId": "client-original", "subjectId": "ops-" + "a" * 32,
        "capability": "c" * 48, "binding": BINDING}
    result = {"requestId": "original", "teamId": "team-a", "flowId": "flow-a", "runId": "run-a",
        "status": "available", "runStatus": "completed", "terminal": True, "businessAcceptance": "not_evaluated",
        "text": "Final deliverable", "truncated": False, "textFiltered": False, "untrustedContent": True}
    result[field] = "different"
    calls = []
    async def request(method, path, **kwargs):
        calls.append((method, path))
        assert method == "GET"
        if path.endswith("/binding"):
            return {"protocolVersion": 1, "binding": BINDING}
        assert kwargs["management_auth"] == ("ops-" + "a" * 32, "c" * 48)
        return result
    monkeypatch.setattr(client, "_request_json", request)
    monkeypatch.setattr(client, "_save_state_locked", lambda: pytest.fail("Read attempted credential mutation"))
    with pytest.raises(BackendClientError, match="identity changed"):
        asyncio.run(client.management_flow_result(request_id="original", team_id="team-a", flow_id="flow-a", run_id="run-a"))
    assert len(calls) == 2


@pytest.mark.parametrize("tool_name", ["personal_assistant_action_tool", "personal_assistant_manage_tool"])
def test_repair_facts_survive_native_model_projection_for_reads_and_receipts(tool_name):
    import json
    from core.assistant_runtime.management_projection import project_team_recovery_for_model
    from core.infrastructure.tool_result import package_tool_result_facts, render_tool_result_for_model
    result = response()
    if tool_name.endswith("manage_tool"):
        result = {"action": "team_recovery_confirm_deployment", "requestId": "original", "status": "completed",
            "verified": True, "recovery": result}
    value = project_team_recovery_for_model(result)
    raw = json.dumps({"source": "launcher-assistant", "untrustedContent": True, **value}, ensure_ascii=False)
    facts = package_tool_result_facts(raw, tool_name=tool_name, action="team_recovery_get", max_chars=8000)
    rendered = render_tool_result_for_model(facts, max_chars=8000)
    assert all(text in rendered for text in ("repairState", "repairing", "issue-a", "deployment_verification"))


@pytest.mark.parametrize("action,scope", [("flow_result", "teams:results:read"), ("team_recovery_get", "operations:read")])
def test_read_scope_recovery_names_only_the_missing_original_permission(monkeypatch, action, scope):
    import json
    from tools import personal_assistant_tools as tool
    from core.infrastructure import native_runtime
    from core.assistant_runtime import actions
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tool, "_identity", lambda: {"agentId": "assistant", "turnId": "turn"})
    monkeypatch.setattr(actions, "execute_action", lambda *a, **kw: {"ok": False, "code": "SCOPE_DENIED"})
    result = json.loads(tool.personal_assistant_action_tool(action, {"project_id": "project"}))
    assert result["requiredScopes"] == [scope] and result["requiredScope"] == scope
    assert "authorization_status" in result["nextStep"]
