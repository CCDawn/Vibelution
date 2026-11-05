"""Launcher model actions use only registered project IDs and stable task keys."""

import asyncio
import json

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchError


@pytest.fixture(autouse=True)
def isolated_action_result_budget(monkeypatch):
    from core.infrastructure import tool_result_budget
    monkeypatch.setattr(tool_result_budget, "_TOOL_RESULT_BUDGETS", dict(tool_result_budget._TOOL_RESULT_BUDGETS))


class Dispatch:
    projects = {"test-project": "/private/source/path"}

    def project_ids(self):
        return list(self.projects)

    async def available_projects(self, **_kwargs):
        return {"projects": [{"projectId": key} for key in self.projects], "skippedProjects": []}

    async def discover(self, project_id):
        return {"agents": [{"agentId": "agent-1"}], "projectId": project_id}

    async def dispatch(self, project_id, **kwargs):
        return {"dispatchId": kwargs["dispatch_id"], "taskId": "native-1"}

    async def dispatch_from_source(self, project_id, **kwargs):
        return await self.dispatch(project_id, **kwargs)


@pytest.mark.parametrize(("action", "scope"), [("task_list", "tasks:read"), ("source_read", "source:read"), ("source_search", "source:read")])
def test_denied_requested_query_explains_native_approval_without_granting_it(monkeypatch, action, scope):
    from core.infrastructure import native_runtime
    from core.assistant_runtime import actions
    from tools import personal_assistant_tools as tool

    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tool, "_identity", lambda: {"agentId": "assistant", "turnId": "turn"})
    monkeypatch.setattr(actions, "execute_action", lambda *_args, **_kwargs: {"ok": False, "code": "SCOPE_DENIED"})
    result = json.loads(tool.personal_assistant_action_tool(action, {"project_id": "project"}))
    assert result["code"] == "SCOPE_DENIED" and result["requiredScope"] == scope
    assert result["requiredScopes"] == [scope]
    assert "authorization_status" in result["nextStep"] and "personal_assistant_manage_tool" in result["nextStep"]
    assert "不自行宣称已授权" in result["nextStep"]


def test_denied_parameter_query_names_both_required_read_scopes(monkeypatch):
    from core.infrastructure import native_runtime
    from core.assistant_runtime import actions
    from tools import personal_assistant_tools as tool

    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tool, "_identity", lambda: {"agentId": "assistant", "turnId": "turn"})
    monkeypatch.setattr(actions, "execute_action", lambda *_args, **_kwargs: {"ok": False, "code": "SCOPE_DENIED"})
    result = json.loads(tool.personal_assistant_action_tool("session_parameters_get", {"project_id": "project"}))
    assert result["requiredScopes"] == ["sessions:parameters:read", "sessions:read"]
    assert "requiredScope" not in result and "缺失的权限" in result["nextStep"]


def _through_native_model_budget(payload):
    from core.infrastructure.tool_result_budget import apply_tool_result_budget, get_tool_result_budget
    from core.infrastructure.tool_result import package_tool_result_facts, render_tool_result_for_model
    from core.assistant_runtime.actions import configure_action_result_budget
    configure_action_result_budget()
    budget = get_tool_result_budget("personal_assistant_action_tool").packaging_max_chars
    raw = json.dumps({"source": "launcher-assistant", "untrustedContent": True, **payload}, ensure_ascii=False)
    result, outcome = apply_tool_result_budget(raw, tool_name="personal_assistant_action_tool")
    facts = package_tool_result_facts(result, tool_name="personal_assistant_action_tool", action="index", max_chars=budget)
    rendered = render_tool_result_for_model(facts, max_chars=budget)
    return raw, outcome, facts, rendered


