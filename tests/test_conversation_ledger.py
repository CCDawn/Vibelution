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
    assert messages[1].get("tool_calls")
    assert messages[1]["tool_calls"][0]["id"] == "tool-1"
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


def test_checkpoint_summarized_boundary_covers_only_folded_events(tmp_path):
    """F2 回归②：covered 集合必须等于摘要实际折叠的事件集。

    turn-old-1 的 user/assistant/tool 事件被折叠进摘要；turn-old-2 属于
    kept 窗口——不得进 coveredEventIds，重放后必须仍对模型可见。
    """
    from langchain_core.messages import AIMessage, ToolMessage

    from core.infrastructure.runtime_input import build_chat_user_message

    session_id = "session-summarized-boundary"
    append_conversation_event(
        tmp_path, session_id, "turn-old-1", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "FOLDED-REQUEST 旧请求一"},
    )
    append_conversation_event(
        tmp_path, session_id, "turn-old-1", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "FOLDED-ANSWER 旧回答一"},
    )
    append_conversation_event(
        tmp_path, session_id, "turn-old-1", EVENT_TOOL_RESULT,
        status="done", tool_call_id="tool-folded",
        payload={"toolCall": {"id": "tool-folded", "name": "cli_tool", "status": "done", "result": "FOLDED-TOOL-RESULT 旧工具结果"}},
    )
    append_conversation_event(
        tmp_path, session_id, "turn-old-2", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "KEPT-REQUEST 旧请求二"},
    )
    append_conversation_event(
        tmp_path, session_id, "turn-old-2", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "KEPT-ANSWER 旧回答二"},
    )

    projected = conversation_model_messages_from_events(
        load_conversation_events(tmp_path, session_id)
    )
    summarized = []
    for message in projected:
        role = str(message.get("role") or "")
        if role == "user":
            summarized.append(build_chat_user_message(str(message.get("content") or "")))
        elif role == "assistant":
            summarized.append(AIMessage(content=str(message.get("content") or "")))
        elif role == "tool":
            summarized.append(
                ToolMessage(
                    content=str(message.get("content") or ""),
                    tool_call_id=str(message.get("tool_call_id") or ""),
                )
            )
    # kept 窗口消息显式留在折叠集之外
    def _message_text(message) -> str:
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", "")
        )
        return str(content or "")

    summarized = [message for message in summarized if "KEPT" not in _message_text(message)]

    event = append_context_compression_checkpoint(
        tmp_path,
        session_id,
        turn_id="turn-current",
        current_turn_id="turn-current",
        summary="旧阶段已折叠：FOLDED 部分进摘要。",
        level="standard",
        reason="context_pressure",
        before_tokens=9000,
        after_tokens=3000,
        iteration=5,
        trigger_source="auto",
        summarized_messages=summarized,
    )
    assert event is not None
    payload = dict(event.payload or {})
    events = load_conversation_events(tmp_path, session_id)
    covered_ids = set(payload["coveredEventIds"])
    folded_ids = {
        event_.event_id
        for event_ in events
        if event_.turn_id == "turn-old-1"
    }
    kept_ids = {
        event_.event_id
        for event_ in events
        if event_.turn_id == "turn-old-2"
    }
    assert folded_ids and kept_ids
    assert folded_ids <= covered_ids
    assert kept_ids.isdisjoint(covered_ids)
    # 连续折叠块保留序列范围语义
    assert payload["coveredEventSeqStart"] > 0
    assert payload["coveredEventSeqEnd"] >= payload["coveredEventSeqStart"]

    messages = conversation_model_messages_from_events(events)
    contents = "\n".join(str(message.get("content") or "") for message in messages)
    assert "旧阶段已折叠" in contents
    assert "FOLDED-REQUEST" not in contents
    assert "FOLDED-ANSWER" not in contents
    assert "FOLDED-TOOL-RESULT" not in contents
    # kept 窗口事件未被覆盖，重放仍可见
    assert "KEPT-REQUEST" in contents
    assert "KEPT-ANSWER" in contents


