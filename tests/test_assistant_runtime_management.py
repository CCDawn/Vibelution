"""Launcher associations reuse the target durable gate and fixed project registry."""
import asyncio
import json

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchError, DispatchService
from core.external_agent.backend_client import BackendClientError


@pytest.mark.anyio
async def test_archive_governed_action_and_restart_receipt_only(tmp_path):
    writes, reads = [], []
    def factory(root, **kwargs):
        class Client:
            async def diagnostics(self): return {"status": "healthy"}
            async def management_action(self, **values):
                writes.append(values)
                return {"status": "unknown", "action": "agent_archive", "requestId": "archive-1", "verified": False, "reused": False}
            async def management_receipt(self, **values):
                reads.append(values)
                return {"status": "unknown", "action": "agent_archive", "requestId": "archive-1", "verified": False, "reused": True}
        return Client()
    profile, project = tmp_path / "profile", tmp_path / "project"
    service = DispatchService(profile, {"p": project}, client_factory=factory)
    bind_actions(service, asyncio.get_running_loop())
    parameters = {"project_id": "p", "request_id": "archive-1", "agent_id": "agent-a", "expected_config_revision": 3}
    try:
        description = execute_action("describe", {"action": "agent_archive"})
        assert description["governed"] is True and description["scope"] == "agents:archive"
        for _ in range(2):
            denied = await asyncio.to_thread(execute_action, "agent_archive", parameters)
            assert denied["status"] == "approval_required" and writes == []
        result = await asyncio.to_thread(execute_action, "agent_archive", parameters, governed=True)
        assert result["status"] == "unknown" and len(writes) == 1
        await asyncio.to_thread(execute_action, "management_receipt", {
            "project_id": "p", "request_id": "archive-1", "action": "agent_archive"})
        for injected in ({"force": True}, {"purge": True}, {"governed": True}, {"expected_config_revision": True}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "agent_archive", {**parameters, **injected}, governed=True)
    finally:
        unbind_actions(service)
    restarted = DispatchService(profile, {"p": project}, client_factory=factory)
    result = await restarted.management.invoke("p", action="agent_archive", request_id="archive-1",
        parameters={"agent_id": "agent-a", "expected_config_revision": 3})
    assert result["status"] == "unknown" and len(writes) == 1 and len(reads) == 2


@pytest.mark.anyio
async def test_session_pin_governed_closed_action_and_original_receipt_after_restart(tmp_path):
    probe = Probe()
    def factory(root, **kwargs):
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}
            async def management_action(self, **values):
                probe.writes.append(values)
                return receipt(values, reused=False)
            async def management_receipt(self, **values):
                probe.lookups.append(values)
                return receipt(values, reused=True)
        return Client()
    def receipt(values, *, reused):
        return {"status": "completed", "action": values["action"], "requestId": values["request_id"],
            "verified": True, "reused": reused, "session": {"id": "session-a", "agentId": "agent-a",
                "title": "Visible", "pinned": True, "pinnedAtMs": 123, "status": "ready", "archived": False}}
    profile, project = tmp_path / "profile", tmp_path / "project"
    service = DispatchService(profile, {"p": project}, client_factory=factory)
    bind_actions(service, asyncio.get_running_loop())
    parameters = {"project_id": "p", "request_id": "pin-1", "session_id": "session-a", "pinned": True}
    try:
        described = execute_action("describe", {"action": "session_pin"})
        assert described["governed"] is True and described["scope"] == "sessions:pin"
        index = execute_action("index", {"query": "session_pin"})
        assert "session_pin" in json.dumps(index)
        denied = await asyncio.to_thread(execute_action, "session_pin", parameters)
        assert denied["status"] == "approval_required" and probe.writes == []
        result = await asyncio.to_thread(execute_action, "session_pin", parameters, governed=True)
        assert result["session"]["pinned"] is True and result["projectId"] == "p"
        assert probe.writes[0]["parameters"] == {"session_id": "session-a", "pinned": True}
        for injected in ({"agentId": "fake"}, {"actor": "operator"}, {"pinned": "true"}, {"governed": True}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "session_pin", {**parameters, **injected}, governed=True)
        await asyncio.to_thread(execute_action, "management_receipt", {
            "project_id": "p", "action": "session_pin", "request_id": "pin-1"})
    finally:
        unbind_actions(service)
    restarted = DispatchService(profile, {"p": project}, client_factory=factory)
    await restarted.management.invoke("p", action="session_pin", request_id="pin-1",
        parameters={"session_id": "session-a", "pinned": True})
    assert len(probe.writes) == 1
    assert all(row == {"action": "session_pin", "request_id": "pin-1"} for row in probe.lookups)
    with pytest.raises(DispatchError) as conflict:
        await restarted.management.invoke("p", action="session_pin", request_id="pin-1",
            parameters={"session_id": "session-a", "pinned": False})
    assert conflict.value.code == "MANAGEMENT_CONFLICT"