def _assert_only_title_annotations_removed(original, projected):
    """Generic structural diff; deliberately does not traverse by schema keywords."""
    if isinstance(original, dict):
        assert isinstance(projected, dict) and projected.keys() <= original.keys()
        for key, value in original.items():
            if key not in projected:
                assert key == "title" and isinstance(value, str)
            else:
                _assert_only_title_annotations_removed(value, projected[key])
    elif isinstance(original, list):
        assert isinstance(projected, list) and len(original) == len(projected)
        for left, right in zip(original, projected):
            _assert_only_title_annotations_removed(left, right)
    else:
        assert type(original) is type(projected) and original == projected


def test_schema_title_compaction_preserves_business_keys_and_literal_data():
    from copy import deepcopy
    from core.assistant_runtime.actions import _schema_without_titles
    schema = {"title": "Root display", "type": "object", "required": ["title"],
        "properties": {"title": {"title": "Business title label", "type": "string", "maxLength": 120},
                       "nested": {"items": {"title": "Item label", "anyOf": [{"title": "Alt", "type": "integer"}]}}},
        "$defs": {"title": {"title": "Definition label", "type": "string"}},
        "default": {"title": "literal default", "nested": {"title": "literal nested"}},
        "examples": [{"title": "literal example"}], "x-extension": {"title": "unknown data"}}
    before = deepcopy(schema)
    compact = _schema_without_titles(schema)
    _assert_only_title_annotations_removed(schema, compact)
    assert compact["properties"]["title"] == {"type": "string", "maxLength": 120}
    assert compact["$defs"]["title"] == {"type": "string"}
    assert compact["default"] == schema["default"] and compact["examples"] == schema["examples"]
    assert compact["x-extension"] == schema["x-extension"]
    assert compact["required"] == ["title"] and schema == before


def test_management_navigation_builds_each_source_contract_registry_once_per_call(monkeypatch):
    from core.assistant_runtime import actions
    from core.web.services.external_management import contracts as source
    calls = []
    for name in ("contracts", "pa_managed_write_contracts"):
        original = getattr(source, name)
        def counted(original=original, name=name):
            calls.append(name)
            return original()
        monkeypatch.setattr(source, name, counted)

    first = actions._management_contracts()
    assert calls == ["contracts", "pa_managed_write_contracts"]
    calls.clear()
    second = actions._management_contracts()
    assert calls == ["contracts", "pa_managed_write_contracts"]
    assert {name: item[1] for name, item in first.items()} == {name: item[1] for name, item in second.items()}