def test_checkpoint_sparse_summarized_boundary_suppresses_sequence_range(tmp_path):
    """稀疏折叠集（kept 事件夹在中间）只写 coveredEventIds，不发布序列范围。

    否则 replay 会把范围内的 kept 事件一并当成已覆盖剔除。
    """
    from langchain_core.messages import AIMessage

    session_id = "session-sparse-boundary"
    append_conversation_event(
        tmp_path, session_id, "turn-a", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "SPARSE-FOLD-ONE 旧请求一"},
    )
    append_conversation_event(
        tmp_path, session_id, "turn-a", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "SPARSE-KEPT-ANSWER 保留回答"},
    )
    append_conversation_event(
        tmp_path, session_id, "turn-b", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "SPARSE-FOLD-TWO 旧请求二"},
    )

    projected = conversation_model_messages_from_events(
        load_conversation_events(tmp_path, session_id)
    )
    summarized = [
        AIMessage(content=str(message.get("content") or ""))
        if str(message.get("role")) == "assistant"
        else {"role": "user", "content": str(message.get("content") or "")}
        for message in projected
        if "KEPT" not in str(message.get("content") or "")
    ]

    event = append_context_compression_checkpoint(
        tmp_path,
        session_id,
        turn_id="turn-current",
        current_turn_id="turn-current",
        summary="稀疏折叠边界检查点。",
        level="standard",
        reason="context_pressure",
        before_tokens=8000,
        after_tokens=3000,
        iteration=3,
        trigger_source="auto",
        summarized_messages=summarized,
    )
    assert event is not None
    payload = dict(event.payload or {})
    events = load_conversation_events(tmp_path, session_id)
    covered_ids = list(payload["coveredEventIds"])
    fold_one = next(event_ for event_ in events if "SPARSE-FOLD-ONE" in str(event_.payload.get("content") or ""))
    fold_two = next(event_ for event_ in events if "SPARSE-FOLD-TWO" in str(event_.payload.get("content") or ""))
    kept_answer = next(event_ for event_ in events if "SPARSE-KEPT-ANSWER" in str(event_.payload.get("content") or ""))
    assert covered_ids == [fold_one.event_id, fold_two.event_id]
    # 稀疏集合不发布 min/max 序列范围
    assert payload["coveredEventSeqStart"] == 0
    assert payload["coveredEventSeqEnd"] == 0

    messages = conversation_model_messages_from_events(events)
    contents = "\n".join(str(message.get("content") or "") for message in messages)
    assert "SPARSE-KEPT-ANSWER" in contents
    assert "SPARSE-FOLD-ONE" not in contents
    assert "SPARSE-FOLD-TWO" not in contents


def test_checkpoint_replacement_survives_next_turn_without_replaying_folded_current_turn(tmp_path):
    session_id = "session-compression-continuation"
    records = [
        ("old", EVENT_USER_MESSAGE, "OLD REQUEST"),
        ("old", EVENT_ASSISTANT_MESSAGE, "OLD ANSWER"),
        ("current", EVENT_USER_MESSAGE, "CURRENT REQUEST"),
        ("current", EVENT_ASSISTANT_MESSAGE, "FOLDED CURRENT WORK"),
        ("current", EVENT_ASSISTANT_MESSAGE, "RETAINED CURRENT WORK"),
    ]
    originals = [
        append_conversation_event(
            tmp_path, session_id, turn, kind, status="completed", payload={"content": text}
        )
        for turn, kind, text in records
    ]
    source = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
    retained = [message for message in source if message["content"] in {"CURRENT REQUEST", "RETAINED CURRENT WORK"}]
    folded = [message for message in source if message not in retained]
    checkpoint = append_context_compression_checkpoint(
        tmp_path, session_id, turn_id="current", current_turn_id="current",
        summary="Summary of old history and completed current work.", level="standard", reason="context_pressure",
        before_tokens=1000, after_tokens=200, summarized_messages=folded,
        source_messages=source, retained_messages=retained,
    )
    assert checkpoint is not None
    assert originals[3].event_id in checkpoint.payload["coveredEventIds"]
    assert originals[2].event_id not in checkpoint.payload["coveredEventIds"]
    append_conversation_event(
        tmp_path, session_id, "current", EVENT_ASSISTANT_MESSAGE,
        status="completed", payload={"content": "FINAL ANSWER AFTER COMPRESSION"},
    )
    append_conversation_event(
        tmp_path, session_id, "next", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "NEXT QUESTION"},
    )
    events = load_conversation_events(tmp_path, session_id)
    replay = conversation_model_messages_from_events(events)
    contents = "\n".join(str(message.get("content") or "") for message in replay)
    assert "OLD REQUEST" not in contents
    assert "FOLDED CURRENT WORK" not in contents
    for text in ["CURRENT REQUEST", "RETAINED CURRENT WORK", "FINAL ANSWER AFTER COMPRESSION", "NEXT QUESTION"]:
        assert text in contents
    # Compression changes only model replay. The original transcript remains available.
    visible = conversation_ledger.conversation_visible_messages_from_events(events)
    assert any("FOLDED CURRENT WORK" in str(message.get("content")) for message in visible)


