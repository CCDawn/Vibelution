"""Closed SDK DTOs through the actual HTTP management/native config chain."""
from copy import deepcopy
import json

from fastapi import FastAPI
import httpx
import pytest

from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient
from tests.test_external_management_dispatch_access import env, metadata_env, authorized


@pytest.fixture
def client(env, monkeypatch):
    from core.web import control
    from core.web.routes import launcher_assistant_management as routes
    service, credentials, binding = authorized(env)
    monkeypatch.setattr(routes, "_SERVICE", service)
    monkeypatch.setattr(control, "_CONTROL_TOKEN", "fixture-control-token")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = ManagedAgentBackendClient(env.root, state_path=env.root / "client.json", transport=httpx.ASGITransport(app=app))
    client._verified, client._base_url, client._control_token = True, "http://127.0.0.1", "fixture-control-token"
    client._state["management"] = {"clientId": "original", "subjectId": credentials[0],
        "capability": credentials[1], "binding": binding}
    async def grant(**kwargs):
        return {"subjectId": credentials[0], "capability": credentials[1], "binding": binding}
    monkeypatch.setattr(client, "_management_grant", grant)
    return client, service, credentials, app


@pytest.mark.anyio
async def test_sdk_get_set_receipt_and_reconcile_use_original_native_transaction(client, env, monkeypatch):
    from core.web.services.external_management import dispatch_access
    sdk, service, credentials, app = client
    before = await sdk.management_asset("dispatch-access", agent_id="ordinary")
    assert before["agentId"] == "ordinary" and before["operatorEnabled"] is False
    parameters = {"agent_id": "ordinary", "enabled": True,
        "expected_public_config_hash": before["publicConfigHash"],
        "expected_eligibility_fingerprint": before["eligibilityFingerprint"]}
    commits = []
    apply = dispatch_access.apply_operator_config_transaction
    def record(*args, **kwargs):
        commits.append("one native config commit")
        return apply(*args, **kwargs)
    monkeypatch.setattr(dispatch_access, "apply_operator_config_transaction", record)
    result = await sdk.management_action(action="agent_dispatch_access_set", request_id="stable-request", parameters=parameters)
    assert result["status"] == "completed" and result["verified"] is True
    assert result["asset"]["resourceId"] == "ordinary"
    receipt = await sdk.management_receipt(action="agent_dispatch_access_set", request_id="stable-request")
    assert receipt["reused"] and receipt["asset"] == result["asset"]
    assert (await sdk.management_asset("dispatch-access", agent_id="ordinary"))["dispatchable"] is True
    await sdk.management_action(action="agent_dispatch_access_set", request_id="stable-request", parameters=parameters)
    assert commits == ["one native config commit"]
    proof = await sdk.management_reconciliation(action="agent_dispatch_access_set", request_id="stable-request")
    assert proof["state"] == "confirmed" and proof["target"] == {"agent_id": "ordinary"}


@pytest.mark.anyio
async def test_http_reads_and_writes_require_control_scope_and_closed_fields(client, env):
    sdk, service, credentials, app = client
    headers = {"X-Vibelution-Control-Token": "fixture-control-token",
        "X-Vibelution-Management-Subject": credentials[0], "X-Vibelution-Management-Capability": credentials[1]}
    url = "/api/v1/launcher-assistant-management/assets/dispatch-access"
    original = env.config.read_bytes()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as http:
        assert (await http.get(url + "?agent_id=ordinary")).status_code == 403
        for query in ("agent_id=ordinary&agent_id=hidden", "agent_id=ordinary&path=secret", "agent_id=ordinary&enabled=true"):
            assert (await http.get(url + "?" + query, headers=headers)).status_code == 422
        grant = service.store.read(service.store.path("subjects", credentials[0]))
        grant["scopes"].remove("agents:dispatch-access:read")
        service.store.write(service.store.path("subjects", credentials[0]), grant)
        denied = await http.get(url + "?agent_id=ordinary", headers=headers)
        assert denied.status_code == 403 and denied.json()["detail"]["code"] == "SCOPE_DENIED"
    assert env.config.read_bytes() == original


@pytest.mark.anyio
async def test_sdk_rejects_authority_list_and_ceiling_parameters_before_http(client, env):
    sdk, *_rest = client
    original = env.config.read_bytes()
    valid = {"agent_id": "ordinary", "enabled": True, "expected_public_config_hash": "a" * 64,
        "expected_eligibility_fingerprint": "b" * 64}
    for patch in ({"enabled": "true"}, {"allowed_agent_ids": []}, {"denied_agent_ids": []},
                  {"gateway_enabled": True}, {"config_path": "elsewhere"}, {"ceiling": "full_access"}, {"governed": True}):
        with pytest.raises(BackendClientError) as failure:
            await sdk.management_action(action="agent_dispatch_access_set", request_id="same", parameters={**valid, **patch})
        assert failure.value.code == "INVALID_MANAGEMENT_REQUEST"
    assert env.config.read_bytes() == original and not (env.config.parent / "backups").exists()


@pytest.mark.anyio
async def test_sdk_target_only_response_rejects_foreign_id_extra_config_and_inconsistent_flags(client, monkeypatch):
    sdk, *_rest = client
    valid = {"agentId": "ordinary", "gatewayEnabled": True, "operatorEnabled": False, "dispatchable": False,
        "dispatchReason": "operator_disabled", "publicConfigHash": "a" * 64,
        "eligibilityFingerprint": "b" * 64, "untrustedContent": True}
    payload = deepcopy(valid)
    async def response(*args, **kwargs): return deepcopy(payload)
    monkeypatch.setattr(sdk, "_request_json", response)
    for patch in ({"agentId": "foreign"}, {"allowed_agent_ids": []}, {"api_key": "private"},
                  {"gatewayEnabled": False, "operatorEnabled": True}, {"dispatchable": True}, {"untrustedContent": 1}):
        payload = {**valid, **patch}
        with pytest.raises(BackendClientError) as failure:
            await sdk.management_asset("dispatch-access", agent_id="ordinary")
        assert failure.value.code == "BACKEND_PROTOCOL_ERROR"