@pytest.mark.anyio
async def test_launcher_index_remains_complete_json_through_native_budget():
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        page = await asyncio.to_thread(execute_action, "index", {})
        raw, outcome, facts, rendered = _through_native_model_budget(page)
        assert not facts.truncated, f"{len(page['actions'])} actions serialized to {len(raw)} chars"
        assert outcome is None and "truncated: false" in rendered
        assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_index_pages_cover_every_existing_contract_without_duplicate_or_schema_loss():
    from core.assistant_runtime import actions, local_actions
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        expected = set(actions._SCHEMAS) | set(actions._documentation_contracts()) | set(actions._project_read_contracts())
        expected |= set(local_actions.contracts()) | set(actions._management_contracts())
        raw_contracts = {key: cls.model_json_schema() for key, cls in {
            **actions._SCHEMAS, **actions._documentation_contracts(), **actions._project_read_contracts()}.items()}
        raw_contracts.update({key: value["parameters"] for key, value in local_actions.contracts().items()})
        raw_contracts.update({key: value[1]["parameters"] for key, value in actions._management_contracts().items()})
        names, offset = [], 0
        while True:
            page = await asyncio.to_thread(execute_action, "index", {"offset": offset, "limit": 5})
            assert page["total"] == len(expected) and page["offset"] == offset
            assert len(page["actions"]) <= 5
            for row in page["actions"]:
                assert set(row) <= {"action", "description", "governed", "available", "unavailableReason", "scope"}
                assert "parameters" not in row and type(row["governed"]) is bool and type(row["available"]) is bool
                names.append(row["action"])
                description = await asyncio.to_thread(execute_action, "describe", {"action": row["action"]})
                assert description["parameters"]["additionalProperties"] is False
                _assert_only_title_annotations_removed(raw_contracts[row["action"]], description["parameters"])
                raw_description, outcome, facts, rendered = _through_native_model_budget(description)
                assert outcome is None and not facts.truncated and "truncated: false" in rendered, row["action"]
                assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw_description)
                assert row["governed"] == description.get("governed", False)
                assert row["available"] == description.get("available", True)
                assert row["unavailableReason"] == description.get("unavailableReason", "")
            raw, outcome, facts, rendered = _through_native_model_budget(page)
            assert outcome is None and not facts.truncated and "truncated: false" in rendered
            assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
            if page["nextOffset"] is None:
                break
            assert page["nextOffset"] == offset + len(page["actions"])
            offset = page["nextOffset"]
        assert len(names) == len(set(names)) and set(names) == expected and names == sorted(names)
        # Every permitted full-size window, not just default page boundaries,
        # must survive both native packaging and the model-visible facts header.
        for offset in range(len(names) + 1):
            page = await asyncio.to_thread(execute_action, "index", {"offset": offset, "limit": 12})
            raw, outcome, facts, rendered = _through_native_model_budget(page)
            assert outcome is None and not facts.truncated and "truncated: false" in rendered, (offset, len(raw))
            assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        beyond = await asyncio.to_thread(execute_action, "index", {"offset": 999999})
        assert beyond["actions"] == [] and beyond["nextOffset"] is None and beyond["total"] == len(expected)
        full_dispatch = await asyncio.to_thread(execute_action, "describe", {"action": "dispatch"})
        assert full_dispatch["description"] == actions._HELP["dispatch"]
        _assert_only_title_annotations_removed(actions.Dispatch.model_json_schema(), full_dispatch["parameters"])
        assert full_dispatch["parameters"]["properties"]["title"]["maxLength"] == 120
        valid = {"project_id": "p", "agent_id": "a", "dispatch_id": "d", "task": "literal", "title": "kept business field"}
        assert actions.Dispatch.model_validate(valid).title == "kept business field"
        with pytest.raises(ValueError):
            actions.Dispatch.model_validate({**valid, "title": "x" * 121})
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_index_query_search_and_unavailable_reasons_remain_visible():
    from core.assistant_runtime import local_actions
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        async def matching_actions(query):
            names, offset = set(), 0
            while offset is not None:
                page = await asyncio.to_thread(execute_action, "index", {"query": query, "offset": offset})
                names.update(row["action"] for row in page["actions"])
                offset = page["nextOffset"]
            return names

        assert await matching_actions("SESSION") >= {"session_get", "session_config_get"}
        assert "session_config_get" in await matching_actions("历史")
        for name in ("provider_remove", "model_remove"):
            page = await asyncio.to_thread(execute_action, "index", {"query": name})
            row = next(r for r in page["actions"] if r["action"] == name)
            assert row["available"] is False
            assert row["unavailableReason"] == local_actions.contracts()[name]["unavailableReason"]
            _raw, _outcome, facts, rendered = _through_native_model_budget(page)
            assert not facts.truncated and row["unavailableReason"] in rendered
        none = await asyncio.to_thread(execute_action, "index", {"query": "definitely_unknown_action"})
        assert none["total"] == 0 and none["actions"] == [] and none["nextOffset"] is None
        schema = await asyncio.to_thread(execute_action, "describe", {"action": "index"})
        assert schema["parameters"]["additionalProperties"] is False
        assert set(schema["parameters"]["properties"]) == {"query", "offset", "limit"}
        assert schema["parameters"]["properties"]["limit"]["maximum"] == 12
        for unknown in ("agent_sessions", "workspace_list", "sessions", "nonexistent"):
            with pytest.raises(ValueError, match="Unknown Launcher action"):
                await asyncio.to_thread(execute_action, "describe", {"action": unknown})
            with pytest.raises(ValueError, match="Unknown Launcher action"):
                await asyncio.to_thread(execute_action, unknown, {})
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
@pytest.mark.parametrize("parameters", [{"query": True}, {"query": None}, {"query": "x" * 65},
    {"offset": -1}, {"offset": True}, {"offset": "1"}, {"offset": 1_000_001},
    {"limit": 0}, {"limit": 13}, {"limit": False}, {"limit": "12"}, {"url": "http://unused"}])