def test_checkpoint_records_budget_retirement_without_claiming_it_was_summarized(tmp_path):
    session_id = "session-budget-retirement"
    dropped = append_conversation_event(
        tmp_path, session_id, "old", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "BUDGET RETIRED HISTORY"},
    )
    kept = append_conversation_event(
        tmp_path, session_id, "current", EVENT_USER_MESSAGE,
        status="recorded", payload={"content": "PROTECTED CURRENT REQUEST"},
    )
    source = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
    checkpoint = append_context_compression_checkpoint(
        tmp_path, session_id, turn_id="current", current_turn_id="current",
        summary="Existing anchored summary.", level="emergency", reason="token_budget",
        before_tokens=1000, after_tokens=200, summarized_messages=[],
        source_messages=source, retained_messages=[source[-1]],
    )
    assert checkpoint is not None
    assert dropped.event_id in checkpoint.payload["retiredEventIds"]
    assert dropped.event_id not in checkpoint.payload["coveredEventIds"]
    assert kept.event_id not in checkpoint.payload["retiredEventIds"]
    events = load_conversation_events(tmp_path, session_id)
    contents = "\n".join(str(message.get("content")) for message in conversation_model_messages_from_events(events))
    assert "BUDGET RETIRED HISTORY" not in contents
    assert "PROTECTED CURRENT REQUEST" in contents
    assert any(event.event_id == dropped.event_id for event in events)


def test_replacement_checkpoint_retires_previous_summary_and_preserves_duplicate_latest_user(tmp_path):
    session_id = "session-anchored-summary-replacement"
    old_user = append_conversation_event(
        tmp_path, session_id, "old", EVENT_USER_MESSAGE, status="recorded", payload={"content": "SAME USER REQUEST"}
    )
    first = append_context_compression_checkpoint(
        tmp_path, session_id, turn_id="first", current_turn_id="first",
        summary="PREVIOUS ANCHORED SUMMARY", level="standard", reason="context_pressure",
        before_tokens=1000, after_tokens=200,
    )
    current_user = append_conversation_event(
        tmp_path, session_id, "current", EVENT_USER_MESSAGE, status="recorded", payload={"content": "SAME USER REQUEST"}
    )
    source = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
    checkpoint = append_context_compression_checkpoint(
        tmp_path, session_id, turn_id="current", current_turn_id="current",
        summary="NEW ANCHORED SUMMARY", level="standard", reason="context_pressure",
        before_tokens=1000, after_tokens=200,
        summarized_messages=source[:-1], source_messages=source, retained_messages=[source[-1]],
    )
    assert first is not None and checkpoint is not None
    assert first.event_id in checkpoint.payload["coveredEventIds"]
    assert current_user.event_id not in checkpoint.payload["coveredEventIds"]
    events = load_conversation_events(tmp_path, session_id)
    replay = conversation_model_messages_from_events(events)
    contents = "\n".join(str(message.get("content")) for message in replay)
    assert "PREVIOUS ANCHORED SUMMARY" not in contents
    assert "NEW ANCHORED SUMMARY" in contents
    assert len([message for message in replay if message.get("role") == "user" and message.get("content") == "SAME USER REQUEST"]) == 1
    assert any(event.event_id == old_user.event_id for event in events)


@pytest.mark.parametrize("second_text", ["SHORT WITH MORE CONTEXT", "SHORT"])
def test_replacement_does_not_infer_retirement_from_substrings_or_ambiguous_twins(tmp_path, second_text):
    session_id = "session-exact-replacement-boundary"
    first = append_conversation_event(
        tmp_path, session_id, "first", EVENT_USER_MESSAGE, status="recorded", payload={"content": "SHORT"}
    )
    second = append_conversation_event(
        tmp_path, session_id, "second", EVENT_USER_MESSAGE, status="recorded", payload={"content": second_text}
    )
    source = [{"role": "user", "content": "SHORT"}, {"role": "user", "content": second_text}]
    checkpoint = append_context_compression_checkpoint(
        tmp_path, session_id, turn_id="compression", current_turn_id="compression",
        summary="The second request was summarized.", level="standard", reason="context_pressure",
        before_tokens=1000, after_tokens=200,
        summarized_messages=[source[1]], source_messages=source, retained_messages=[source[0]],
    )
    assert checkpoint is not None
    assert first.event_id not in checkpoint.payload["coveredEventIds"]
    assert first.event_id not in checkpoint.payload["retiredEventIds"]
    if second_text != "SHORT":
        assert second.event_id in checkpoint.payload["coveredEventIds"]
    else:
        # Identical text without identity is not proof either event was removed.
        assert checkpoint.payload["coveredEventIds"] == []
        assert checkpoint.payload["retiredEventIds"] == []


