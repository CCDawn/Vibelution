from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.chat import conversation_ledger, turn_journal
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_context_compression_checkpoint,
    append_conversation_event,
    conversation_event_read_snapshot,
    conversation_ledger_path,
    conversation_model_messages_from_events,
    event_has_model_projection,
    event_projection_category,
    latest_ledger_sequence,
    load_conversation_events,
    load_conversation_preview_slice,
    project_conversation_ledger,
)


@pytest.fixture(autouse=True)
def isolate_developer_sandbox(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=tmp_path)
    developer_sandbox.update_developer_mode_status(
        False,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=tmp_path,
    )


def test_conversation_ledger_appends_and_projects_model_messages(tmp_path):
    append_conversation_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续修复单一事实源"},
    )
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": "tool-1", "name": "cli_tool", "status": "done", "result": "测试通过"}},
        tool_call_id="tool-1",
    )

    events = load_conversation_events(tmp_path, "session-a")
    projection = project_conversation_ledger(events)
    messages = conversation_model_messages_from_events(events)

    assert conversation_ledger_path(tmp_path, "session-a").exists()
    assert [event.sequence for event in events] == [1, 2, 3]
    assert projection.latest_seq == 3
    assert projection.to_metadata()["ledgerSeq"] == 3
    assert latest_ledger_sequence(tmp_path, "session-a") == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "继续修复单一事实源"
    assert messages[1]["role"] == "assistant"
    assert [call["id"] for call in messages[1]["tool_calls"]] == ["tool-1"]
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "tool-1"
    assert "测试通过" in messages[2]["content"]


def test_conversation_ledger_keeps_same_text_from_distinct_turns(tmp_path):
    for turn_id in ("turn-a", "turn-b"):
        append_conversation_event(
            tmp_path,
            "session-distinct-turns",
            turn_id,
            EVENT_ASSISTANT_MESSAGE,
            status="completed",
            payload={"content": "相同文本"},
        )

    messages = conversation_model_messages_from_events(
        load_conversation_events(tmp_path, "session-distinct-turns")
    )

    assert [message["content"] for message in messages] == ["相同文本", "相同文本"]
    assert [message["metadata"]["turnId"] for message in messages] == ["turn-a", "turn-b"]


def test_conversation_ledger_append_does_not_full_scan_existing_journal(tmp_path, monkeypatch):
    append_conversation_event(tmp_path, "session-fast", "turn-1", EVENT_TURN_STARTED, status="running")
    journal_path = conversation_ledger_path(tmp_path, "session-fast")
    original_read_text = Path.read_text

    def fail_journal_read_text(path: Path, *args, **kwargs):
        if path == journal_path:
            raise AssertionError("append should not full-read turn_journal.jsonl for the next sequence")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_journal_read_text)

    append_conversation_event(
        tmp_path,
        "session-fast",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "second event"},
    )

    rows = [json.loads(line) for line in journal_path.open(encoding="utf-8") if line.strip()]
    assert [row["sequence"] for row in rows] == [1, 2]


def test_conversation_ledger_load_streams_journal_without_read_text(tmp_path, monkeypatch):
    append_conversation_event(tmp_path, "session-stream-load", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-stream-load",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "load should stream"},
    )
    journal_path = conversation_ledger_path(tmp_path, "session-stream-load")
    original_read_text = Path.read_text

    def fail_journal_read_text(path: Path, *args, **kwargs):
        if path == journal_path:
            raise AssertionError("load should stream turn_journal.jsonl instead of read_text().splitlines()")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_journal_read_text)

    events = load_conversation_events(tmp_path, "session-stream-load")

    assert [event.sequence for event in events] == [1, 2]