async def test_index_query_is_strict_bounded_and_closed(parameters):
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        with pytest.raises(ValueError, match="Index parameters"):
            await asyncio.to_thread(execute_action, "index", parameters)
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_avatar_catalog_action_uses_registered_project_and_strict_native_query():
    from types import SimpleNamespace
    calls = []
    async def avatar_options(project_id, **query):
        calls.append((project_id, query))
        return {'options': [], 'total': 0, 'offset': query.get('offset', 0), 'nextOffset': None, 'untrustedContent': True}
    dispatch = Dispatch(); dispatch.management = SimpleNamespace(avatar_options=avatar_options)
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        index = await asyncio.to_thread(execute_action, 'index', {"query": "avatar_options"})
        assert 'avatar_options' in {row['action'] for row in index['actions']}
        contract = await asyncio.to_thread(execute_action, 'describe', {'action': 'avatar_options'})
        assert contract['parameters']['additionalProperties'] is False
        assert await asyncio.to_thread(execute_action, 'avatar_options', {'project_id': 'test-project', 'offset': 2, 'limit': 3}) == {
            'options': [], 'total': 0, 'offset': 2, 'nextOffset': None, 'untrustedContent': True}
        for patch in ({'project_id': 'other'}, {'offset': True}, {'limit': 31}, {'path': '/private'}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, 'avatar_options', {'project_id': 'test-project', **patch})
        assert calls == [('test-project', {'offset': 2, 'limit': 3})]
    finally:
        unbind_actions(dispatch)


def test_actions_default_deny_without_owner_loop():
    with pytest.raises(ValueError, match="not running"):
        execute_action("projects", {})


