from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage

from core.orchestration.tool_lifecycle import ToolLifecycleBridge


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
    assert original_messages[0].content == "result:read_file_tool"
    assert original_messages[1].content == "[错误] read-only 工具 grep_search_tool 执行失败: RuntimeError: boom"
    assert original_messages[2].content == "result:list_files_tool"
    assert "worker-local mutation" not in original_messages
    assert worker_message_ids
    assert all(message_id != id(original_messages) for message_id in worker_message_ids)
