"""Only the native managed Launcher path can execute permanent deletion."""
import asyncio
import json
from copy import deepcopy

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchService
from tests.test_external_agent_agent_purge_client import preview, receipt


@pytest.mark.anyio
async def test_purge_discovery_preview_governed_execution_and_receipt_only_retry(tmp_path, monkeypatch):
    import tools.personal_assistant_tools as tools
    calls = []
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_agent_purge_preview(self, **query):
            calls.append(("preview", query))
            return preview()
        async def management_action(self, **values):
            calls.append(("write", values))
            return receipt()
        async def management_receipt(self, **query):
            calls.append(("receipt", query))
            return receipt(reused=True)
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=lambda *_a, **_kw: Client())
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    bind_actions(service, asyncio.get_running_loop())
    parameters = {"project_id": "p", "request_id": "purge-1", "agent_id": "agent-1", "expected_config_revision": 3}
    try:
        for query in ("purge", "永久删除"):
            index = execute_action("index", {"query": query})
            assert any(item["action"] == "agent_purge" and item["governed"] for item in index["actions"])
        contract = execute_action("describe", {"action": "agent_purge"})
        assert contract["scope"] == "agents:purge" and "agent_purge_preview" in contract["description"]
        raw = await asyncio.to_thread(tools.personal_assistant_action_tool, "agent_purge_preview",
            {"project_id": "p", "agent_id": "agent-1"})
        assert json.loads(raw)["agent"]["configRevision"] == 3
        denied = await asyncio.to_thread(execute_action, "agent_purge", parameters)
        assert denied["status"] == "approval_required" and [kind for kind, _ in calls] == ["preview"]
        raw = await asyncio.to_thread(tools.personal_assistant_manage_tool, "agent_purge", json.dumps(parameters))
        assert json.loads(raw)["purge"]["agentId"] == "agent-1"
        await asyncio.to_thread(execute_action, "agent_purge", deepcopy(parameters), governed=True)
        assert [kind for kind, _ in calls] == ["preview", "write", "receipt"]
        returned = await asyncio.to_thread(execute_action, "management_receipt",
            {"project_id": "p", "action": "agent_purge", "request_id": "purge-1"})
        assert returned["reused"] is True and returned["purge"]["status"] == "purged"
    finally:
        unbind_actions(service)


def test_purge_missing_scope_explains_exact_existing_upgrade(monkeypatch):
    import tools.personal_assistant_tools as tools
    from core.assistant_runtime import actions
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    monkeypatch.setattr(actions, "execute_action", lambda *_a, **_kw: {"ok": False, "code": "SCOPE_DENIED"})
    result = json.loads(tools.personal_assistant_manage_tool("agent_purge", "{}"))
    assert result["requiredScopes"] == ["agents:purge"]
    assert "authorization_status" in result["nextStep"] and "authorization_upgrade" in result["nextStep"]