@pytest.mark.anyio
async def test_session_metadata_action_requires_registered_project_and_closed_query():
    from types import SimpleNamespace
    observed = []

    async def session(project_id, **parameters):
        observed.append((project_id, parameters))
        return {"session": {"id": parameters["session_id"]}, "untrustedContent": True}

    dispatch = Dispatch()
    dispatch.management = SimpleNamespace(session=session)
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        schema = await asyncio.to_thread(execute_action, "describe", {"action": "session_get"})
        assert schema["parameters"]["additionalProperties"] is False
        result = await asyncio.to_thread(execute_action, "session_get", {
            "project_id": "test-project", "session_id": "session-1"})
        assert result["session"]["id"] == "session-1" and result["untrustedContent"] is True
        for parameters in (
            {"project_id": "unregistered", "session_id": "session-1"},
            {"project_id": "test-project", "session_id": "../session-1"},
            {"project_id": "test-project", "session_id": "session-1", "project_root": "/arbitrary"},
        ):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "session_get", parameters)
        assert observed == [("test-project", {"session_id": "session-1"})]
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_session_config_is_neutral_closed_read_with_explicit_historical_description():
    from types import SimpleNamespace
    from core.web.services.external_management.contracts import ACTION_MODELS
    observed = []
    async def session_config(project_id, **parameters):
        observed.append((project_id, parameters))
        return {"source": "session_agent_config_revision", "untrustedContent": True,
                "config": {"sessionId": parameters["session_id"]}}
    dispatch = Dispatch()
    dispatch.management = SimpleNamespace(session_config=session_config)
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        index = await asyncio.to_thread(execute_action, "index", {"query": "session_config_get"})
        assert "session_config_get" in {r["action"] for r in index["actions"]}
        assert "session_config_get" not in ACTION_MODELS
        schema = await asyncio.to_thread(execute_action, "describe", {"action": "session_config_get"})
        assert schema["parameters"]["additionalProperties"] is False
        assert "历史" in schema["description"] and "active Turn" in schema["description"] and "不返回预算" in schema["description"]
        result = await asyncio.to_thread(execute_action, "session_config_get", {"project_id": "test-project", "session_id": "session-1"})
        assert result["source"] == "session_agent_config_revision"
        for patch in ({"project_id": "other"}, {"session_id": "../session"}, {"effective": True}, {"agent_id": "other"}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "session_config_get", {"project_id": "test-project", "session_id": "session-1", **patch})
        assert observed == [("test-project", {"session_id": "session-1"})]
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_session_config_compare_action_preserves_read_scope_and_explicit_comparison_contract():
    from types import SimpleNamespace
    from core.web.services.external_management.contracts import ACTION_MODELS, SCOPES
    calls = []
    async def compare(project_id, **parameters):
        calls.append((project_id, parameters))
        return {"source": "session_agent_config_comparison", "sessionId": parameters["session_id"], "sameRevision": False}
    dispatch = Dispatch()
    dispatch.management = SimpleNamespace(session_config_compare=compare)
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        page = await asyncio.to_thread(execute_action, "index", {"query": "session_config_compare"})
        assert {r["action"] for r in page["actions"]} >= {"session_config_compare", "session_config_get"}
        assert next(r for r in page["actions"] if r["action"] == "session_config_compare")["governed"] is False
        assert "session_config_compare" not in ACTION_MODELS and "sessions:read" in SCOPES
        assert "legacy:receipts:read" in SCOPES
        description = await asyncio.to_thread(execute_action, "describe", {"action": "session_config_compare"})
        assert description["parameters"]["additionalProperties"] is False
        assert set(description["parameters"]["properties"]) == {"session_id", "project_id"}
        assert "同一 Agent 当前 compiled" in description["description"] and "不根据时间戳" in description["description"]
        history = await asyncio.to_thread(execute_action, "describe", {"action": "session_config_get"})
        assert "不能据时间戳" in history["description"] and "session_config_compare" in history["description"]
        raw, outcome, facts, rendered = _through_native_model_budget(description)
        assert outcome is None and not facts.truncated and "truncated: false" in rendered
        assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        result = await asyncio.to_thread(execute_action, "session_config_compare", {"project_id": "test-project", "session_id": "session-1"})
        assert result["source"] == "session_agent_config_comparison"
        for patch in ({"project_id": "other"}, {"session_id": "../bad"}, {"current": True}, {"expected_agent_id": "other"}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "session_config_compare", {"project_id": "test-project", "session_id": "session-1", **patch})
        assert calls == [("test-project", {"session_id": "session-1"})]
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_registered_project_discovery_and_native_dispatch_reuse():
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        projects = await asyncio.to_thread(execute_action, "projects", {})
        assert projects == {"projects": [{"projectId": "test-project"}], "skippedProjects": []}
        result = await asyncio.to_thread(execute_action, "dispatch", {
            "project_id": "test-project", "agent_id": "agent-1", "task": "查项目状态",
            "dispatch_id": "dispatch-1"}, runtime={"agentId": "assistant", "sessionId": "own", "turnId": "turn"})
        assert result["taskId"] == "native-1"
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "dispatch", {"project_root": "/arbitrary"})
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "agents", {"project_id": "unregistered"})
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "approve", {"decision": "accept"})
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_offline_error_stays_a_bounded_tool_receipt():
    class Offline(Dispatch):
        async def discover(self, project_id):
            raise DispatchError("Native task operation failed", code="BACKEND_UNAVAILABLE")
    dispatch = Offline()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(execute_action, "agents", {"project_id": "test-project"})
        assert result == {"ok": False, "code": "BACKEND_UNAVAILABLE", "message": "Native task operation failed"}
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_management_wait_includes_native_write_timeout_and_original_receipt(tmp_path, monkeypatch):
    from core.assistant_runtime import actions
    from core.assistant_runtime.dispatch import DispatchService
    from core.external_agent.backend_client import BackendClientError

    calls, waits = [], []

    class Client:
        async def diagnostics(self):
            return {"status": "healthy"}

        async def management_action(self, **values):
            calls.append(("write", values))
            error = BackendClientError("slow native write", code="BACKEND_TIMEOUT")
            error.management_action = values["action"]
            error.management_request_id = values["request_id"]
            raise error

        async def management_receipt(self, **values):
            calls.append(("receipt", values))
            return {"status": "completed", "action": values["action"], "requestId": values["request_id"],
                "verified": True, "reused": True, "agent": {"agentId": "agent-a"}}

    submit = asyncio.run_coroutine_threadsafe

    def observe_wait(coroutine, loop):
        pending = submit(coroutine, loop)

        class Future:
            def result(self, timeout):
                waits.append(timeout)
                assert timeout == 125, "25s POST plus receipt recovery must fit inside the tool wait"
                return pending.result(timeout=2)

            def cancel(self):
                return pending.cancel()

        return Future()

    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"},
        client_factory=lambda *_args, **_kwargs: Client())
    bind_actions(service, asyncio.get_running_loop())
    monkeypatch.setattr(actions.asyncio, "run_coroutine_threadsafe", observe_wait)
    try:
        result = await asyncio.to_thread(execute_action, "agent_archive", {
            "project_id": "p", "request_id": "slow-1", "agent_id": "agent-a", "expected_config_revision": 3},
            governed=True)
    finally:
        unbind_actions(service)
    assert result["status"] == "completed" and result["reconciledAfterTimeout"] is True
    assert waits == [125] and [kind for kind, _ in calls] == ["write", "receipt"]
    assert calls[1][1] == {"action": "agent_archive", "request_id": "slow-1"}