@pytest.mark.anyio
async def test_session_list_action_uses_read_scope_without_intent_and_fits_native_budget(tmp_path, monkeypatch):
    from core.infrastructure.tool_result_budget import apply_tool_result_budget
    from core.infrastructure.tool_result import package_tool_result_facts, render_tool_result_for_model
    import tools.personal_assistant_tools as tools
    import core.infrastructure.native_runtime as runtime
    project_id = "p" * 160
    rows = [{"id": "s" + str(i) + "x" * 158, "agentId": "a" * 128,
        "titlePreview": "😀" * 48, "titleTruncated": True} for i in range(6)]
    observed = []
    def factory(root, **kwargs):
        class Client:
            async def diagnostics(self): return {"status": "healthy"}
            async def management_session_list(self, **query):
                observed.append(query)
                return {"source": "native-session-directory", "untrustedContent": True, "sessions": rows,
                    "offset": 0, "limit": 6, "total": 6, "nextOffset": None}
        return Client()
    service = DispatchService(tmp_path / "profile", {project_id: tmp_path / "target"}, client_factory=factory)
    monkeypatch.setattr(tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    monkeypatch.setattr(runtime, "is_launcher_assistant_process", lambda: True)
    bind_actions(service, asyncio.get_running_loop())
    try:
        description = execute_action("describe", {"action": "session_list"})
        assert "单行" in description["description"] and "控制字符" in description["description"]
        raw = await asyncio.to_thread(tools.personal_assistant_action_tool, "session_list", {"project_id": project_id})
        assert len(raw) <= 3400
        budgeted, outcome = apply_tool_result_budget(raw, tool_name="personal_assistant_action_tool")
        facts = package_tool_result_facts(budgeted, tool_name="personal_assistant_action_tool", action="session_list")
        parsed = json.loads(render_tool_result_for_model(facts).split("\nResult:\n", 1)[1])
        assert outcome is None and not facts.truncated and parsed == json.loads(raw)
        assert parsed["sessions"] == rows and observed == [{"agent_id": "", "query": "", "offset": 0, "limit": 6}]
        assert not (tmp_path / "profile/assistant_management").exists()
        with pytest.raises(DispatchError):
            await service.management.session_list("foreign")
        for injected in ({"limit": 7}, {"include_hidden": True}, {"offset": True}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "session_list", {"project_id": project_id, **injected})
    finally:
        unbind_actions(service)


async def _native_action_tool_result(monkeypatch, *, project_id, query="", tag="", offset=0, limit=50):
    """Exercise the actual Launcher action-tool wrapper and model result path."""
    import tools.personal_assistant_tools as assistant_tools
    import core.infrastructure.native_runtime as native_runtime
    from core.infrastructure.tool_result_budget import apply_tool_result_budget
    from core.infrastructure.tool_result import package_tool_result_facts, render_tool_result_for_model

    monkeypatch.setattr(assistant_tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "session"})
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    raw = await asyncio.to_thread(
        assistant_tools.personal_assistant_action_tool,
        "api_catalog",
        {"project_id": project_id, "query": query, "tag": tag, "offset": offset, "limit": limit},
    )
    budgeted, outcome = apply_tool_result_budget(raw, tool_name="personal_assistant_action_tool")
    facts = package_tool_result_facts(
        budgeted, tool_name="personal_assistant_action_tool", action="api_catalog",
    )
    rendered = render_tool_result_for_model(facts)
    return raw, outcome, facts, rendered