def test_checkpoint_protects_ambiguous_retained_message_when_source_has_strong_identity(tmp_path):
    session_id = "session-mixed-retained-identity"
    for turn in ["old", "current"]:
        append_conversation_event(
            tmp_path, session_id, turn, EVENT_USER_MESSAGE,
            status="recorded", payload={"content": "SAME REQUEST"},
        )
    source = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
    checkpoint = append_context_compression_checkpoint(
        tmp_path, session_id, turn_id="current", current_turn_id="current",
        summary="Old request summarized.", level="standard", reason="context_pressure",
        before_tokens=1000, after_tokens=200,
        summarized_messages=[source[0]], source_messages=source,
        retained_messages=[{"role": "user", "content": "SAME REQUEST"}],
    )
    assert checkpoint is not None
    assert checkpoint.payload["coveredEventIds"] == []
    assert checkpoint.payload["retiredEventIds"] == []
    replay = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
    assert len([message for message in replay if message.get("content") == "SAME REQUEST"]) == 2


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


def _append_compression_tool_lifecycle(project_root, session_id, turn_id, call_id):
    started = [
        append_conversation_event(
            project_root, session_id, turn_id, turn_journal.EVENT_TOOL_CALL_STARTED,
            status="running", tool_call_id=call_id,
            payload={"toolCall": {
                "id": call_id, "name": "read_file_tool", "arguments": {"path": "fixture.txt"},
                "status": "running", "result": {}, "error": {},
            }},
        )
        for _ in range(2)
    ]
    result = append_conversation_event(
        project_root, session_id, turn_id, EVENT_TOOL_RESULT,
        status="done", tool_call_id=call_id,
        payload={"toolCall": {
            "id": call_id, "name": "read_file_tool", "arguments": {"path": "fixture.txt"},
            "status": "done", "result": f"RESULT {turn_id} {call_id}",
        }},
    )
    return [*started, result]


@pytest.mark.parametrize("retired", [False, True])
def test_checkpoint_covers_completed_tool_lifecycle_as_one_group(tmp_path, retired):
    session_id = "session-compression-tool-group"
    append_conversation_event(tmp_path, session_id, "old", EVENT_TURN_STARTED, status="running")
    folded = _append_compression_tool_lifecycle(tmp_path, session_id, "old", "folded-call")
    kept = _append_compression_tool_lifecycle(tmp_path, session_id, "old", "kept-call")
    source = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
    folded_messages = [m for m in source if m.get("metadata", {}).get("eventId") == folded[-1].event_id]
    retained = [m for m in source if m not in folded_messages]
    checkpoint = append_context_compression_checkpoint(
        tmp_path, session_id, turn_id="compression", summary="Completed work summary.",
        level="standard", reason="context_pressure", before_tokens=1000, after_tokens=200,
        source_messages=source, retained_messages=retained,
        summarized_messages=[] if retired else folded_messages,
    )
    assert checkpoint is not None
    field = "retiredEventIds" if retired else "coveredEventIds"
    assert {e.event_id for e in folded} <= set(checkpoint.payload[field])
    covered = set(checkpoint.payload["coveredEventIds"]) | set(checkpoint.payload["retiredEventIds"])
    assert covered.isdisjoint(e.event_id for e in kept)
    events = load_conversation_events(tmp_path, session_id)
    replay = conversation_model_messages_from_events(events)
    calls = [call["id"] for m in replay for call in m.get("tool_calls", [])]
    assert calls == ["kept-call"]
    assert {e.event_id for e in folded} <= {e.event_id for e in events}