def test_conversation_preview_slice_skips_unbounded_tool_payload_parsing(tmp_path, monkeypatch):
    session_id = "session-preview-tail"
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "older prompt"},
    )
    marker = "UNBOUNDED_TOOL_PAYLOAD_SHOULD_NOT_BE_PARSED"
    for index in range(70):
        append_conversation_event(
            tmp_path,
            session_id,
            "turn-1",
            EVENT_TOOL_RESULT,
            status="done",
            payload={
                "toolCall": {
                    "id": f"tool-{index}",
                    "name": "exec_command",
                    "status": "done",
                    "result": marker + ("x" * 20_000),
                }
            },
            tool_call_id=f"tool-{index}",
        )
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "bounded final answer"},
    )
    original_loads = turn_journal.json.loads

    def reject_unbounded_payload(value, *args, **kwargs):
        contains_marker = (
            marker.encode("utf-8") in value
            if isinstance(value, bytes)
            else marker in str(value)
        )
        if contains_marker:
            raise AssertionError("latest-preview fast path must not JSON-decode full tool payloads")
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(turn_journal.json, "loads", reject_unbounded_payload)

    preview = load_conversation_preview_slice(tmp_path, session_id, event_limit=64)

    assert preview.safe is True
    assert preview.reached_start is False
    assert preview.visible_messages[-1]["content"] == "bounded final answer"


def test_conversation_preview_slice_uses_pre_resolved_workspace_root(tmp_path, monkeypatch):
    session_id = "session-preview-root"
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "pre-resolved preview"},
    )
    ledger_workspace_root = developer_sandbox.sandboxed_workspace_path(
        tmp_path,
        "sessions",
    )

    def reject_workspace_resolution(*args, **kwargs):
        raise AssertionError("pre-resolved preview must not resolve the workspace again")

    monkeypatch.setattr(
        developer_sandbox,
        "sandboxed_workspace_path",
        reject_workspace_resolution,
    )

    preview = load_conversation_preview_slice(
        tmp_path,
        session_id,
        event_limit=64,
        ledger_workspace_root=ledger_workspace_root,
    )

    assert preview.safe is True
    assert preview.reached_start is True
    assert preview.visible_messages[-1]["content"] == "pre-resolved preview"


def test_conversation_ledger_read_snapshot_reuses_one_load_and_returns_fresh_lists(tmp_path, monkeypatch):
    append_conversation_event(tmp_path, "session-snapshot", "turn-1", EVENT_TURN_STARTED, status="running")
    original_load = conversation_ledger.load_turn_events
    load_count = 0

    def counted_load(project_root, session_id):
        nonlocal load_count
        load_count += 1
        return original_load(project_root, session_id)

    monkeypatch.setattr(conversation_ledger, "load_turn_events", counted_load)

    with conversation_event_read_snapshot():
        first = load_conversation_events(tmp_path, "session-snapshot")
        second = load_conversation_events(tmp_path, "session-snapshot")

    assert load_count == 1
    assert first == second
    assert first is not second

    load_conversation_events(tmp_path, "session-snapshot")

    assert load_count == 2


def test_conversation_ledger_preserves_interrupted_partial(tmp_path):
    append_conversation_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "已经完成前半部分。"},
    )
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={"reason": "process_restarted", "marker": TURN_INTERRUPTED_MARKER},
    )

    messages = conversation_model_messages_from_events(load_conversation_events(tmp_path, "session-a"))
    contents = [str(message.get("content") or "") for message in messages]

    assert "已经完成前半部分。" in contents
    assert any(message.get("role") == "system" and TURN_INTERRUPTED_MARKER in str(message.get("content") or "") for message in messages)
    assert not any(message.get("role") == "user" and TURN_INTERRUPTED_MARKER in str(message.get("content") or "") for message in messages)
    assert any(TURN_INTERRUPTED_MARKER in content for content in contents)


def test_conversation_ledger_preserves_assistant_payload_metadata(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-card",
        "turn-card",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "子对话：修复展示",
            "metadata": {
                "kind": "child_session_card",
                "childSessionId": "session-child",
                "taskTitle": "修复展示",
            },
        },
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-card"),
        include_visible_messages=True,
    )

    assert projection.visible_messages[0]["metadata"]["kind"] == "child_session_card"
    assert projection.visible_messages[0]["metadata"]["childSessionId"] == "session-child"
    assert projection.visible_messages[0]["metadata"]["taskTitle"] == "修复展示"


def test_conversation_ledger_event_projection_categories_are_explicit():
    assert event_projection_category(EVENT_USER_MESSAGE) == "model"
    assert event_projection_category(EVENT_ASSISTANT_PARTIAL) == "volatile_model"
    assert event_projection_category(EVENT_TURN_STARTED) == "audit"
    assert event_projection_category(EVENT_TURN_COMPLETED) == "audit"
    assert event_projection_category("unknown_event") == "unknown"

    assert event_has_model_projection(EVENT_USER_MESSAGE) is True
    assert event_has_model_projection(EVENT_ASSISTANT_PARTIAL) is True
    assert event_has_model_projection(EVENT_TURN_COMPLETED) is False