def _documentation_entry(index, *, long_summary=True):
    summary = f"Read registered agent operation {index}. "
    if long_summary:
        summary += "Detailed operator guidance that belongs in api_describe. " * 5
    if index == 0:
        return {
            "operationId": "create_agent",
            "method": "POST",
            "path": "/api/agents",
            "summary": summary,
            "tags": ["agents", "operator"],
            "access": "native_action",
            "executable": True,
            "action": "agent_create",
            "capabilitySubset": True,
            "argumentHelp": {"action": "describe", "parameters": {"action": "agent_create"}},
        }
    return {
        "operationId": f"get_agent_{index:03d}",
        "method": "GET",
        "path": f"/api/v1/agents/{index:03d}/config/details",
        "summary": summary,
        "tags": ["agents", "launcher-assistant"],
        "access": "operator_only",
        "executable": False,
    }


def _documentation_factory(rows, observed):
    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}

            async def management_documentation(self, **query):
                observed.append((root, dict(query)))
                matches = []
                wanted_query = query["query"].casefold()
                wanted_tag = query["tag"].casefold()
                for row in rows:
                    searchable = " ".join(
                        [row["operationId"], row["method"], row["path"], row["summary"], *row["tags"]]
                    ).casefold()
                    if wanted_query and wanted_query not in searchable:
                        continue
                    if wanted_tag and not any(wanted_tag == value.casefold() for value in row["tags"]):
                        continue
                    matches.append(row)
                offset, limit = query["offset"], query["limit"]
                page = matches[offset:offset + limit]
                return {
                    "ok": True,
                    "status": "ok",
                    "observedAt": "2026-10-25T02:00:00Z",
                    "source": "registered-openapi",
                    "untrustedContent": True,
                    "operations": page,
                    "offset": offset,
                    "limit": limit,
                    "total": len(matches),
                    "truncated": offset + len(page) < len(matches),
                }
        return Client()
    return factory


class Probe:
    def __init__(self):
        self.writes, self.lookups = [], []
        self.fail = False

    def factory(self, root, **kwargs):
        owner = self
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}

            async def management_action(self, **values):
                owner.writes.append(values)
                if owner.fail:
                    raise BackendClientError("secret backend detail", code="BACKEND_UNAVAILABLE")
                return {"action": values["action"], "requestId": values["request_id"], "status": "completed",
                        "verified": True, "agent": {"agentId": "ordinary-target"}}

            async def management_receipt(self, **values):
                owner.lookups.append(values)
                return {"action": values["action"], "requestId": values["request_id"], "status": "completed",
                        "verified": True, "agent": {"agentId": "ordinary-target"}}
            async def management_documentation(self, **values):
                owner.lookups.append(values)
                return {"ok": True, "untrustedContent": True, "operations": []}
        return Client()


@pytest.mark.anyio
async def test_session_config_read_has_no_management_intent_or_request_id(tmp_path):
    observed = []
    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self): return {"status": "healthy"}
            async def management_session_config(self, **query):
                observed.append((root, query))
                return {"source": "session_agent_config_revision", "untrustedContent": True, "config": {"sessionId": query["session_id"]}}
        return Client()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"}, client_factory=factory)
    result = await service.management.session_config("p", session_id="session-a")
    assert result["source"] == "session_agent_config_revision" and result["projectId"] == "p"
    with pytest.raises(DispatchError) as denied:
        await service.management.session_config("other", session_id="session-a")
    assert denied.value.code == "PROJECT_NOT_AUTHORIZED"
    assert observed == [(tmp_path / "target", {"session_id": "session-a"})]
    assert not (tmp_path / "profile/assistant_management").exists()


@pytest.mark.anyio
async def test_session_config_compare_read_has_no_intent_or_business_writes(tmp_path):
    observed = []
    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self): return {"status": "healthy"}
            async def management_session_config_compare(self, **query):
                observed.append((root, query))
                return {"source": "session_agent_config_comparison", "sessionId": query["session_id"], "untrustedContent": True}
        return Client()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"}, client_factory=factory)
    result = await service.management.session_config_compare("p", session_id="session-a")
    assert result == {"projectId": "p", "source": "session_agent_config_comparison", "sessionId": "session-a", "untrustedContent": True}
    with pytest.raises(DispatchError) as denied:
        await service.management.session_config_compare("other", session_id="session-a")
    assert denied.value.code == "PROJECT_NOT_AUTHORIZED"
    assert observed == [(tmp_path / "target", {"session_id": "session-a"})]
    assert not (tmp_path / "profile/assistant_management").exists()


