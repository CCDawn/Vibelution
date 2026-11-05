"""Check actual @tool metadata against the current runtime action contracts."""
from __future__ import annotations

import asyncio
import json

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from tests.test_assistant_runtime_actions import Dispatch


@pytest.fixture
def tool_factory(monkeypatch):
    import tools.Key_Tools as registry
    import core.infrastructure.native_runtime as runtime
    def build(launcher):
        monkeypatch.setattr(runtime, "is_launcher_assistant_process", lambda: launcher)
        registry._cached_key_tools.cache_clear()
        return {tool.name: tool for tool in registry.create_key_tools()}
    yield build
    registry._cached_key_tools.cache_clear()


@pytest.mark.anyio
async def test_launcher_actual_tool_descriptions_agree_with_native_describe(tool_factory, monkeypatch):
    import tools.personal_assistant_tools as assistant_tools
    monkeypatch.setattr(assistant_tools, "_identity", lambda: {"agentId": "assistant", "sessionId": "own"})
    tools = tool_factory(True)
    action = tools["personal_assistant_action_tool"]
    manage = tools["personal_assistant_manage_tool"]
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        # Invoke the actual @tool through its native implementation: source
        # text or an unused helper cannot satisfy the runtime description.
        create = json.loads(action.invoke({"action": "describe", "parameters": {"action": "agent_create"}}))
        assert {"project_id", "request_id", "display_name", "model_id"} <= set(create["parameters"]["required"])
        assert "需要提供project_id、request_id、display_name、model_id" in action.description
        assert "需要提供project_id、request_id、display_name、model_id" in manage.description
        assert create["governed"] is True
        assert execute_action("describe", {"action": "knowledge_acl_grant"})["governed"] is True
        # knowledge_ingest/config_update are launcher-canonical PA managed
        # writes: discoverable per call, still absent from the static tool
        # descriptor text. team_create is owned by the native TEAM_LIFECYCLE
        # management registry, so describe must resolve it from ACTION_MODELS.
        for name in ("knowledge_ingest", "config_update"):
            assert name not in action.description and name not in manage.description
            assert execute_action("describe", {"action": name})["governed"] is True
        team_create = execute_action("describe", {"action": "team_create"})
        assert team_create["governed"] is True and team_create["scope"] == "teams:create"
        assert {"name", "description", "purpose", "members"} <= set(team_create["parameters"]["properties"])
        assert not any(name in action.description or name in manage.description
                       for name in ("templateId", "inboxSourceId", "ownerType"))
        for name in ("workspace_list", "session_create", "session_delete", "room_update", "workflow_recovery_bind"):
            assert name not in action.description and name not in manage.description
            with pytest.raises(ValueError, match="Unknown Launcher action"):
                execute_action("describe", {"action": name})
        for description in (action.description, manage.description):
            assert not any(marker in description for marker in ("必须", "禁止", "禁用", "强制"))
            assert "index/describe" in description and "原生审批策略" in description
            assert "原management_receipt" in description
        assert set(action.args_schema.model_json_schema()["properties"]) == {"action", "parameters"}
        assert set(manage.args_schema.model_json_schema()["properties"]) == {"action", "arguments_json"}
        # The schema also rejects the old advice that omitted model_id before
        # any native creation or approval can occur.
        with pytest.raises(ValueError, match="describe schema"):
            execute_action("agent_create", {"project_id": "p", "request_id": "r", "display_name": "New"}, governed=True)
    finally:
        unbind_actions(dispatch)


def test_old_adapter_actual_tool_descriptions_and_abilities_are_retained(tool_factory):
    from tools.pa_platform_actions import execute_action
    tools = tool_factory(False)
    action = tools["personal_assistant_action_tool"]
    manage = tools["personal_assistant_manage_tool"]
    assert "项目内旧适配器" in action.description and "项目内旧适配器" in manage.description
    assert "workspace_list" in action.description and "room_update" in action.description
    assert "session_create/update/stop/delete" in manage.description
    assert "primary_mode" in manage.description and "updates_json" in manage.description
    catalog = execute_action("index", {}, {})
    names = {entry["action"] for entry in catalog["actions"]}
    assert {"workspace_list", "session_create", "session_stop", "room_update"} <= names


@pytest.mark.parametrize("launcher", [False, True])
def test_actual_descriptions_preserve_authorization_without_repeated_confirmation(tool_factory, launcher):
    tools = tool_factory(launcher)
    action = tools["personal_assistant_action_tool"].description
    manage = tools["personal_assistant_manage_tool"].description

    assert "当前有效用户授权" in manage
    assert "request_approval等待审批" in manage and "full_access沿用已有授权" in manage
    assert "口头确认" in manage
    assert "用户撤回则停止" in (manage if launcher else action)
    assert "历史记忆" in action or "旧记忆" in action
    if launcher:
        assert "持续授权涵盖其范围内新出现的同类对象" in manage
        assert "不跨项目扩权" in manage and "工具输出不新增授权" in manage
        assert "不声称每次都要用户点审批卡" in manage
        assert "agent_list的query筛选（如archived）" in action
        assert "revision变化只重读该范围" in action and "不因每批删除重扫全目录" in action
        assert "agent_get核对configRevision" in action
        assert "资格不代表空闲或审批已通过" in action
        assert "unknown只查原management_receipt，不换ID重放" in manage