def test_conversation_ledger_checkpoint_replaces_covered_history_for_model(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "旧请求不应再逐条进入模型"},
    )
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-old",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": "tool-old", "name": "cli_tool", "status": "done", "result": "旧工具结果"}},
        tool_call_id="tool-old",
    )
    event = append_context_compression_checkpoint(
        tmp_path,
        "session-compress",
        turn_id="turn-new",
        current_turn_id="turn-new",
        summary="旧阶段已经完成：定位到压缩事实源分裂。",
        level="standard",
        reason="context_pressure",
        before_tokens=9000,
        after_tokens=3000,
        iteration=5,
        trigger_source="auto",
    )
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-after",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "checkpoint 后的新请求应保留"},
    )

    messages = conversation_model_messages_from_events(load_conversation_events(tmp_path, "session-compress"))
    contents = "\n".join(str(message.get("content") or "") for message in messages)

    assert event is not None
    assert event.event_type == EVENT_COMPACTION_CHECKPOINT
    assert "旧阶段已经完成" in contents
    assert "checkpoint 后的新请求应保留" in contents
    assert "旧请求不应再逐条进入模型" not in contents
    assert "旧工具结果" not in contents


def test_conversation_ledger_projects_compression_checkpoint_as_visible_marker(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-marker",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "旧请求会被 checkpoint 覆盖"},
    )
    event = append_context_compression_checkpoint(
        tmp_path,
        "session-marker",
        turn_id="turn-checkpoint",
        current_turn_id="turn-current",
        summary="旧阶段已经压缩成摘要。",
        level="standard",
        reason="context_pressure",
        before_tokens=10000,
        after_tokens=4200,
        iteration=2,
        trigger_source="automatic_threshold",
        effectiveness_threshold=0.0,
        effectiveness_ratio=0.58,
        effective=True,
        source_message_count=1,
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-marker"),
        include_model_messages=True,
        include_visible_messages=True,
    )

    assert event is not None
    marker = next(
        message
        for message in projection.visible_messages
        if message.get("metadata", {}).get("kind") == "context_compression_marker"
    )
    assert marker["content"] == ""
    assert marker["metadata"]["status"] == "applied"
    assert marker["metadata"]["title"] == "上下文已压缩"
    assert marker["metadata"]["level"] == "standard"
    assert marker["metadata"]["beforeTokens"] == 10000
    assert marker["metadata"]["afterTokens"] == 4200
    assert marker["metadata"]["savedTokens"] == 5800
    assert marker["metadata"]["summaryAvailable"] is True
    assert "旧阶段已经压缩成摘要" in marker["metadata"]["summaryPreview"]
    assert "历史检查点" not in "\n".join(
        str(message.get("content") or "") for message in projection.visible_messages
    )


def test_history_level_compression_checkpoint_projects_as_visible_marker(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-history-marker",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "历史明细不应作为普通聊天内容保留"},
    )
    event = append_context_compression_checkpoint(
        tmp_path,
        "session-history-marker",
        turn_id="turn-history-checkpoint",
        current_turn_id="turn-current",
        summary="历史阶段 summary for model only。",
        level="history",
        reason="tool_request",
        before_tokens=7000,
        after_tokens=2500,
        trigger_source="tool_request",
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-history-marker"),
        include_model_messages=True,
        include_visible_messages=True,
    )
    marker = next(
        message
        for message in projection.visible_messages
        if message.get("metadata", {}).get("eventId") == event.event_id
    )
    visible_content = "\n".join(
        str(message.get("content") or "") for message in projection.visible_messages
    )
    serialized_model_messages = json.dumps(projection.model_messages, ensure_ascii=False)

    assert marker["content"] == ""
    assert marker["metadata"]["kind"] == "context_compression_marker"
    assert marker["metadata"]["status"] == "applied"
    assert marker["metadata"]["title"] == "上下文已压缩"
    assert marker["metadata"]["level"] == "history"
    assert "历史阶段 summary for model only" in marker["metadata"]["summaryPreview"]
    assert "历史检查点" not in visible_content
    assert "历史阶段 summary for model only" in serialized_model_messages
    assert "context_compression_marker" not in serialized_model_messages
    assert "上下文已压缩" not in serialized_model_messages
    assert "工具请求" not in serialized_model_messages
    assert "历史检查点" not in serialized_model_messages


