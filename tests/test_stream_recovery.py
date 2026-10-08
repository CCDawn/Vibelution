from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from core.chat.llm_resilience_journal import STAGE_STREAM_RECOVERY
from core.chat.stream_recovery import (
    REASON_LATEST_TOOL,
    REASON_NO_TOOL,
    STREAM_RECOVERY_MAX_RETRIES,
    bind_committed_tool_results,
    committed_tool_result,
    plan_stream_recovery,
)
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_RESULT,
    append_turn_event,
    load_turn_events,
    model_messages_from_events,
)
from core.orchestration.tool_lifecycle import ToolLifecycleBridge


def _tool_event(call_id: str, text: str, *, error: bool = False) -> SimpleNamespace:
    tool_call = {"name": "read_file_tool", "id": call_id}
    if error:
        tool_call["error"] = text
    else:
        tool_call["result"] = text
    return SimpleNamespace(
        event_type="tool_result",
        tool_call_id=call_id,
        turn_id="turn-1",
        payload={"toolCall": tool_call},
    )


def test_plan_counts_tool_errors_and_drops_unfinished_ids():
    plan = plan_stream_recovery(
        [_tool_event("call-ok", "done"), _tool_event("call-bad", "disk full", error=True)],
        assistant_message_id="turn-1",
        discarded_text="",
        retryable=False,
        failure_kind="provider_timeout",
    )

    assert plan is not None
    assert plan["reason"] == REASON_LATEST_TOOL
    assert plan["anchorId"] == "turn-1:call-bad:tool-result"
    assert plan["committedToolCallIds"] == ["call-ok", "call-bad"]
    assert plan["committedResults"]["call-bad"] == "disk full"
    assert plan["discardedToolCallIds"] == []
    assert plan["failureKind"] == "provider_timeout"
    assert plan["maxRetries"] == STREAM_RECOVERY_MAX_RETRIES


def test_plan_without_tools_needs_retryable_output_and_honors_stop_and_budget():
    events = []

    assert plan_stream_recovery(events, assistant_message_id="turn-1", discarded_text="半截", retryable=False) is None
    assert plan_stream_recovery(events, assistant_message_id="turn-1", discarded_text="", retryable=True) is None
    assert (
        plan_stream_recovery(
            events,
            assistant_message_id="turn-1",
            discarded_text="半截",
            retryable=True,
            user_stopped=True,
        )
        is None
    )
    assert (
        plan_stream_recovery(
            [_tool_event("call-1", "done")],
            assistant_message_id="turn-1",
            retry_count=STREAM_RECOVERY_MAX_RETRIES,
            retryable=True,
        )
        is None
    )

    plan = plan_stream_recovery(
        events,
        assistant_message_id="turn-1",
        discarded_text="半截",
        discarded_reasoning="想",
        retryable=True,
    )
    assert plan is not None
    assert plan["reason"] == REASON_NO_TOOL
    assert plan["anchorId"] == "turn-1:previous-message-anchor"
    assert plan["committedToolCallIds"] == []
    assert plan["discardedTextBytes"] > 0
    assert plan["discardedReasoningBytes"] > 0


def test_model_replay_drops_partial_only_after_stream_recovery(tmp_path):
    append_turn_event(
        tmp_path,
        "sess",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="error",
        payload={"toolCall": {"name": "read_file_tool", "id": "call-1", "error": "disk full"}},
        tool_call_id="call-1",
        visible_in_model=True,
    )
    append_turn_event(
        tmp_path,
        "sess",
        "turn-1",
        EVENT_ASSISTANT_PARTIAL,
        status="streaming",
        payload={"content": "没提交的半截"},
        visible_in_model=True,
    )
    append_turn_event(
        tmp_path,
        "sess",
        "turn-2",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "已经提交的说明"},
        visible_in_model=True,
    )

    before = model_messages_from_events(load_turn_events(tmp_path, "sess"))
    assert any("没提交的半截" in str(item.get("content") or "") for item in before)
    assert any("已经提交的说明" in str(item.get("content") or "") for item in before)

    append_turn_event(
        tmp_path,
        "sess",
        "turn-1",
        "llm_resilience",
        status=STAGE_STREAM_RECOVERY,
        payload={
            "schema": "llm_resilience.v1",
            "stage": STAGE_STREAM_RECOVERY,
            "attempt": 1,
            "anchorId": "turn-1:call-1:tool-result",
            "reason": REASON_LATEST_TOOL,
            "discardedToolCallIds": [],
        },
        visible_in_model=False,
    )

    after = model_messages_from_events(load_turn_events(tmp_path, "sess"))
    contents = [str(item.get("content") or "") for item in after]
    kinds = [
        str((item.get("metadata") or {}).get("kind") or "")
        for item in after
        if isinstance(item.get("metadata"), dict)
    ]
    assert not any("没提交的半截" in text for text in contents)
    assert any("已经提交的说明" in text for text in contents)
    assert "journal_assistant_partial" not in kinds
    assert not any(
        kind == "turn_interrupted" and str((item.get("metadata") or {}).get("reason") or "") == "open_turn_replay"
        for item in after
        if isinstance(item, dict)
        for kind in [str((item.get("metadata") or {}).get("kind") or "")]
    )
    rendered = json.dumps(after, ensure_ascii=False, default=str)
    assert "call-1" in rendered
    assert "disk full" in rendered


