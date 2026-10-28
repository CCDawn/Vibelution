import asyncio
import json

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchService


@pytest.mark.anyio
async def test_team_knowledge_directory_is_available_through_assistant_tool(tmp_path, monkeypatch):
    import core.infrastructure.native_runtime as native_runtime
    import tools.personal_assistant_tools as assistant_tools
    from core.infrastructure.tool_result_budget import apply_tool_result_budget
    from core.infrastructure.tool_result import package_tool_result_facts, render_tool_result_for_model

    calls = []
    rows = [{"id": f"base-{i}" + "x" * 120, "name": "知" * 64, "status": "active"} for i in range(6)]

    def factory(root, **kwargs):
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}

            async def management_team_knowledge(self, **query):
                calls.append(query)
                return {"teamId": query["team_id"], "knowledgeBases": rows, "total": 6,
                        "offset": 0, "nextOffset": None, "untrustedContent": True,
                        "requiredScopes": ["knowledge:catalog:read", "teams:directory:read"],
                        "coverage": "Only existing team knowledge metadata; no content or Agent authorization."}
        return Client()

    project_id = "p" * 160
    service = DispatchService(tmp_path / "profile", {project_id: tmp_path / "project"}, client_factory=factory)
    monkeypatch.setattr(assistant_tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    bind_actions(service, asyncio.get_running_loop())
    try:
        assert "knowledge:catalog:read" in execute_action("describe", {"action": "team_knowledge_list"})["description"]
        raw = await asyncio.to_thread(assistant_tools.personal_assistant_action_tool,
                                      "team_knowledge_list", {"project_id": project_id, "team_id": "team-a"})
        budgeted, outcome = apply_tool_result_budget(raw, tool_name="personal_assistant_action_tool")
        facts = package_tool_result_facts(budgeted, tool_name="personal_assistant_action_tool", action="team_knowledge_list")
        parsed = json.loads(render_tool_result_for_model(facts).split("\nResult:\n", 1)[1])
        assert outcome is None and not facts.truncated and parsed["knowledgeBases"] == rows
        assert calls == [{"team_id": "team-a", "offset": 0, "limit": 6}]
    finally:
        unbind_actions(service)


def test_knowledge_query_requests_only_its_missing_authorizations(monkeypatch):
    import core.assistant_runtime.actions as actions
    import core.infrastructure.native_runtime as native_runtime
    import tools.personal_assistant_tools as assistant_tools

    monkeypatch.setattr(assistant_tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(actions, "execute_action", lambda *args, **kwargs: {"ok": False, "code": "SCOPE_DENIED"})
    result = json.loads(assistant_tools.personal_assistant_action_tool(
        "team_knowledge_list", {"project_id": "p", "team_id": "team-a"}))
    assert result["requiredScopes"] == ["knowledge:catalog:read", "teams:directory:read"]
    assert "authorization_status" in result["nextStep"] and "authorization_upgrade" in result["nextStep"]
