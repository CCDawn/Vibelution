# -*- coding: utf-8 -*-
"""todo_write 清单工具回归：实现契约、注册面、授权面与会话投影。"""

import json

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_STARTED,
    append_turn_event,
    load_turn_events,
    session_turn_items_from_events,
)
from core.web.services import agent_directory_service, tool_catalog
from core.web.services.tool_registry_service import get_tool_registry
from tools.Key_Tools import create_key_tools, create_llm_facing_tools
from tools.todo_tools import MAX_TODO_ITEMS, todo_write


# ---------------------------------------------------------------------------
# 工具实现契约：全量快照校验 + 确认回显，不落盘
# ---------------------------------------------------------------------------

def test_todo_write_returns_confirmation_echo_for_valid_snapshot():
    result = json.loads(todo_write([
        {"content": "定位 owning surface", "activeForm": "正在定位 owning surface", "status": "completed"},
        {"content": "补齐回归测试", "activeForm": "正在补齐回归测试", "status": "in_progress"},
        {"content": "更新文档", "activeForm": "正在更新文档", "status": "pending"},
    ]))

    assert result["status"] == "ok"
    assert result["itemCount"] == 3
    assert result["completedCount"] == 1
    assert result["pendingCount"] == 1
    assert result["inProgress"] == ["正在补齐回归测试"]


def test_todo_write_accepts_json_string_payload_and_defaults_active_form_to_content():
    payload = json.dumps([
        {"content": "只写祈使句", "status": "pending"},
    ], ensure_ascii=False)

    result = json.loads(todo_write(payload))

    assert result["status"] == "ok"
    assert result["itemCount"] == 1


def test_todo_write_rejects_multiple_in_progress_items():
    result = json.loads(todo_write([
        {"content": "a", "status": "in_progress"},
        {"content": "b", "status": "in_progress"},
    ]))

    assert result["status"] == "error"
    assert result["code"] == "INVALID_TODOS"
    assert "in_progress" in result["message"]


@pytest.mark.parametrize("payload", [
    "not json",
    {"todos": []},
    [{"status": "pending"}],
    [{"content": "x", "status": "doing"}],
    [{"content": "x", "status": "pending"}, "not-an-object"],
])
def test_todo_write_rejects_invalid_payloads(payload):
    result = json.loads(todo_write(payload))

    assert result["status"] == "error"
    assert result["code"] == "INVALID_TODOS"


def test_todo_write_rejects_oversized_snapshots():
    payload = [
        {"content": f"item {index}", "status": "pending"}
        for index in range(MAX_TODO_ITEMS + 1)
    ]

    result = json.loads(todo_write(payload))

    assert result["status"] == "error"
    assert str(MAX_TODO_ITEMS) in result["message"]


# ---------------------------------------------------------------------------
# 注册面：LLM 可见、schema 三字段、描述带状态纪律
# ---------------------------------------------------------------------------

def test_todo_write_is_registered_and_llm_facing():
    key_names = [tool.name for tool in create_key_tools()]
    llm_names = [tool.name for tool in create_llm_facing_tools()]

    assert "todo_write" in key_names
    assert "todo_write" in llm_names


def test_todo_write_schema_declares_full_snapshot_todos():
    tool = next(tool for tool in create_llm_facing_tools() if tool.name == "todo_write")
    schema = tool.args_schema.model_json_schema()
    description = getattr(tool, "description", "")

    todo_property = schema["properties"]["todos"]
    assert todo_property.get("type") == "array"
    assert todo_property.get("items", {}).get("type") == "object"
    # 状态纪律必须写进工具描述，引导模型遵循 Claude Code 范式。
    assert "全量" in description
    assert "in_progress" in description
    assert "completed" in description
    for field in ("content", "activeForm", "status"):
        assert field in description


# ---------------------------------------------------------------------------
# 授权面：默认 session agent 可见，registry 描述符低风险只读
# ---------------------------------------------------------------------------

def test_todo_write_is_in_default_session_agent_allowed_tools():
    assert "todo_write" in agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS

    policy = agent_directory_service.default_session_agent_tool_policy("tool-test")
    assert "todo_write" in policy["allowedTools"]


def test_todo_write_registry_descriptor_is_low_risk_read_only():
    payload = get_tool_registry()
    tool = next(item for item in payload["tools"] if item["name"] == "todo_write")
    descriptor = next(item for item in payload["descriptors"] if item["name"] == "todo_write")

    assert tool["llmVisible"] is True
    assert tool["runtimeActive"] is True
    assert descriptor["risk"] == "read"
    assert descriptor["approval"] == "never"
    assert tool_catalog.permission_tier_for_tool("todo_write") == tool_catalog.LOW_PERMISSION_TIER


# ---------------------------------------------------------------------------
# 会话投影：journal 回放的 tool_call turn item 保留结构化 todos（前端派生源）
# ---------------------------------------------------------------------------

def test_todo_write_arguments_survive_journal_turn_item_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    todos = [
        {"content": "梳理结论", "activeForm": "正在梳理结论", "status": "in_progress"},
        {"content": "落盘草稿", "activeForm": "正在落盘草稿", "status": "pending"},
    ]
    append_turn_event(tmp_path, "session-todo", "turn-todo", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-todo",
        "turn-todo",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="ready",
        payload={
            "kind": "tool_call",
            "status": "ready",
            "itemId": "tool-item-todo-1",
            "callId": "call-todo-1",
            "toolName": "todo_write",
            "sessionId": "session-todo",
            "turnId": "turn-todo",
            "revision": 0,
        },
    )
    append_turn_event(
        tmp_path,
        "session-todo",
        "turn-todo",
        EVENT_TOOL_RESULT,
        status="done",
        tool_call_id="call-todo-1",
        payload={
            "toolCall": {
                "id": "call-todo-1",
                "toolCallId": "call-todo-1",
                "name": "todo_write",
                "status": "done",
                "summary": "清单已更新",
                "arguments": {"todos": todos},
            }
        },
    )

    items = session_turn_items_from_events(
        load_turn_events(tmp_path, "session-todo"),
        turn_id="turn-todo",
    )
    tool_item = next(item for item in items if item["type"] == "tool_call")
    assert tool_item["toolName"] == "todo_write"
    assert json.loads(tool_item["input"]) == {"todos": todos}