@pytest.mark.parametrize("boundary", ["coveredEventIds", "retiredEventIds", "sequence_range"])
def test_legacy_checkpoint_does_not_resurrect_completed_tool_starts(tmp_path, boundary):
    from core.chat.context_compression_ledger import apply_context_compression_checkpoints

    session_id = "session-legacy-compression-tool-group"
    append_conversation_event(tmp_path, session_id, "old", EVENT_TURN_STARTED, status="running")
    folded = _append_compression_tool_lifecycle(tmp_path, session_id, "old", "reused-call")
    append_conversation_event(tmp_path, session_id, "kept", EVENT_TURN_STARTED, status="running")
    kept = _append_compression_tool_lifecycle(tmp_path, session_id, "kept", "reused-call")
    unresolved = append_conversation_event(
        tmp_path, session_id, "kept", turn_journal.EVENT_TOOL_CALL_STARTED,
        status="running", tool_call_id="unresolved-call",
        payload={"toolCall": {"id": "unresolved-call", "name": "read_file_tool"}},
    )
    payload = {"summary": "Legacy summary.", "beforeTokens": 1000, "afterTokens": 200}
    if boundary == "sequence_range":
        payload.update(coveredEventSeqStart=folded[-1].sequence, coveredEventSeqEnd=folded[-1].sequence)
    else:
        payload[boundary] = [folded[-1].event_id]
    append_conversation_event(
        tmp_path, session_id, "compression", EVENT_COMPACTION_CHECKPOINT,
        status="applied", payload=payload, visible_in_model=False,
    )
    events = load_conversation_events(tmp_path, session_id)
    replayable = apply_context_compression_checkpoints(events, current_turn_id="next")
    ids = {e.event_id for e in replayable}
    assert ids.isdisjoint(e.event_id for e in folded)
    assert {e.event_id for e in kept} <= ids
    assert unresolved.event_id in ids
    current_ids = {
        e.event_id for e in apply_context_compression_checkpoints(events, current_turn_id="old")
    }
    assert {e.event_id for e in folded} <= current_ids
    replay = conversation_model_messages_from_events(events)
    results = [m for m in replay if m.get("role") == "tool"]
    assert any(m.get("content") == "RESULT kept reused-call" for m in results)
    assert not any(m.get("metadata", {}).get("eventId") in {e.event_id for e in folded} for m in replay)


def test_checkpoint_preserves_starts_when_same_turn_call_has_an_uncovered_result(tmp_path):
    from core.chat.context_compression_ledger import apply_context_compression_checkpoints

    session_id = "session-compression-repeated-call-identity"
    append_conversation_event(tmp_path, session_id, "old", EVENT_TURN_STARTED, status="running")
    first = _append_compression_tool_lifecycle(tmp_path, session_id, "old", "shared-call")
    second = _append_compression_tool_lifecycle(tmp_path, session_id, "old", "shared-call")
    append_conversation_event(
        tmp_path, session_id, "compression", EVENT_COMPACTION_CHECKPOINT,
        status="applied", payload={"summary": "Partial boundary.", "coveredEventIds": [first[-1].event_id]},
        visible_in_model=False,
    )
    replayable = apply_context_compression_checkpoints(load_conversation_events(tmp_path, session_id))
    ids = {e.event_id for e in replayable}
    assert {e.event_id for e in [*first[:-1], *second]} <= ids


def test_checkpoint_preserves_later_unresolved_start_reusing_covered_call_id(tmp_path):
    from core.chat.context_compression_ledger import apply_context_compression_checkpoints

    session_id = "session-compression-later-tool-start"
    append_conversation_event(tmp_path, session_id, "old", EVENT_TURN_STARTED, status="running")
    completed = _append_compression_tool_lifecycle(tmp_path, session_id, "old", "shared-call")
    later = append_conversation_event(
        tmp_path, session_id, "old", turn_journal.EVENT_TOOL_CALL_STARTED,
        status="running", tool_call_id="shared-call",
        payload={"toolCall": {"id": "shared-call", "name": "read_file_tool"}},
    )
    append_conversation_event(
        tmp_path, session_id, "compression", EVENT_COMPACTION_CHECKPOINT,
        status="applied", payload={"summary": "Completed call.", "coveredEventIds": [completed[-1].event_id]},
        visible_in_model=False,
    )
    replayable = apply_context_compression_checkpoints(load_conversation_events(tmp_path, session_id))
    ids = {e.event_id for e in replayable}
    assert ids.isdisjoint(e.event_id for e in completed)
    assert later.event_id in ids