def test_execute_tools_does_not_rerun_or_duplicate_committed_results():
    calls: list[str] = []

    def fake_execute(tool_name, tool_args, *, tool_call_id=""):
        calls.append(tool_call_id)
        return ("ran", None)

    bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)
    bind_committed_tool_results({"call-1": "disk full", "call-empty": ""})
    messages: list = []

    bridge.execute_tools(
        [
            {"id": "call-1", "name": "read_file_tool", "args": {"path": "a"}},
            {"id": "call-empty", "name": "read_file_tool", "args": {"path": "b"}},
            {"id": "call-new", "name": "read_file_tool", "args": {"path": "c"}},
        ],
        messages,
    )

    assert calls == ["call-new"]
    bound_ids = [message.tool_call_id for message in messages if isinstance(message, ToolMessage)]
    assert bound_ids == ["call-1", "call-empty", "call-new"]
    assert "disk full" in str(messages[0].content)
    assert messages[1].tool_call_id == "call-empty"

    bridge.execute_tools(
        [{"id": "call-1", "name": "read_file_tool", "args": {"path": "a"}}],
        messages,
    )
    assert calls == ["call-new"]
    assert [message.tool_call_id for message in messages if isinstance(message, ToolMessage)] == [
        "call-1",
        "call-empty",
        "call-new",
    ]
    bind_committed_tool_results({})


def test_recover_failed_model_stream_journals_anchor_and_skips_user_stop(tmp_path, monkeypatch):
    from agent import AgentRuntime

    append_turn_event(
        tmp_path,
        "sess",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="error",
        payload={"toolCall": {"name": "read_file_tool", "id": "call-1", "error": "disk full"}},
        tool_call_id="call-1",
        visible_in_model=True,
    )
    agent = AgentRuntime.__new__(AgentRuntime)
    agent._chat_ledger_identity = lambda: (tmp_path, "sess", "turn-1")
    agent._current_turn_stop_reason = lambda: ""
    agent._last_llm_error_retryable = False
    agent._stream_recovery_retry_count = 0
    agent._last_llm_error_category = "provider_timeout"
    agent._last_llm_error_message = "timed out"
    agent._last_visible_response_text = "半截"
    discarded = {"called": False}
    monkeypatch.setattr(
        "core.web.services.session.stream_capture.peek_uncommitted_live_stream_tail",
        lambda: ("半截", "想过"),
    )
    monkeypatch.setattr(
        "core.web.services.session.stream_capture.discard_uncommitted_live_stream_tail",
        lambda: discarded.__setitem__("called", True),
    )

    assert agent._recover_failed_model_stream() is True
    assert discarded["called"] is True
    assert agent._last_visible_response_text == ""
    assert agent._stream_recovery_retry_count == 1
    assert committed_tool_result("call-1") == "disk full"
    recovery = [
        event
        for event in load_turn_events(tmp_path, "sess")
        if event.event_type == "llm_resilience"
    ]
    assert recovery[-1].payload["stage"] == STAGE_STREAM_RECOVERY
    assert recovery[-1].payload["reason"] == REASON_LATEST_TOOL
    assert recovery[-1].payload["discardedToolCallIds"] == []
    assert recovery[-1].visible_in_model is False

    agent._current_turn_stop_reason = lambda: "stopped_by_user"
    assert agent._recover_failed_model_stream() is False
    bind_committed_tool_results({})