@pytest.mark.anyio
async def test_avatar_read_uses_existing_project_call_without_management_intent(tmp_path):
    observed = []
    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self):
                return {'status': 'healthy'}
            async def management_avatar_options(self, **query):
                observed.append((root, query))
                return {'options': [], 'total': 0, 'offset': query['offset'], 'nextOffset': None, 'untrustedContent': True}
        return Client()
    service = DispatchService(tmp_path / 'profile', {'p': tmp_path / 'target'}, client_factory=factory)
    result = await service.management.avatar_options('p', offset=0, limit=3)
    assert result == {'projectId': 'p', 'options': [], 'total': 0, 'offset': 0, 'nextOffset': None, 'untrustedContent': True}
    with pytest.raises(DispatchError):
        await service.management.avatar_options('other', offset=0, limit=3)
    assert observed == [(tmp_path / 'target', {'offset': 0, 'limit': 3})]
    assert not (tmp_path / 'profile' / 'assistant_management').exists()


@pytest.mark.anyio
async def test_model_action_reuses_target_schema_and_no_caller_supplied_subject(tmp_path):
    probe = Probe()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=probe.factory)
    bind_actions(service, asyncio.get_running_loop())
    try:
        params = {"project_id": "p", "request_id": "create-1", "display_name": "Worker", "model_id": "provider/model"}
        result = await asyncio.to_thread(execute_action, "agent_create", params)
        assert result["agent"]["agentId"] == "ordinary-target"
        assert probe.writes[0]["parameters"]["mission"]
        assert "project_id" not in probe.writes[0]["parameters"]
        for injected in ({"subject": "fake"}, {"governed": True}, {"project_root": "/other"}, {"tool_policy": {"allowedTools": ["all"]}}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "agent_create", {**params, **injected})
        assert len(probe.writes) == 1
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_restart_and_unknown_reply_keep_the_original_operation(tmp_path):
    probe = Probe()
    profile, project = tmp_path / "profile", tmp_path / "project"
    first = DispatchService(profile, {"p": project}, client_factory=probe.factory)
    params = {"display_name": "Worker", "model_id": "provider/model", "mission": "private mission"}
    probe.fail = True
    with pytest.raises(DispatchError) as lost:
        await first.management.invoke("p", action="agent_create", request_id="stable", parameters=params)
    assert lost.value.code == "BACKEND_UNAVAILABLE" and "secret" not in str(lost.value)
    restarted = DispatchService(profile, {"p": project}, client_factory=probe.factory)
    result = await restarted.management.invoke("p", action="agent_create", request_id="stable", parameters=params)
    assert result["status"] == "completed" and len(probe.writes) == 1 and len(probe.lookups) == 1
    record = next((profile / "assistant_management").glob("*.json"))
    assert "private mission" not in record.read_text(encoding="utf-8")
    with pytest.raises(DispatchError) as conflict:
        await restarted.management.invoke("p", action="agent_create", request_id="stable", parameters={**params, "display_name": "Other"})
    assert conflict.value.code == "MANAGEMENT_CONFLICT"
    assert len(probe.writes) == 1


