"""Batch purge approval shows the whole manifest; one approval covers one batch."""
import asyncio
import json
from copy import deepcopy

import pytest

from core.assistant_runtime.actions import agent_purge_batch_approval_summary, bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchError, DispatchService
from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient
from core.web.services.session.tool_approvals import _assistant_management_summary

PARAMETERS = {"project_id": "registered:1", "request_id": "batch-1", "purges": [
    {"agent_id": "agent-1", "expected_config_revision": 9007199254740993},
    {"agent_id": "agent-2", "expected_config_revision": 7},
    {"agent_id": "agent-3", "expected_config_revision": 11}]}


def batch_receipt(**changes):
    return {"status": "completed", "action": "agent_purge_batch", "requestId": "batch-1", "verified": True,
            "reused": False, "purgeBatch": {"results": [
                {"agentId": "agent-1", "outcome": "purged", "cleanupPending": False},
                {"agentId": "agent-2", "outcome": "rejected", "code": "STATE_CONFLICT"},
                {"agentId": "agent-3", "outcome": "purged", "cleanupPending": True}]}, **changes}


def test_batch_summary_shows_every_target_for_one_approval(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary({"action": "agent_purge_batch", "arguments_json": json.dumps(PARAMETERS)})
    assert result == agent_purge_batch_approval_summary(PARAMETERS)
    assert result["assistantTargets"] == {"project_id": "registered:1", "request_id": "batch-1", "batchCount": "3"}
    assert result["assistantPurgeItems"] == [{"agent_id": "agent-1", "expected_config_revision": "9007199254740993"},
        {"agent_id": "agent-2", "expected_config_revision": "7"}, {"agent_id": "agent-3", "expected_config_revision": "11"}]
    assert result["assistantPurgeIrreversible"] is True
    assert result["assistantPurgeEffects"] == ["agent", "sessions", "private_workspace", "team_room_mode_references"]


def test_batch_duplicate_json_keys_cannot_be_approved_or_executed(monkeypatch):
    import tools.personal_assistant_tools as tools

    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tools, "_identity", lambda: {"agentId": "native", "sessionId": "native-session"})
    calls = []
    monkeypatch.setattr("core.assistant_runtime.actions.execute_action", lambda *_a, **_kw: calls.append(True))
    raw = json.dumps(PARAMETERS)[:-1] + ', "project_id": "another-project"}'
    assert _assistant_management_summary({"action": "agent_purge_batch", "arguments_json": raw}) == {
        "assistantAction": "agent_purge_batch", "assistantArgumentsInvalid": True}
    result = tools.personal_assistant_manage_tool("agent_purge_batch", raw)
    assert calls == []
    assert "Duplicate" in result


@pytest.mark.parametrize("change", [{"force": True}, {"approved": True},
    {"purges": [{"agent_id": "bad\nagent", "expected_config_revision": 1}]},
    {"purges": []}, {"purges": [{"agent_id": "agent-1", "expected_config_revision": True}]},
    {"project_id": "bad\u202eproject"}, {"request_id": "bad.request"},
    {"purges": [{"agent_id": "agent-1", "expected_config_revision": 1},
                {"agent_id": "agent-1", "expected_config_revision": 2}]}])
def test_batch_summary_rejects_unreviewable_or_open_requests(monkeypatch, change):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary({"action": "agent_purge_batch",
        "arguments_json": json.dumps({**PARAMETERS, **change})})
    assert result == {"assistantAction": "agent_purge_batch", "assistantArgumentsInvalid": True}


def test_batch_stays_outside_non_launcher_surfaces_and_keeps_per_call_high_risk(monkeypatch):
    from core.web.services.session.assistant_manage_policy import (
        ASSISTANT_MANAGE_HIGH_RISK_ACTIONS, ASSISTANT_MANAGE_LOW_RISK_ACTIONS)
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: False)
    assert _assistant_management_summary({"action": "agent_purge_batch",
        "arguments_json": json.dumps(PARAMETERS)})["assistantArgumentsInvalid"]
    assert "agent_purge_batch" in ASSISTANT_MANAGE_HIGH_RISK_ACTIONS
    assert "agent_purge_batch" not in ASSISTANT_MANAGE_LOW_RISK_ACTIONS