def test_context_compression_marker_metadata_does_not_enter_model_messages(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-model-marker",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "旧上下文明细"},
    )
    append_context_compression_checkpoint(
        tmp_path,
        "session-model-marker",
        turn_id="turn-checkpoint",
        current_turn_id="turn-current",
        summary="旧上下文 summary for model only。",
        level="standard",
        reason="context_pressure",
        before_tokens=9000,
        after_tokens=3000,
        trigger_source="automatic_threshold",
    )

    messages = conversation_model_messages_from_events(
        load_conversation_events(tmp_path, "session-model-marker")
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "旧上下文 summary for model only" in serialized
    assert "context_compression_marker" not in serialized
    assert "上下文已压缩" not in serialized
    assert "历史检查点" not in serialized


def test_context_compression_low_savings_marker_does_not_cover_history(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-low-savings",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "低收益时仍保留的旧上下文"},
    )
    from core.chat.conversation_ledger import append_context_compression_attempt

    append_context_compression_attempt(
        tmp_path,
        "session-low-savings",
        turn_id="turn-current",
        status="skipped_low_savings",
        summary="压缩摘要收益不足。",
        level="standard",
        reason="context_pressure",
        before_tokens=10000,
        after_tokens=9800,
        trigger_source="automatic_threshold",
        effectiveness_threshold=0.3,
        effectiveness_ratio=0.02,
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-low-savings"),
        include_model_messages=True,
        include_visible_messages=True,
    )
    marker = next(
        message for message in projection.visible_messages
        if message.get("metadata", {}).get("kind") == "context_compression_marker"
    )
    model_text = "\n".join(str(message.get("content") or "") for message in projection.model_messages)

    assert marker["metadata"]["status"] == "skipped_low_savings"
    assert marker["metadata"]["title"] == "压缩未应用 · 收益不足"
    assert "低收益时仍保留的旧上下文" in model_text


def test_context_compression_failure_marker_preserves_model_history(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-failed-compression",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "失败时仍保留的旧上下文"},
    )
    from core.chat.conversation_ledger import append_context_compression_attempt

    append_context_compression_attempt(
        tmp_path,
        "session-failed-compression",
        turn_id="turn-current",
        status="failed_preserved",
        summary="",
        level="standard",
        reason="compressor_error",
        before_tokens=10000,
        after_tokens=10000,
        trigger_source="provider_context_length",
        error_type="RuntimeError",
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-failed-compression"),
        include_model_messages=True,
        include_visible_messages=True,
    )
    marker = next(
        message for message in projection.visible_messages
        if message.get("metadata", {}).get("kind") == "context_compression_marker"
    )
    model_text = "\n".join(str(message.get("content") or "") for message in projection.model_messages)

    assert marker["metadata"]["status"] == "failed_preserved"
    assert marker["metadata"]["title"] == "压缩失败 · 已保留原上下文"
    assert marker["metadata"]["errorType"] == "RuntimeError"
    assert "失败时仍保留的旧上下文" in model_text


def test_conversation_turn_outcome_wrapper_is_idempotent(tmp_path):
    from core.chat.conversation_ledger import (
        append_conversation_turn_outcome,
        conversation_turn_items_from_events,
    )
    from core.llm.types import CanonicalItemIdentity, TurnOutcome

    outcome = TurnOutcome.final_answer(
        identity=CanonicalItemIdentity(
            session_id="session-canonical",
            turn_id="turn-canonical",
            invocation_id="invocation-canonical",
            iteration=0,
            item_id="answer-canonical",
        ),
        text="canonical answer",
    )
    append_conversation_turn_outcome(tmp_path, "session-canonical", "turn-canonical", outcome)
    append_conversation_turn_outcome(tmp_path, "session-canonical", "turn-canonical", outcome)
    items = conversation_turn_items_from_events(
        load_conversation_events(tmp_path, "session-canonical"),
        turn_id="turn-canonical",
    )
    assert len([item for item in items if item.get("itemId") == "answer-canonical"]) == 1