@pytest.mark.anyio
async def test_corrupt_association_and_unregistered_project_never_replay(tmp_path):
    probe = Probe()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=probe.factory)
    params = {"display_name": "Worker", "model_id": "provider/model"}
    await service.management.invoke("p", action="agent_create", request_id="stable", parameters=params)
    path = next((tmp_path / "profile/assistant_management").glob("*.json"))
    path.write_text(json.dumps({"schemaVersion": 2}), encoding="utf-8")
    with pytest.raises(DispatchError) as corrupt:
        await service.management.invoke("p", action="agent_create", request_id="stable", parameters=params)
    assert corrupt.value.code == "MANAGEMENT_STATE_INVALID" and len(probe.writes) == 1
    with pytest.raises(DispatchError) as denied:
        await service.management.invoke("unregistered", action="agent_create", request_id="stable", parameters=params)
    assert denied.value.code == "PROJECT_NOT_AUTHORIZED" and len(probe.writes) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("phase,resume,expected_writes", [
    ("materialization_pending", False, 1), ("materialization_pending", True, 1),
    ("materialized", False, 1), ("materialized", True, 2), ("flow_saved", True, 2),
    ("started", True, 1),
])
async def test_team_restart_resumes_only_native_proven_unstarted_original_request(tmp_path, phase, resume, expected_writes):
    probe = Probe()
    original = probe.factory
    def factory(*args, **kwargs):
        client = original(*args, **kwargs)
        async def receipt(**values):
            probe.lookups.append(values)
            return {"action": "team_run", "requestId": "team-1", "status": "unknown", "phase": phase,
                    "resumeAllowed": resume, "teamRun": {"teamId": "team-native", "flowId": "flow-native"}}
        client.management_receipt = receipt
        return client
    profile, project = tmp_path / "profile", tmp_path / "project"
    first = DispatchService(profile, {"p": project}, client_factory=factory)
    params = {"name": "Team", "goal": "original private goal", "template_id": "dev-team"}
    await first.management.invoke("p", action="team_run", request_id="team-1", parameters=params)
    restarted = DispatchService(profile, {"p": project}, client_factory=factory)
    # Querying a receipt is always read-only, even when continuation is safe.
    await restarted.management.receipt("p", action="team_run", request_id="team-1")
    assert len(probe.writes) == 1
    await restarted.management.invoke("p", action="team_run", request_id="team-1", parameters=params)
    assert len(probe.writes) == expected_writes
    if expected_writes == 2:
        assert probe.writes[-1] == {"action": "team_run", "request_id": "team-1", "parameters": params,
                                   "require_existing_subject": True}
    with pytest.raises(DispatchError) as conflict:
        await restarted.management.invoke("p", action="team_run", request_id="team-1", parameters={**params, "goal": "changed"})
    assert conflict.value.code == "MANAGEMENT_CONFLICT"


@pytest.mark.anyio
async def test_team_action_uses_canonical_governance_and_closed_native_schema(tmp_path):
    probe = Probe()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=probe.factory)
    bind_actions(service, asyncio.get_running_loop())
    try:
        params = {"project_id": "p", "request_id": "team-1", "name": "Team", "goal": "Build a team"}
        denied = await asyncio.to_thread(execute_action, "team_run", params)
        assert denied["status"] == "approval_required" and not probe.writes
        result = await asyncio.to_thread(execute_action, "team_run", params, governed=True)
        assert result["status"] == "completed" and len(probe.writes) == 1
        assert probe.writes[0]["parameters"] == {"name": "Team", "goal": "Build a team", "template_id": "dev-team"}
        receipt = await asyncio.to_thread(execute_action, "team_status", {"project_id": "p", "request_id": "team-1"})
        assert receipt["action"] == "team_run" and len(probe.writes) == 1
        for injected in ({"governed": True}, {"run_id": "other"}, {"owner": "fake"}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "team_run", {**params, **injected}, governed=True)
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_documentation_actions_reuse_closed_schema_without_any_management_intent(tmp_path):
    probe = Probe()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"}, client_factory=probe.factory)
    bind_actions(service, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(execute_action, "api_catalog", {"project_id": "p", "query": "agents", "limit": 3})
        assert result["untrustedContent"] is True and result["projectId"] == "p"
        assert probe.lookups == [{"query": "agents", "tag": "", "offset": 0, "limit": 3}] and not probe.writes
        await asyncio.to_thread(execute_action, "api_describe", {"project_id": "p", "operation_id": "real-operation"})
        assert probe.lookups[-1] == {"operation_id": "real-operation"}
        assert not (tmp_path / "profile/assistant_management").exists()
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "api_catalog", {"project_id": "p", "url": "http://other"})
    finally:
        unbind_actions(service)


