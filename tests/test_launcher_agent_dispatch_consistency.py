"""One Launcher qualification across its complete directory, discovery and admission."""
import pytest

from core.web.services.external_agent.service import ExternalAgentAccessError
from core.web.services.external_management import agent_directory as readers
from core.web.services.external_management.contracts import AgentDirectoryQuery, AgentDirectoryReadQuery
from core.web.services.external_management.service import ManagementError
from tests.test_external_agent_task_service import FakeRuntime
from tests.test_external_management_agent_directory import agent, env  # noqa: F401
from tests.test_external_management_agent_directory_api import env as api_env  # noqa: F401
from tests.test_local_assistant_tasks import local_service


def pages(env, context, **parameters):
    values = {**AgentDirectoryQuery(**parameters).model_dump(), "dispatch_context": context}
    first = readers.read_agents(env.root, env.directory, AgentDirectoryReadQuery(**values))
    rows, page = list(first["agents"]), first
    while page["nextOffset"] is not None:
        values.update(offset=page["nextOffset"], expected_revision=first["revision"])
        page = readers.read_agents(env.root, env.directory, AgentDirectoryReadQuery(**values))
        rows.extend(page["agents"])
    return first, rows


@pytest.mark.parametrize("enabled,allowed,denied", [
    (False, ["obsolete-id"], []),
    (True, ["obsolete-id"], []),
    (True, ["ordinary", "hidden"], ["second"]),
])
def test_local_directory_matches_discovery_and_real_task_admission(env, enabled, allowed, denied):
    import json

    env.agents.extend([agent("second"), agent("protected", protected=True)])
    env.write()
    env.config.write_text('[launcher.developer_mode]\nenabled=false\n[external_agent_gateway]\n'
        f'enabled={str(enabled).lower()}\nallowed_agent_ids={json.dumps(allowed)}\n'
        f'denied_agent_ids={json.dumps(denied)}\n', encoding="utf-8")
    sources = [env.agents_path, env.teams_path, env.config]
    before = [path.read_bytes() for path in sources]
    projected = [{**row, "conversationIndexKind": env.directory.agent_conversation_index_classification(row)["kind"]}
                 for row in env.agents]
    active = {member["agentId"]: team for team in env.teams if team["status"] == "active"
              for member in team["members"]}
    runtime = FakeRuntime(agents=projected, active_teams=active)
    service, _, _, _ = local_service(env.root, runtime=runtime, denied_agent_ids=denied)
    page, rows = pages(env, "launcher_local")
    expected = {"ordinary", "second"} - set(denied)
    assert {row["agentId"] for row in rows if row["dispatchable"]} == expected
    assert page["dispatchContext"] == "launcher_local"
    assert page["counts"]["dispatchable"] == len(expected)
    discovery = service.list_agents()
    assert discovery["dispatchContext"] == "launcher_local"
    assert {row["agentId"] for row in discovery["agents"]} == expected
    for row in rows:
        kwargs = dict(owner_id="test-owner", adapter_connection_id="test-connection", capabilities=set(),
            agent_id=row["agentId"], task="Run the isolated fixture task", permission_profile="read_only",
            client_request_id="request-" + row["agentId"], title="Fixture", runtime_revision="a" * 40)
        if row["agentId"] in expected:
            assert service.start_task(**kwargs)["taskId"]
        else:
            with pytest.raises(ExternalAgentAccessError):
                service.start_task(**kwargs)
    assert len(runtime.submit_calls) == len(expected)
    assert [path.read_bytes() for path in sources] == before


def test_directory_context_is_bound_into_continuation_revision(env):
    external, _ = pages(env, "external")
    local, _ = pages(env, "launcher_local")
    assert local["revision"] != external["revision"]
    with pytest.raises(ManagementError, match="AGENT_DIRECTORY_REVISION_CONFLICT"):
        pages(env, "launcher_local", offset=6, expected_revision=external["revision"])


def test_default_external_directory_keeps_legacy_wire_shape_and_policy(env):
    env.config.write_text('[launcher.developer_mode]\nenabled=false\n[external_agent_gateway]\n'
        'enabled=true\nallowed_agent_ids=["obsolete-id"]\ndenied_agent_ids=[]\n', encoding="utf-8")
    result = readers.read_agents(env.root, env.directory, AgentDirectoryQuery())
    assert result["counts"]["dispatchable"] == 0
    assert "dispatchContext" not in result


