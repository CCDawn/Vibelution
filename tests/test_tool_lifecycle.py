from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Any

from langchain_core.messages import ToolMessage

from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, CanonicalToolResult
from core.orchestration.tool_lifecycle import ToolLifecycleBridge


def test_execute_tool_passes_call_id_to_executor_events():
    observed: dict[str, Any] = {}

    def fake_execute(tool_name, tool_args, *, tool_call_id=""):
        observed.update(name=tool_name, args=tool_args, call_id=tool_call_id)
        return ("ok", None)

    bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)

    result, action = bridge.execute_tool(
        {"name": "read_file_tool", "args": {"path": "agent.py"}, "id": "call-identity"},
        [],
    )

    assert result == "ok"
    assert action is None
    assert observed == {
        "name": "read_file_tool",
        "args": {"path": "agent.py"},
        "call_id": "call-identity",
    }


def test_readonly_batch_isolates_worker_exception_and_preserves_success_results():
    original_messages: list[Any] = []
    worker_message_ids: list[int] = []

    class CapturingBridge(ToolLifecycleBridge):
        def execute_tool(self, tool_call, messages):  # type: ignore[override]
            worker_message_ids.append(id(messages))
            messages.append("worker-local mutation")
            tool_name = str(tool_call.get("name") or "")
            if tool_name == "grep_search_tool":
                raise RuntimeError("boom")
            return (f"result:{tool_name}", None)

    bridge = CapturingBridge(tool_executor_execute=lambda _name, _args: ("unused", None))

    action = bridge.execute_tools(
        [
            {"name": "read_file_tool", "args": {}, "id": "call-read"},
            {"name": "grep_search_tool", "args": {}, "id": "call-grep"},
            {"name": "list_files_tool", "args": {}, "id": "call-list"},
        ],
        original_messages,
        max_parallel_readonly=3,
    )

    assert action is None
    assert len(original_messages) == 3
    assert all(isinstance(message, ToolMessage) for message in original_messages)
    assert [message.tool_call_id for message in original_messages] == ["call-read", "call-grep", "call-list"]
    assert "toolName: read_file_tool" in original_messages[0].content
    assert "Result:\nresult:read_file_tool" in original_messages[0].content
    assert "toolName: grep_search_tool" in original_messages[1].content
    assert "[错误] read-only 工具 grep_search_tool 执行失败: RuntimeError: boom" in original_messages[1].content
    assert "toolName: list_files_tool" in original_messages[2].content
    assert "Result:\nresult:list_files_tool" in original_messages[2].content
    assert "worker-local mutation" not in original_messages
    assert worker_message_ids
    assert all(message_id != id(original_messages) for message_id in worker_message_ids)


def test_readonly_batch_gives_each_future_an_independent_context_copy():
    worker_context = ContextVar("readonly_worker_context", default="missing")
    parent_token = worker_context.set("parent")
    worker_barrier = threading.Barrier(3)
    observed: list[tuple[str, str, str]] = []
    observed_lock = threading.Lock()

    class ContextCapturingBridge(ToolLifecycleBridge):
        def execute_tool(self, tool_call, messages):  # type: ignore[override]
            call_id = str(tool_call.get("id") or "")
            inherited_value = worker_context.get()
            worker_context.set(call_id)
            worker_barrier.wait(timeout=5)
            with observed_lock:
                observed.append((call_id, inherited_value, worker_context.get()))
            return (f"result:{call_id}", None)

    bridge = ContextCapturingBridge(tool_executor_execute=lambda _name, _args: ("unused", None))
    messages: list[Any] = []
    try:
        action = bridge.execute_tools(
            [
                {"name": "read_file_tool", "args": {}, "id": "call-a"},
                {"name": "grep_search_tool", "args": {}, "id": "call-b"},
                {"name": "list_files_tool", "args": {}, "id": "call-c"},
            ],
            messages,
            max_parallel_readonly=3,
        )

        assert action is None
        assert worker_context.get() == "parent"
    finally:
        worker_context.reset(parent_token)

    assert {inherited for _, inherited, _ in observed} == {"parent"}
    assert {(call_id, worker_value) for call_id, _, worker_value in observed} == {
        ("call-a", "call-a"),
        ("call-b", "call-b"),
        ("call-c", "call-c"),
    }


def test_handle_tool_result_creates_one_canonical_result_and_one_compatibility_message():
    identity = CanonicalItemIdentity(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-1",
        iteration=1,
        item_id="call-1",
    )
    canonical_call = CanonicalToolCall(
        identity=identity,
        call_id="call-1",
        name="read_file_tool",
        arguments={"path": "agent.py"},
    )
    messages: list[Any] = []

    canonical_result = ToolLifecycleBridge.handle_tool_result(
        {
            "name": "read_file_tool",
            "id": "call-1",
            "canonical_tool_call": canonical_call,
        },
        "file content",
        None,
        messages,
    )

    assert isinstance(canonical_result, CanonicalToolResult)
    assert canonical_result.call_id == "call-1"
    assert canonical_result.tool_name == "read_file_tool"
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert messages[0].tool_call_id == "call-1"
    assert messages[0].additional_kwargs["canonical_tool_result"] is canonical_result


def test_handle_tool_result_uses_business_failure_semantics_for_canonical_status():
    identity = CanonicalItemIdentity(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-2",
        iteration=1,
        item_id="call-2",
    )
    canonical_call = CanonicalToolCall(
        identity=identity,
        call_id="call-2",
        name="write_file_tool",
        arguments={"path": "blocked.txt"},
    )
    messages: list[Any] = []

    canonical_result = ToolLifecycleBridge.handle_tool_result(
        {
            "name": "write_file_tool",
            "id": "call-2",
            "canonical_tool_call": canonical_call,
        },
        {"ok": False, "error": "blocked"},
        None,
        messages,
    )

    assert isinstance(canonical_result, CanonicalToolResult)
    assert canonical_result.status == "failed"
    assert canonical_result.is_error is True
    assert messages[0].additional_kwargs["canonical_tool_result"] is canonical_result