@pytest.mark.anyio
@pytest.mark.parametrize("count", [20, 50])
async def test_documentation_catalog_pages_fit_native_action_tool_budget_without_loss(tmp_path, monkeypatch, count):
    rows = [_documentation_entry(index) for index in range(count)]
    project_id = "project-" + "x" * 152
    project = tmp_path / "target"
    observed = []
    service = DispatchService(tmp_path / "profile", {project_id: project},
                              client_factory=_documentation_factory(rows, observed))
    bind_actions(service, asyncio.get_running_loop())
    try:
        offset = 0
        seen = []
        requested_offsets = []
        page_count = 0
        while True:
            requested_offsets.append(offset)
            raw, outcome, facts, rendered = await _native_action_tool_result(
                monkeypatch, project_id=project_id, query="agents", tag="agents",
                offset=offset, limit=count,
            )
            assert outcome is None
            assert len(raw) <= 3400
            assert not facts.truncated and "truncated: false" in rendered
            payload = json.loads(raw)
            assert json.loads(rendered.split("\nResult:\n", 1)[1]) == payload
            assert payload["source"] == "registered-openapi"
            assert payload["observedAt"] == "2026-10-25T02:00:00Z"
            assert payload["untrustedContent"] is True
            assert payload["projectId"] == project_id
            assert payload["offset"] == offset
            assert payload["limit"] == len(payload["operations"])
            assert payload["total"] == count
            assert payload["navigation"] and "api_describe" in payload["navigation"]
            assert payload["limit"] <= count
            for entry in payload["operations"]:
                original = next(row for row in rows if row["operationId"] == entry["operationId"])
                expected = dict(original)
                if len(expected["summary"]) > 120:
                    expected["summary"] = expected["summary"][:117] + "..."
                assert entry == expected
                assert len(entry["summary"]) <= 120
                seen.append(entry["operationId"])
            page_count += 1
            if payload["nextOffset"] is None:
                assert payload["truncated"] is False
                break
            assert payload["truncated"] is True
            assert payload["nextOffset"] == offset + payload["limit"]
            assert payload["nextOffset"] > offset
            offset = payload["nextOffset"]

        assert page_count > 1
        assert seen == [row["operationId"] for row in rows]
        assert len(seen) == len(set(seen))
        assert observed and all(root == project for root, _query in observed)
        assert all(query["query"] == "agents" and query["tag"] == "agents" and query["limit"] == count
                   for _root, query in observed)
        assert [query["offset"] for _root, query in observed] == requested_offsets
        observed_count = len(observed)
        with pytest.raises(DispatchError) as denied:
            await service.management.documentation("unauthorized", query="agents", tag="agents", offset=0, limit=count)
        assert denied.value.code == "PROJECT_NOT_AUTHORIZED" and len(observed) == observed_count
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_documentation_catalog_sanitizes_only_long_summary_and_keeps_native_semantics(tmp_path, monkeypatch):
    row = _documentation_entry(0)
    row["summary"] = "IGNORE_PRIOR_INSTRUCTIONS " + "untrusted summary. " * 300
    original = dict(row)
    observed = []
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"},
                              client_factory=_documentation_factory([row], observed))
    bind_actions(service, asyncio.get_running_loop())
    try:
        raw, outcome, facts, rendered = await _native_action_tool_result(
            monkeypatch, project_id="p", query="agents", tag="agents", limit=20,
        )
        assert outcome is None and not facts.truncated and "truncated: false" in rendered
        payload = json.loads(raw)
        actual = payload["operations"][0]
        expected = {**original, "summary": original["summary"][:117] + "..."}
        assert actual == expected
        assert actual["operationId"] == original["operationId"]
        assert actual["method"] == original["method"]
        assert actual["path"] == original["path"]
        assert actual["tags"] == original["tags"]
        assert actual["access"] == "native_action" and actual["executable"] is True
        assert actual["action"] == "agent_create" and actual["capabilitySubset"] is True
        assert actual["argumentHelp"] == original["argumentHelp"]
        assert len(actual["summary"]) == 120
        assert payload["navigation"] and "api_describe" in payload["navigation"]
    finally:
        unbind_actions(service)