@pytest.mark.anyio
async def test_expired_management_wait_releases_local_locks_and_preserves_native_writer(tmp_path, monkeypatch):
    from threading import Event
    from core.assistant_runtime import actions
    from core.assistant_runtime.dispatch import DispatchService

    entered, cancelled = Event(), asyncio.Event()
    finish_native = asyncio.Event()
    native_writes, lookups, remote_tasks = [], [], []

    async def native_write():
        native_writes.append("agent-a")
        entered.set()
        await finish_native.wait()
        return {"agentId": "agent-a"}

    class Client:
        async def diagnostics(self):
            return {"status": "healthy"}

        async def management_action(self, **values):
            # An accepted server request outlives its disconnected client.
            remote = asyncio.create_task(native_write())
            remote_tasks.append(remote)
            try:
                return await asyncio.shield(remote)
            finally:
                cancelled.set()

        async def management_receipt(self, **values):
            lookups.append(values)
            done = bool(remote_tasks) and remote_tasks[0].done()
            return {"status": "completed" if done else "unknown", "action": values["action"],
                "requestId": values["request_id"], "verified": done, "reused": True,
                **({"agent": remote_tasks[0].result()} if done else {})}

    service = DispatchService(tmp_path / "profile", {"p": tmp_path / "project"},
        client_factory=lambda *_args, **_kwargs: Client())
    submit = asyncio.run_coroutine_threadsafe
    local_futures = []

    def expire_wait(coroutine, loop):
        pending = submit(coroutine, loop)
        local_futures.append(pending)

        class Future:
            def result(self, timeout):
                assert timeout == 125
                assert entered.wait(2)
                return pending.result(timeout=0.03)

            def cancel(self):
                return pending.cancel()

        return Future()

    parameters = {"project_id": "p", "request_id": "slow-1", "agent_id": "agent-a", "expected_config_revision": 3}
    bind_actions(service, asyncio.get_running_loop())
    try:
        with monkeypatch.context() as patch:
            patch.setattr(actions.asyncio, "run_coroutine_threadsafe", expire_wait)
            with pytest.raises(ValueError, match="原生请求尚未确认"):
                await asyncio.to_thread(execute_action, "agent_archive", parameters, governed=True)
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        assert local_futures[0].cancelled()
        assert not service._project_locks["p"].locked()
        assert all(not lock.locked() for lock in service.management._locks.values())
        assert not remote_tasks[0].done()
        reference = {"project_id": "p", "action": "agent_archive", "request_id": "slow-1"}
        progress = await asyncio.wait_for(asyncio.to_thread(execute_action, "management_receipt", reference), timeout=1)
        assert progress["status"] == "unknown"
        finish_native.set()
        await remote_tasks[0]
        final = await asyncio.to_thread(execute_action, "management_receipt", reference)
        assert final["status"] == "completed" and final["agent"]["agentId"] == "agent-a"
        assert await asyncio.to_thread(execute_action, "agent_archive", parameters, governed=True) == final
        assert native_writes == ["agent-a"] and len(lookups) == 3
    finally:
        finish_native.set()
        if remote_tasks:
            await asyncio.gather(*remote_tasks)
        unbind_actions(service)