@pytest.mark.anyio
async def test_batch_discovery_governed_gate_one_call_receipt_only_retry(tmp_path, monkeypatch):
    import tools.personal_assistant_tools as tools
    calls = []
    parameters = {**PARAMETERS, "project_id": "p"}

    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_action(self, **values):
            calls.append(("write", values))
            return batch_receipt()
        async def management_receipt(self, **query):
            calls.append(("receipt", query))
            return batch_receipt(reused=True)
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=lambda *_a, **_kw: Client())
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    bind_actions(service, asyncio.get_running_loop())
    try:
        index = execute_action("index", {"query": "purge"})
        assert any(item["action"] == "agent_purge_batch" and item["governed"] for item in index["actions"])
        contract = execute_action("describe", {"action": "agent_purge_batch"})
        assert contract["scope"] == "agents:purge" and "50" in contract["description"]
        assert contract["parameters"]["properties"]["purges"]["maxItems"] == 50
        # The governed gate holds the whole batch behind one approval; zero
        # native calls happen before it.
        denied = await asyncio.to_thread(execute_action, "agent_purge_batch", deepcopy(parameters))
        assert denied["status"] == "approval_required" and calls == []
        raw = await asyncio.to_thread(tools.personal_assistant_manage_tool, "agent_purge_batch", json.dumps(parameters))
        payload = json.loads(raw)
        assert payload["purgeBatch"]["results"][1]["code"] == "STATE_CONFLICT"
        await asyncio.to_thread(execute_action, "agent_purge_batch", deepcopy(parameters), governed=True)
        assert [kind for kind, _ in calls] == ["write", "receipt"]
        returned = await asyncio.to_thread(execute_action, "management_receipt",
            {"project_id": "p", "action": "agent_purge_batch", "request_id": "batch-1"})
        assert returned["reused"] is True and returned["purgeBatch"]["results"][0]["outcome"] == "purged"
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_batch_admission_never_replays_after_a_lost_server_receipt(tmp_path):
    calls = []

    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_action(self, **values):
            calls.append("write")
            return batch_receipt()
        async def management_receipt(self, **query):
            calls.append("receipt")
            raise DispatchError("Missing.", code="REQUEST_UNAVAILABLE")
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=lambda *_a, **_kw: Client())
    manifest = {"purges": deepcopy(PARAMETERS["purges"])}
    first = await service.management.invoke("p", action="agent_purge_batch", request_id="batch-1",
        parameters=deepcopy(manifest))
    assert first["status"] == "completed"
    with pytest.raises(DispatchError) as blocked:
        await service.management.invoke("p", action="agent_purge_batch", request_id="batch-1",
            parameters=deepcopy(manifest))
    assert blocked.value.code == "OPERATION_UNCONFIRMED"
    assert calls == ["write", "receipt"]


def test_batch_sdk_rejects_open_parameters_and_malformed_receipts(tmp_path, monkeypatch):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "sdk.json")
    state = {"payload": batch_receipt(), "calls": []}

    async def grant(**_kwargs):
        return {"subjectId": "subject", "capability": "capability", "binding": {"projectId": "p", "instanceId": "i"}}

    async def request(method, path, **kwargs):
        state["calls"].append((method, path, kwargs))
        return deepcopy(state["payload"])
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)

    async def exercise():
        result = await client.management_action(action="agent_purge_batch", request_id="batch-1",
            parameters={"purges": PARAMETERS["purges"]})
        assert result["purgeBatch"]["results"][2]["cleanupPending"] is True
        assert state["calls"][0][1].endswith("/actions/agent_purge_batch")
        for bad in ({"purges": []}, {"purges": PARAMETERS["purges"] * 20},
                    {"purges": [{**PARAMETERS["purges"][0], "expected_config_revision": "7"}]}):
            with pytest.raises(BackendClientError) as failure:
                await client.management_action(action="agent_purge_batch", request_id="batch-2", parameters=bad)
            assert failure.value.code == "INVALID_MANAGEMENT_REQUEST"
        for fault in ({"verified": False}, {"purgeBatch": None}, {"purge": {"agentId": "x", "status": "purged", "cleanupPending": False}},
                      {"purgeBatch": {"results": [{"agentId": "a", "outcome": "purged"}]}}):
            state["payload"] = {**batch_receipt(reused=True), **fault}
            with pytest.raises(BackendClientError) as failure:
                await client.management_receipt(action="agent_purge_batch", request_id="batch-1")
            assert failure.value.code == "BACKEND_PROTOCOL_ERROR"
        state["payload"] = {**batch_receipt(reused=True), "status": "unknown", "verified": False,
                            "code": "OPERATION_UNCONFIRMED"}
        unknown = await client.management_receipt(action="agent_purge_batch", request_id="batch-1")
        assert unknown["status"] == "unknown" and unknown["purgeBatch"]["results"][1]["code"] == "STATE_CONFLICT"
    asyncio.run(exercise())