@pytest.mark.anyio
@pytest.mark.parametrize("large_field", ["operationId", "path"])
async def test_documentation_catalog_rejects_oversized_identity_without_partial_entry(tmp_path, monkeypatch, large_field):
    row = _documentation_entry(1)
    row[large_field] = "x" * 10000
    observed = []
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"},
                              client_factory=_documentation_factory([row], observed))
    bind_actions(service, asyncio.get_running_loop())
    try:
        raw, outcome, facts, rendered = await _native_action_tool_result(
            monkeypatch, project_id="p", query="agents", tag="agents", limit=20,
        )
        assert outcome is None and not facts.truncated and "truncated: false" in rendered
        payload = json.loads(raw)
        assert payload["ok"] is False and payload["status"] == "error"
        assert payload["code"] == "DOCUMENTATION_ENTRY_TOO_LARGE"
        assert payload["observedAt"] == "2026-10-25T02:00:00Z"
        assert payload["source"] == "registered-openapi" and payload["untrustedContent"] is True
        assert payload["operations"] == [] and payload["limit"] == 0 and payload["total"] == 1
        assert payload["offset"] == 0 and payload["truncated"] is True and payload["nextOffset"] is None
        assert "x" * 200 not in raw and len(raw) < 3400
        if large_field == "path":
            assert payload["operationIdHint"] == row["operationId"]
        else:
            assert "operationIdHint" not in payload
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_documentation_catalog_keeps_prefix_before_oversized_entry_and_fails_at_its_offset(tmp_path, monkeypatch):
    rows = [_documentation_entry(index, long_summary=False) for index in range(4)]
    rows[2]["path"] = "/api/v1/agents/" + "x" * 10000
    observed = []
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"},
                              client_factory=_documentation_factory(rows, observed))
    bind_actions(service, asyncio.get_running_loop())
    try:
        raw, outcome, facts, rendered = await _native_action_tool_result(
            monkeypatch, project_id="p", query="agents", tag="agents", limit=4,
        )
        assert outcome is None and not facts.truncated and "truncated: false" in rendered
        first_page = json.loads(raw)
        assert [row["operationId"] for row in first_page["operations"]] == [
            rows[0]["operationId"], rows[1]["operationId"],
        ]
        assert first_page["offset"] == 0 and first_page["limit"] == 2
        assert first_page["total"] == 4 and first_page["truncated"] is True and first_page["nextOffset"] == 2

        raw, outcome, facts, rendered = await _native_action_tool_result(
            monkeypatch, project_id="p", query="agents", tag="agents", offset=first_page["nextOffset"], limit=4,
        )
        assert outcome is None and not facts.truncated and "truncated: false" in rendered
        blocked_page = json.loads(raw)
        assert blocked_page["code"] == "DOCUMENTATION_ENTRY_TOO_LARGE"
        assert blocked_page["offset"] == 2 and blocked_page["total"] == 4
        assert blocked_page["operations"] == [] and blocked_page["nextOffset"] is None
        assert [query["offset"] for _root, query in observed] == [0, 2]
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_documentation_catalog_error_empty_and_out_of_range_pages_are_bounded(tmp_path, monkeypatch):
    observed = []

    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}

            async def management_documentation(self, **query):
                observed.append((root, dict(query)))
                metadata = {"observedAt": "2026-10-25T02:00:00Z", "source": "registered-openapi",
                            "untrustedContent": True}
                if query["query"] == "failure":
                    return {"ok": False, "status": "error", **metadata, "message": "secret " + "z" * 10000}
                if query["offset"]:
                    return {"ok": True, "status": "ok", **metadata, "operations": [], "offset": query["offset"],
                            "limit": query["limit"], "total": 1, "truncated": False}
                return {"ok": True, "status": "ok", **metadata, "operations": [], "offset": 0,
                        "limit": query["limit"], "total": 0, "truncated": False}
        return Client()

    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"}, client_factory=factory)
    bind_actions(service, asyncio.get_running_loop())
    try:
        for query, offset, expected_total, expected_code in (
            ("", 0, 0, None), ("", 100, 1, None), ("failure", 0, 0, "DOCUMENTATION_READ_FAILED"),
        ):
            raw, outcome, facts, rendered = await _native_action_tool_result(
                monkeypatch, project_id="p", query=query, tag="", offset=offset, limit=50,
            )
            assert outcome is None and not facts.truncated and "truncated: false" in rendered
            payload = json.loads(raw)
            assert len(raw) < 3400
            assert payload["observedAt"] == "2026-10-25T02:00:00Z"
            assert payload["source"] == "registered-openapi" and payload["untrustedContent"] is True
            assert payload["operations"] == [] and payload["limit"] == 0 and payload["total"] == expected_total
            assert payload["offset"] == offset and payload["nextOffset"] is None
            if expected_code is None:
                assert payload["ok"] is True and payload["truncated"] is False
            else:
                assert payload["ok"] is False and payload["code"] == expected_code
                assert "secret" not in raw and "z" * 200 not in raw
        assert [query["offset"] for _root, query in observed] == [0, 100, 0]
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_documentation_describe_pages_finite_dto_without_mutating_it_or_extending_sdk(tmp_path):
    original = {
        "ok": True, "status": "ok", "observedAt": "2026-10-25T02:00:00Z",
        "source": "registered-openapi", "untrustedContent": True, "operationId": "known-operation",
        "operation": {**_documentation_entry(1), "operationId": "known-operation"}, "description": "complete describe body " * 100,
        "parameters": [{"name": "agent_id", "in": "path", "required": True}],
        "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
        "responses": {"200": {"description": "Complete response"}}, "components": {"schemas": {"Agent": {"type": "object"}}},
        "truncated": True, "omittedSchemas": ["LargeSchema"],
    }
    seen = []

    def factory(root, **_kwargs):
        class Client:
            async def diagnostics(self):
                return {"status": "healthy"}

            async def management_documentation(self, **query):
                seen.append((root, query))
                return original
        return Client()

    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"}, client_factory=factory)
    result = await service.management.documentation("p", operation_id="known-operation")
    assert result["nodeType"] == "object" and result["upstreamTruncated"] is True
    assert any(row["pointer"] == "/components" for row in result["items"])
    leaf = await service.management.documentation("p", operation_id="known-operation",
        document_pointer="/requestBody/content/application~1json/schema/type", offset=0, limit=32,
        expected_document_digest=result["documentDigest"])
    assert leaf["value"] == "object" and leaf["documentDigest"] == result["documentDigest"]
    assert original["requestBody"]["content"]["application/json"]["schema"]["type"] == "object"
    assert seen == [(tmp_path / "target", {"operation_id": "known-operation"})] * 2
    assert not (tmp_path / "profile/assistant_management").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("count", [20, 50])