@pytest.mark.anyio
async def test_dispatch_model_marker_rewrite_fails_before_record_or_network(tmp_path, monkeypatch):
    from core.assistant_runtime import native
    from core.assistant_runtime.dispatch import DispatchService
    marker = "E3_RECEIPT_3E159D2DFC294ED1"
    runtime = {"agentId": "assistant-a", "sessionId": "assistant-session", "turnId": "turn-a"}
    monkeypatch.setattr(native, "read_task_source", lambda *_args, **_kwargs: {
        **runtime, "eventId": "user-a", "content": "只回复 " + marker}, raising=False)
    service = DispatchService(tmp_path / "profile", {"test-project": tmp_path / "project"},
        client_factory=lambda *_args, **_kwargs: pytest.fail("rewritten task reached network"))
    bind_actions(service, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(execute_action, "dispatch", {
            "project_id": "test-project", "agent_id": "agent-1", "task": "只回复 " + marker[:-1] + "4",
            "dispatch_id": "source-1"}, runtime=runtime)
        assert result["ok"] is False and "task_source" in result["message"]
        assert not list(tmp_path.rglob("*.json"))
    finally:
        unbind_actions(service)


@pytest.mark.parametrize("source", [{}, {"task": "x", "task_source": {}}, {"task": None}, {"task_source": None},
    {"task_source": {"start_after": "x" * 257}}, {"task_source": {"sessionId": "other"}},
    {"task_source": {}, "source_ref": {"turnId": "model-selected"}}],
    ids=["missing", "both", "null_raw", "null_selector", "long_anchor", "target_identity", "forged_ref"])
def test_dispatch_model_schema_has_exactly_one_closed_source(source):
    from pydantic import ValidationError
    from core.assistant_runtime.actions import Dispatch as Schema
    with pytest.raises(ValidationError):
        Schema.model_validate({"project_id": "project", "agent_id": "agent", "dispatch_id": "request", **source})
    schema = Schema.model_json_schema()
    assert len(schema["oneOf"]) == 2 and schema["additionalProperties"] is False
    assert schema["$defs"]["TaskSelector"]["additionalProperties"] is False


@pytest.mark.anyio
async def test_api_describe_exposes_only_local_pointer_view_fields_within_native_budget():
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        description = execute_action("describe", {"action": "api_describe"})
        assert set(description["parameters"]["properties"]) == {
            "project_id", "operation_id", "document_pointer", "offset", "limit", "expected_document_digest"}
        assert description["parameters"]["properties"]["document_pointer"]["default"] == ""
        raw, outcome, facts, rendered = _through_native_model_budget(description)
        assert len(raw) <= 3400 and outcome is None and not facts.truncated
        assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
    finally:
        unbind_actions(dispatch)
