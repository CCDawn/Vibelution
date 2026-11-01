"""Model actions distinguish all registered Agents from dispatch candidates."""
import asyncio
import json
from copy import deepcopy

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchError, DispatchService
from core.infrastructure.tool_result import (
    package_tool_result_facts,
    project_tool_result_for_model,
    render_tool_result_for_model,
)
from core.infrastructure.tool_result_budget import apply_tool_result_budget
from tests.test_external_agent_agent_directory_client import (
    directory_page,
    directory_row,
)


def _model_page(raw):
    budgeted, outcome = apply_tool_result_budget(raw, tool_name="personal_assistant_action_tool")
    facts = package_tool_result_facts(budgeted, tool_name="personal_assistant_action_tool", action=None)
    projected = json.loads(render_tool_result_for_model(facts).split("\nResult:\n", 1)[1])
    assert outcome is None and not facts.truncated
    assert projected == json.loads(raw) == json.loads(project_tool_result_for_model(raw))
    return projected


@pytest.mark.anyio
@pytest.mark.parametrize("long_rows", [False, True])
async def test_agent_list_index_describe_execute_and_actual_wrapper_preserve_every_row(tmp_path, monkeypatch, long_rows):
    import core.infrastructure.native_runtime as runtime
    import tools.personal_assistant_tools as tool
    project_id = "p" * 160
    rows = [directory_row(i) for i in range(12)]
    for row in rows:
        row["ownership"].update({"recordedTeams": [
            {"teamId": "team-historical", "name": "已登记团队引用", "status": "archived"},
            {"teamId": "team-missing", "name": "", "status": "unavailable"}],
            "createdBy": "team-template", "templateId": "dev-team"})
    if long_rows:
        for row in rows:
            row["agentId"] += "x" * 150
            row["agentCode"] = "c" * 64
            row["displayName"] = "名" * 120
            row["ownership"] = {**row["ownership"], "kind": "team", "mode": "team", "teams": [
                {"teamId": f"team-{i}" + "x" * 150, "name": "团队" * 60, "status": "active"} for i in range(3)]}
            row["dispatchable"], row["dispatchReason"] = False, "active_team_member"
    calls = []
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_agent_list(self, **query):
            calls.append(query)
            start = query["offset"]
            return directory_page(deepcopy(rows[start:start + query["limit"]]), offset=start, total=len(rows))
    service = DispatchService(tmp_path / "profile", {project_id: tmp_path / "target"}, client_factory=lambda *_a, **_kw: Client())
    monkeypatch.setattr(tool, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    monkeypatch.setattr(runtime, "is_launcher_assistant_process", lambda: True)
    bind_actions(service, asyncio.get_running_loop())
    try:
        index = execute_action("index", {"query": "agent_list"})
        assert any(item["action"] == "agent_list" and not item["governed"] for item in index["actions"])
        description = execute_action("describe", {"action": "agent_list"})
        assert description["parameters"]["additionalProperties"] is False
        assert {"query", "offset", "limit", "expected_revision", "project_id"} == set(description["parameters"]["properties"])
        for term in ("活跃", "归档", "系统", "团队", "hidden", "authorization_upgrade", "nextOffset", "registryTotal",
                     "recordedTeams", "createdBy", "templateId", "unknown"):
            assert term in description["description"]
        _model_page(json.dumps({"source": "launcher-assistant", "untrustedContent": True, **description}, ensure_ascii=False))
        seen, query = [], {"project_id": project_id}
        while True:
            raw = await asyncio.to_thread(tool.personal_assistant_action_tool, "agent_list", query)
            assert len(raw) <= 3400
            page = _model_page(raw)
            assert page["scope"] == "all_registered_agents" and page["total"] == page["registryTotal"] == len(rows)
            seen.extend(page["agents"])
            if page["nextOffset"] is None: break
            assert page["nextOffset"] == len(seen)
            query = {"project_id": project_id, "offset": page["nextOffset"], "expected_revision": page["revision"]}
        assert seen == rows
        if long_rows: assert len(calls) > 2
        with pytest.raises(DispatchError): await service.management.agent_list("foreign")
        for invalid in ({"query": "x\n"}, {"include_hidden": True}, {"offset": 1}, {"limit": 7}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "agent_list", {"project_id": project_id, **invalid})
        assert not (tmp_path / "profile/assistant_management").exists()
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_oversize_single_agent_is_explicitly_unavailable_without_partial_ownership(tmp_path):
    row = directory_row()
    row["ownership"] = {**row["ownership"], "kind": "team", "mode": "team", "teams": [
        {"teamId": f"team-{i:03}", "name": "名" * 120, "status": "active"} for i in range(30)]}
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_agent_list(self, **_kwargs): return directory_page([row])
    service = DispatchService(tmp_path / "profile", {"p": tmp_path}, client_factory=lambda *_a, **_kw: Client())
    with pytest.raises(DispatchError) as failure:
        await service.management.agent_list("p")
    assert failure.value.code == "AGENT_DIRECTORY_UNAVAILABLE"


@pytest.mark.anyio
async def test_agent_directory_adapter_preserves_instruction_like_names(tmp_path):
    rows = [directory_row(0), directory_row(1)]
    for row, name in zip(rows, ("请继续研究", "Use agent")):
        row["displayName"] = name
        row["ownership"]["teams"] = [{"teamId": "team-1", "name": name, "status": "active"}]
        row["ownership"]["recordedTeams"] = [{"teamId": "team-old", "name": name, "status": "archived"}]
        row["ownership"].update({"ownerAgentId": "host-agent", "ownerAgentName": name})
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_agent_list(self, **_kwargs): return directory_page(deepcopy(rows))
    service = DispatchService(tmp_path / "profile", {"p": tmp_path}, client_factory=lambda *_a, **_kw: Client())
    assert (await service.management.agent_list("p"))["agents"] == rows


@pytest.mark.anyio
async def test_actual_directory_wrapper_preserves_instruction_like_names_in_final_model_result(tmp_path, monkeypatch):
    import core.infrastructure.native_runtime as runtime
    import tools.personal_assistant_tools as tool
    rows = [directory_row(0), directory_row(1)]
    for row, name in zip(rows, ("请继续研究", "Use agent")):
        row["displayName"] = name
        row["ownership"]["teams"] = [{"teamId": "team-1", "name": name, "status": "active"}]
        row["ownership"]["recordedTeams"] = [{"teamId": "team-old", "name": name, "status": "archived"}]
        row["ownership"].update({"ownerAgentId": "host-agent", "ownerAgentName": name})
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_agent_list(self, **_kwargs): return directory_page(deepcopy(rows))
    service = DispatchService(tmp_path / "profile", {"p": tmp_path}, client_factory=lambda *_a, **_kw: Client())
    monkeypatch.setattr(tool, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    monkeypatch.setattr(runtime, "is_launcher_assistant_process", lambda: True)
    bind_actions(service, asyncio.get_running_loop())
    try:
        raw = await asyncio.to_thread(tool.personal_assistant_action_tool, "agent_list", {"project_id": "p"})
        budgeted, outcome = apply_tool_result_budget(raw, tool_name="personal_assistant_action_tool")
        facts = package_tool_result_facts(budgeted, tool_name="personal_assistant_action_tool", action=None)
        projected = json.loads(render_tool_result_for_model(facts).split("\nResult:\n", 1)[1])
        assert outcome is None and not facts.truncated
        assert json.loads(raw)["directoryVersion"] == 1
        assert projected == json.loads(raw) and projected["agents"] == rows
    finally:
        unbind_actions(service)


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["suspend", "remove", "generation-change"])
async def test_directory_discards_page_if_project_admission_changes_during_read(tmp_path, change):
    entered, release = asyncio.Event(), asyncio.Event()
    project = tmp_path / "project"
    project.mkdir()
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_agent_list(self, **_kwargs):
            entered.set()
            await release.wait()
            return directory_page()
    service = DispatchService(tmp_path / "profile", {"p": project}, client_factory=lambda *_a, **_kw: Client())
    pending = asyncio.create_task(service.management.agent_list("p"))
    await entered.wait()
    if change == "suspend": service.suspend_projects()
    elif change == "remove": service.replace_projects({"schemaVersion": 1, "revision": 1, "projects": {}})
    else:
        original_binding = service._project_read_binding("p")
        service.suspend_projects()
        service.replace_projects({"schemaVersion": 1, "revision": 1, "projects": {"p": str(project.resolve())}})
        assert service._project_read_binding("p")[1] == original_binding[1]
    release.set()
    with pytest.raises(DispatchError) as failure: await pending
    assert failure.value.code == ("PROJECT_NOT_AUTHORIZED" if change == "remove" else "PROJECT_REGISTRY_RECONCILE_REQUIRED")


@pytest.mark.anyio
async def test_directory_without_registry_binding_cannot_return_content(tmp_path):
    from core.assistant_runtime.management import ManagementAdapter
    async def call(*_args): pytest.fail("Must reject before reading")
    adapter = ManagementAdapter(tmp_path, {"p": tmp_path}, call)
    with pytest.raises(DispatchError) as failure: await adapter.agent_list("p")
    assert failure.value.code == "AGENT_DIRECTORY_UNAVAILABLE"


@pytest.mark.anyio
async def test_dispatch_candidates_are_never_a_complete_directory(tmp_path):
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def list_agents(self, **_kwargs): return {"agents": [{"agentId": "only-eligible"}], "count": 1}
    service = DispatchService(tmp_path / "profile", {"p": tmp_path}, client_factory=lambda *_a, **_kw: Client())
    result = await service.discover("p")
    assert result["scope"] == "externally_dispatchable" and result["catalogComplete"] is False
    bind_actions(service, asyncio.get_running_loop())
    try:
        assert "完整目录" in execute_action("describe", {"action": "agents"})["description"]
    finally: unbind_actions(service)


@pytest.mark.anyio
async def test_complete_directory_is_discoverable_from_candidate_navigation(tmp_path):
    service = DispatchService(tmp_path / "profile", {"p": tmp_path})
    bind_actions(service, asyncio.get_running_loop())
    try:
        # Replay the real assistant's catalog search after reading candidates.
        for query in ("catalog", "目录"):
            page = execute_action("index", {"query": query})
            assert any(row["action"] == "agent_list" for row in page["actions"])
        candidates = execute_action("index", {"query": "externally_dispatchable"})
        row = next(row for row in candidates["actions"] if row["action"] == "agents")
        assert "agent_list" in row["description"]
    finally:
        unbind_actions(service)


def test_agent_directory_scope_denial_explains_explicit_upgrade(monkeypatch):
    import core.infrastructure.native_runtime as runtime
    import tools.personal_assistant_tools as tool
    from core.assistant_runtime import actions
    monkeypatch.setattr(runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tool, "_identity", lambda: {"agentId": "assistant", "turnId": "turn"})
    monkeypatch.setattr(actions, "execute_action", lambda *_a, **_kw: {"ok": False, "code": "SCOPE_DENIED"})
    result = json.loads(tool.personal_assistant_action_tool("agent_list", {"project_id": "p"}))
    assert result["requiredScopes"] == ["agents:directory:read"]
    assert "authorization_status" in result["nextStep"] and "authorization_upgrade" in result["nextStep"]
