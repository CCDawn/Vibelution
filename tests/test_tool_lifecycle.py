from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Any

from langchain_core.messages import ToolMessage

from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, CanonicalToolResult
from core.orchestration.tool_lifecycle import ToolLifecycleBridge


def test_restart_special_case_obeys_canonical_execution_authorization(monkeypatch):
    from types import SimpleNamespace

    from core.authorization import tool_authorization_service
    from core.web.services import agent_directory_service

    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-a",
            "turnId": "turn-a",
            "agentConfigSnapshot": {
                "agentId": "agent-a",
                "configRevision": 1,
                "configHash": "test-config-hash",
            },
            "permissionPreset": "request_approval",
        },
    )
    tool_authorization_service.install_execution_authorization(
        SimpleNamespace(
            decision=SimpleNamespace(
                agent_id="agent-a",
                turn_id="turn-a",
                decision_fingerprint="decision-a",
                executable_tools=(),
            )
        )
    )
    executor_calls = []
    bridge = ToolLifecycleBridge(
        tool_executor_execute=lambda *args, **kwargs: executor_calls.append((args, kwargs)) or ("unsafe", None),
    )

    result, action = bridge.execute_tool(
        {"id": "call-restart", "name": "trigger_self_restart_tool", "args": {}},
        [],
    )

    assert "未被本回合授权执行" in result
    assert action is None
    assert executor_calls == []


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


def test_execute_tool_projects_runtime_metadata_without_leaking_navigation_to_model_history():
    captured = []
    raw = (
        "[文件] demo.py\n"
        "[区间] 第 1-20 行 | 已显示 20 行 | 剩余 80 行\n"
        "[阅读导航] 继续调用 read_file_tool(offset=20, max_lines=20)。\n\n"
        "--- Content ---\n"
        "def factual_result():\n    return 1\n"
    )
    bridge = ToolLifecycleBridge(
        tool_executor_execute=lambda *_args, **_kwargs: (raw, None),
        runtime_metadata_observer=lambda _call, metadata: captured.append(metadata),
    )
    messages: list[Any] = []

    result, action = bridge.execute_tool(
        {"name": "read_file_tool", "args": {"path": "demo.py"}, "id": "call-meta"},
        messages,
    )
    ToolLifecycleBridge.handle_tool_result(
        {"name": "read_file_tool", "id": "call-meta"},
        result,
        action,
        messages,
    )

    assert "offset=20" in captured[0].continuation_hint
    assert "阅读导航" not in messages[0].content
    assert "offset=20" not in messages[0].content


def test_tool_result_observer_keeps_full_evidence_while_model_message_is_bounded():
    raw = "full-evidence:" + ("X" * 8000)
    observed: list[str] = []
    bridge = ToolLifecycleBridge(
        tool_executor_execute=lambda *_args, **_kwargs: (raw, None),
        tool_result_observer=lambda _call, result, _action: observed.append(str(result)),
    )
    messages: list[Any] = []
    tool_call = {"name": "read_file_tool", "args": {"path": "large.txt"}, "id": "call-large"}

    result, action = bridge.execute_tool(tool_call, messages)
    ToolLifecycleBridge.handle_tool_result(tool_call, result, action, messages)

    assert observed == [raw]
    assert messages[0].tool_call_id == "call-large"
    assert len(messages[0].content) <= 4000
    assert "originalLength: 8014" in messages[0].content
    assert "truncated: true" in messages[0].content


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


def test_handle_tool_result_creates_one_canonical_result_and_one_compatibility_message(monkeypatch):
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
    events: list[dict[str, Any]] = []
    from core.web.services import runtime_scene_service

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda _component, _phase, event_code, **kwargs: events.append(
            {"eventCode": event_code, **kwargs}
        ),
    )

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
    assert events == [
        {
            "eventCode": "tool.result.bound",
            "message": "Tool result binding to model history recorded.",
            "level": "info",
            "outcome": "completed",
            "lifecycle": False,
            "fields": {
                "toolCallId": "call-1",
                "toolName": "read_file_tool",
                "resultBound": True,
                "canonicalResult": True,
                "semanticStatus": "completed",
                "sessionId": "session-1",
                "turnId": "turn-1",
                "invocationId": "invocation-1",
            },
        }
    ]


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


def test_execute_tool_parses_json_arguments_alias():
    observed: dict[str, Any] = {}

    def fake_execute(tool_name, tool_args, *, tool_call_id=""):
        observed.update(name=tool_name, args=tool_args, call_id=tool_call_id)
        return ("ok", None)

    bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)
    result, action = bridge.execute_tool(
        {"name": "read_file_tool", "arguments": '{"path": "a.py"}', "id": "call-json"},
        [],
    )

    assert result == "ok"
    assert action is None
    assert observed == {
        "name": "read_file_tool",
        "args": {"path": "a.py"},
        "call_id": "call-json",
    }


def test_tool_result_observer_exception_does_not_fail_execute_tool():
    bridge = ToolLifecycleBridge(
        tool_executor_execute=lambda *_args, **_kwargs: ("ok", None),
        tool_result_observer=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("observer")),
    )
    result, action = bridge.execute_tool(
        {"name": "read_file_tool", "args": {"path": "a.py"}, "id": "call-obs"},
        [],
    )
    assert result == "ok"
    assert action is None


def test_budget_exhausted_binds_remaining_declared_calls_without_executing_them():
    calls: list[str] = []

    def fake_execute(tool_name, _tool_args, *, tool_call_id=""):
        calls.append(tool_name)
        if tool_name == "write_file_tool":
            return ("quota used", "tool_budget_exhausted")
        return (f"ran:{tool_name}", None)

    messages: list[Any] = []
    bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)
    action = bridge.execute_tools(
        [
            {"name": "write_file_tool", "args": {}, "id": "call-write"},
            {"name": "read_file_tool", "args": {}, "id": "call-read"},
            {"name": "grep_search_tool", "args": {}, "id": "call-grep"},
        ],
        messages,
    )

    assert action == "tool_budget_exhausted"
    assert calls == ["write_file_tool"]
    assert [message.tool_call_id for message in messages] == ["call-write", "call-read", "call-grep"]
    assert "额度已用尽" in messages[1].content
    assert "额度已用尽" in messages[2].content
    assert "ran:read_file_tool" not in messages[1].content


def test_max_parallel_readonly_zero_uses_serial_pool_not_default(monkeypatch):
    seen_workers: list[int] = []
    from concurrent.futures import ThreadPoolExecutor as RealPool
    import core.orchestration.tool_lifecycle as lifecycle

    def capturing_pool(*args, **kwargs):
        seen_workers.append(int(kwargs.get("max_workers") or (args[0] if args else 0)))
        return RealPool(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "ThreadPoolExecutor", capturing_pool)
    bridge = ToolLifecycleBridge(tool_executor_execute=lambda *_args, **_kwargs: ("ok", None))
    messages: list[Any] = []
    action = bridge.execute_tools(
        [
            {"name": "read_file_tool", "args": {}, "id": "call-a"},
            {"name": "grep_search_tool", "args": {}, "id": "call-b"},
            {"name": "list_files_tool", "args": {}, "id": "call-c"},
        ],
        messages,
        max_parallel_readonly=0,
    )

    assert action is None
    assert seen_workers == [1]
    assert [message.tool_call_id for message in messages] == ["call-a", "call-b", "call-c"]