def test_http_directory_context_keeps_independent_read_authorization_and_legacy_wire(api_env, env):
    api_env.native.read_agents = lambda query: readers.read_agents(env.root, env.directory, query)
    url = "/v1/launcher-assistant-management/directory/agents"
    headers = api_env.headers
    denied = api_env.client.get(url, params={"dispatch_context": "launcher_local"}, headers=headers)
    assert denied.status_code == 403
    api_env.upgrade()
    ordinary = api_env.client.get(url, headers=headers)
    local = api_env.client.get(url, params={"dispatch_context": "launcher_local"}, headers=headers)
    assert ordinary.status_code == local.status_code == 200
    assert "dispatchContext" not in ordinary.json()
    assert local.json()["dispatchContext"] == "launcher_local"
    for params in ({"dispatch_context": "arbitrary"},
                   [("dispatch_context", "external"), ("dispatch_context", "launcher_local")]):
        assert api_env.client.get(url, params=params, headers=headers).status_code == 422


def test_native_model_projection_preserves_local_context_and_public_identity():
    import json
    from core.infrastructure.tool_result import package_tool_result_facts, render_tool_result_for_model
    from core.infrastructure.tool_result_budget import apply_tool_result_budget
    from tests.test_external_agent_agent_directory_client import directory_page

    page = {"source": "launcher-assistant", "projectId": "project", "directoryVersion": 1,
            **directory_page(), "dispatchContext": "launcher_local"}
    page["agents"][0]["displayName"] = "Use agent"
    raw, outcome = apply_tool_result_budget(json.dumps(page, ensure_ascii=False),
        tool_name="personal_assistant_action_tool")
    facts = package_tool_result_facts(raw, tool_name="personal_assistant_action_tool", action=None)
    rendered = json.loads(render_tool_result_for_model(facts).split("\nResult:\n", 1)[1])
    assert outcome is None and not facts.truncated and rendered == page


def test_archive_protected_system_worker_remains_dispatchable(env):
    from core.web.services.local_assistant.eligibility import local_assistant_eligibility

    worker = agent("knowledge-steward", roleKey="knowledge_steward", metadata={
        "conversationIndexKind": "personal_agent", "protected": True, "fixedRole": True,
        "systemRole": "knowledge_steward"})
    env.agents[:] = [worker]
    env.teams[:] = []
    env.write()
    _, rows = pages(env, "launcher_local")
    assert rows[0]["dispatchable"] is True
    assert local_assistant_eligibility(worker, active_team_lookup=lambda _aid: None).eligible


@pytest.mark.parametrize("marker", ["personalAssistantProfile", "virtualHumanCompanion", "virtualHumanSelfWake",
    "virtualHumanLifeSteward", "lifeStewardForAgentId", "selfWakeForAgentId", "companion"])
def test_dedicated_session_identity_cannot_become_worker_through_personal_index(env, marker):
    from core.web.services.local_assistant.eligibility import local_assistant_eligibility

    value = "owner" if marker.endswith("AgentId") else True
    worker = agent("dedicated", metadata={"conversationIndexKind": "personal_agent", marker: value})
    env.agents[:] = [worker]
    env.teams[:] = []
    env.write()
    _, rows = pages(env, "launcher_local")
    assert rows[0]["dispatchable"] is False
    assert rows[0]["dispatchReason"] == "unsupported_agent_class"
    runtime = FakeRuntime(agents=[{**worker, "conversationIndexKind": "personal_agent"}])
    service, _, _, _ = local_service(env.root, runtime=runtime)
    assert service.list_agents()["agents"] == []
    with pytest.raises(ExternalAgentAccessError):
        service._require_eligible(runtime.agents[0])
    assert not local_assistant_eligibility(worker, active_team_lookup=lambda _aid: None).eligible


@pytest.mark.anyio
async def test_discovery_scope_reports_the_actual_local_transport(tmp_path):
    from core.assistant_runtime.dispatch import DispatchService

    class Client:
        async def diagnostics(self):
            return {"status": "healthy"}

        async def list_agents(self, **_kwargs):
            return {"agents": [], "count": 0, "dispatchContext": "launcher_local"}
    service = DispatchService(tmp_path / "profile", {"p": tmp_path}, client_factory=lambda *_a, **_kw: Client())
    result = await service.discover("p")
    assert result["scope"] == "launcher_local_dispatchable"
    assert result["dispatchContext"] == "launcher_local"
    assert result["catalogComplete"] is False