async def test_unprojected_closed_catalog_shape_reproduces_native_truncation(tmp_path, monkeypatch, count):
    """RED baseline: the full SDK page exceeds the native result path without projection."""
    rows = [_documentation_entry(index) for index in range(count)]
    observed = []
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"},
                              client_factory=_documentation_factory(rows, observed))

    async def unprojected_documentation(project_id, **parameters):
        result = await service.management._call(
            project_id, lambda client: client.management_documentation(**parameters),
        )
        return {**result, "projectId": project_id}

    service.management.documentation = unprojected_documentation
    bind_actions(service, asyncio.get_running_loop())
    try:
        raw, _outcome, facts, rendered = await _native_action_tool_result(
            monkeypatch, project_id="p", query="agents", tag="agents", limit=count,
        )
        assert len(raw) > 4000
        assert facts.truncated and "truncated: true" in rendered
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_documentation_node_locals_are_stripped_before_sdk_and_invalid_locals_never_call_it(tmp_path):
    seen = []
    document = {"ok": True, "status": "ok", "source": "registered-openapi", "untrustedContent": True,
                "observedAt": "t1", "operation": {"operationId": "known"}, "description": "Stored factual text"}
    def factory(root, **kwargs):
        class Client:
            async def diagnostics(self): return {"status": "healthy"}
            async def management_documentation(self, **query):
                seen.append(query)
                return document
        return Client()
    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "target"}, client_factory=factory)
    bind_actions(service, asyncio.get_running_loop())
    try:
        first = await asyncio.to_thread(execute_action, "api_describe", {"project_id": "p", "operation_id": "known"})
        leaf = await asyncio.to_thread(execute_action, "api_describe", {"project_id": "p", "operation_id": "known",
            "document_pointer": "/description", "offset": 7, "limit": 4, "expected_document_digest": first["documentDigest"]})
        assert leaf["value"] == "fact" and leaf["offset"] == 7 and leaf["limit"] == 4
        assert seen == [{"operation_id": "known"}] * 2
        for injected in ({"document_pointer": "not-pointer"}, {"document_pointer": "/bad~2"}, {"offset": True},
                         {"offset": -1}, {"limit": 0}, {"limit": 513}, {"expected_document_digest": "bad"},
                         {"url": "https://not-allowed"}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "api_describe", {"project_id": "p", "operation_id": "known", **injected})
        with pytest.raises(DispatchError) as denied:
            await service.management.documentation("foreign", operation_id="known")
        assert denied.value.code == "PROJECT_NOT_AUTHORIZED"
        assert len(seen) == 2 and not (tmp_path / "profile/assistant_management").exists()
    finally:
        unbind_actions(service)
