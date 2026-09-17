"""Invariant tests for stream_capture's documented capture contract.

对应 core/web/services/session/stream_capture.py 模块头 docstring 的五条不变量；
只锁定既有行为，不重构实现。
"""

from __future__ import annotations

import random
from types import SimpleNamespace

from core.infrastructure.event_bus import EventNames, get_event_bus
from core.web.services import session_service
from core.web.services.session import stream_capture


# 安全字母表：不含 markup/括号/控制标记，真实 sanitizer 对其近似恒等，
# 保证随机序列测的是 capture 不变量本身而不是清洗边角。
_THOUGHT_LETTERS = "abcdefghijklmnopqrstuvwxyz0123456789思考推理检查日志投影顺序边界"


def _random_word(rng: random.Random) -> str:
    return "".join(rng.choice(_THOUGHT_LETTERS) for _ in range(rng.randint(2, 10)))


def _random_block(rng: random.Random) -> str:
    """生成首尾非空白、不含连续换行的随机文本块。"""

    words = [_random_word(rng) for _ in range(rng.randint(1, 5))]
    separator = " " if rng.random() < 0.7 else "\n"
    return separator.join(words)


def _publish_stream_restart(session_id: str, turn_id: str, attempt: int = 2) -> None:
    get_event_bus().publish(
        EventNames.LLM_STATUS,
        {
            "status": "retrying",
            "streamRestart": attempt,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    )


def _stub_ui(monkeypatch) -> SimpleNamespace:
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)
    return stub_ui


def _stub_journal(monkeypatch) -> tuple[list[dict], list[str]]:
    """记录 journal 追加并在物品查询里回放已写入 itemId（模拟持久层幂等）。"""

    payloads: list[dict] = []
    item_ids: list[str] = []
    monkeypatch.setattr(session_service, "load_conversation_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [{"itemId": item_id} for item_id in item_ids],
    )
    monkeypatch.setattr(session_service, "_invalidate_session_conversation_events_cache", lambda _sid: None)

    def _append(_session_id, _turn_id, _event_type, **kwargs):
        payload = dict(kwargs.get("payload") or {})
        payloads.append(payload)
        if payload.get("itemId"):
            item_ids.append(str(payload["itemId"]))
        return True

    monkeypatch.setattr(session_service, "_append_session_conversation_event", _append)
    return payloads, item_ids


def test_random_thought_deltas_keep_sequence_watermark_and_prefix_invariants() -> None:
    """不变量 (1)(2)：随机 delta 流下序号严格递增、水位单调、文本前缀延伸。"""

    rng = random.Random(20260917)
    capture = stream_capture.SessionTurnCapture(session_id="inv-seq", turn_id="inv-seq-t")

    seen_sequences: set[int] = set()
    max_sequence = 0
    prev_thought = ""

    def absorb_new_events() -> None:
        nonlocal max_sequence
        for event in capture.feedback_events:
            sequence = int(event["sequence"])
            if sequence in seen_sequences:
                continue
            assert sequence > max_sequence, "feedback sequence 必须严格递增分配"
            seen_sequences.add(sequence)
            max_sequence = sequence

    def check_uncommitted_matches_watermark() -> None:
        watermark = capture._last_committed_thought_sequence
        assert capture.uncommitted_thought_events() == [
            event
            for event in capture.feedback_events
            if event.get("kind") == "thought" and int(event["sequence"]) > watermark
        ]

    for _ in range(240):
        action = rng.random()
        if action < 0.55:
            if rng.random() < 0.4 and capture.thought:
                delta = capture.thought + _random_block(rng)  # 快照式前缀延伸
            else:
                delta = _random_block(rng)  # 追加式增量
            thought_before = capture.thought
            capture.note_thought(delta)
            assert capture.thought.startswith(thought_before)
            segment = capture._latest_thought_text
            if segment:
                assert capture.thought.endswith(segment)
        elif action < 0.65:
            capture.close_latest_thought_boundary()
            assert capture._latest_thought_sequence == 0
            assert capture._latest_thought_text == ""
        else:
            reserved = capture.reserve_feedback_sequence()
            assert reserved > max_sequence
            seen_sequences.add(reserved)
            max_sequence = reserved
        absorb_new_events()
        check_uncommitted_matches_watermark()
        if rng.random() < 0.4:
            pending = capture.uncommitted_thought_events()
            if pending:
                watermark_before = capture._last_committed_thought_sequence
                capture.mark_thought_events_committed(int(pending[-1]["sequence"]))
                assert capture._last_committed_thought_sequence >= watermark_before
                # 过期（更小）的提交水位不得回退
                capture.mark_thought_events_committed(max(0, watermark_before - 1))
                assert capture._last_committed_thought_sequence >= watermark_before
                check_uncommitted_matches_watermark()

    # 收尾提交：水位追平最大 thought 序号，uncommitted 清空
    capture.close_latest_thought_boundary()
    pending = capture.uncommitted_thought_events()
    if pending:
        capture.mark_thought_events_committed(max(int(event["sequence"]) for event in pending))
    thought_sequences = [
        int(event["sequence"]) for event in capture.feedback_events if event.get("kind") == "thought"
    ]
    assert thought_sequences
    assert capture._last_committed_thought_sequence == max(thought_sequences)
    assert capture.uncommitted_thought_events() == []
    assert max(seen_sequences) == capture._next_feedback_sequence - 1


def test_random_content_snapshots_keep_committed_length_bounded() -> None:
    """不变量 (4)：单调增长的 content 快照下，提交长度有界且不重发已提交前缀。"""

    rng = random.Random(424242)
    capture = stream_capture.SessionTurnCapture(session_id="inv-content", turn_id="inv-content-t")
    snapshot = ""
    previous_visible = ""
    for _ in range(200):
        snapshot = snapshot + _random_block(rng) if snapshot else _random_block(rng)
        capture.note_content(snapshot)
        visible = session_service._sanitize_message_content("assistant", snapshot)
        assert capture.content == visible
        # 快照单调不减：整快照替换语义下可见文本前缀延伸
        assert capture.content.startswith(previous_visible)
        previous_visible = visible
        committed = capture._committed_content_length
        assert 0 <= committed <= len(capture.content)
        segment = capture.uncommitted_content_segment()
        assert segment == capture.content[committed:].strip()
        if rng.random() < 0.45:
            capture.mark_content_committed()
            assert capture._committed_content_length == len(capture.content)
            assert capture.uncommitted_content_segment() == ""

    capture.mark_content_committed()
    assert capture._committed_content_length == len(capture.content)
    assert capture.uncommitted_content_segment() == ""


def test_stream_restart_keeps_committed_watermark_and_journals_replay_once(monkeypatch) -> None:
    """不变量 (5)：restart 丢 in-progress、保已提交水位；重试重放不重复写 journal。"""

    payloads, _item_ids = _stub_journal(monkeypatch)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *a, **kw: None)
    monkeypatch.setattr(session_service, "_set_session_llm_status_live_output", lambda *a, **kw: None)
    _stub_ui(monkeypatch)

    session_id, turn_id = "inv-restart", "inv-restart-t"
    capture = stream_capture.SessionTurnCapture(session_id=session_id, turn_id=turn_id)
    committed_text = "第一段推理：检查日志与投影顺序。"
    retry_text = "第二段推理：重试生成的推理内容。"

    with stream_capture._capture_session_ui_stream(session_id, capture):
        capture.note_thought(committed_text)
        capture.close_latest_thought_boundary()
        assert (
            stream_capture._commit_session_capture_reasoning_segments(
                session_id, capture, source="test_restart_invariant"
            )
            == 1
        )
        committed_sequence = capture._last_committed_thought_sequence
        assert committed_sequence > 0

        # 已完成工具先入；注意 note_tool_event 会关闭进行中 thought 段，
        # 因此被 restart 移除的 running thought 必须在工具事件之后才 note。
        capture.note_tool_event("read_log", "done", call_id="call-done", result="ok")
        capture.note_tool_event("web_search", "running", call_id="call-stale")
        capture.note_thought(retry_text)
        assert capture._latest_thought_sequence > committed_sequence
        assert len(capture.uncommitted_thought_events()) == 1
        capture.note_content("失败 attempt 的部分回答")

        _publish_stream_restart(session_id, turn_id)

        # 已提交侧：水位、已提交事件、已完成工具全部保留
        assert capture._last_committed_thought_sequence == committed_sequence
        kept_thoughts = [event for event in capture.feedback_events if event.get("kind") == "thought"]
        assert [int(event["sequence"]) for event in kept_thoughts] == [committed_sequence]
        assert capture.uncommitted_thought_events() == []
        assert [str(entry.get("callId")) for entry in capture.tool_calls] == ["call-done"]
        # in-progress 侧：pending thought、累积文本、未提交内容水位、running 工具全部丢弃
        assert capture.thought == ""
        assert capture.content == ""
        assert capture._committed_content_length == 0
        assert capture._latest_thought_sequence == 0
        assert capture._latest_thought_text == ""
        # 去重记忆指向被移除的 running thought → 一并重置
        assert capture._last_recorded_thought_sequence == 0
        assert capture._last_recorded_thought_text == ""

        # 重试 attempt 重放未提交段：作为新段提交，journal 恰好一次
        capture.note_thought(retry_text)
        capture.close_latest_thought_boundary()
        assert (
            stream_capture._commit_session_capture_reasoning_segments(
                session_id, capture, source="test_restart_invariant"
            )
            == 1
        )
        # 同段再次重放：判重只标记边界，不新建事件、不再提交
        capture.note_thought(retry_text)
        thought_events = [event for event in capture.feedback_events if event.get("kind") == "thought"]
        assert len(thought_events) == 2
        assert (
            stream_capture._commit_session_capture_reasoning_segments(
                session_id, capture, source="test_restart_invariant"
            )
            == 0
        )

    reasoning_payloads = [payload for payload in payloads if payload.get("kind") == "reasoning"]
    assert [payload.get("text") for payload in reasoning_payloads] == [committed_text, retry_text]
    assert len({payload.get("itemId") for payload in reasoning_payloads}) == 2


def test_thought_dedupe_thresholds_and_boundary_mark_only() -> None:
    """不变量 (3)：48 字符 / 85% 包含比分界；判重只标记边界不改事件。"""

    capture = stream_capture.SessionTurnCapture(session_id="inv-dedupe", turn_id="inv-dedupe-t")

    # 47/48 字符分界：真包含但不足 48 字符不判重；完全相等不受长度门槛约束
    capture._last_recorded_thought_text = "y" + "x" * 48
    assert capture._is_repeated_recorded_thought("x" * 48)
    assert not capture._is_repeated_recorded_thought("x" * 47)
    capture._last_recorded_thought_text = "ab"
    assert capture._is_repeated_recorded_thought("ab")

    # 84%/85% 包含比分界（100 字符前文中包含 84/85 字符）
    capture._last_recorded_thought_text = "x" * 100
    assert not capture._is_repeated_recorded_thought("x" * 84)
    assert capture._is_repeated_recorded_thought("x" * 85)

    # 判重命中时只回指旧段：feedback_events 原样，不新建 thought 事件
    replay_capture = stream_capture.SessionTurnCapture(session_id="inv-dedupe-2", turn_id="inv-dedupe-2-t")
    segment_text = "第一段推理内容，用于建立去重记忆。" + "细节补充" * 10
    replay_capture.note_thought(segment_text)
    replay_capture.close_latest_thought_boundary()
    events_before = [dict(event) for event in replay_capture.feedback_events]
    recorded_sequence = replay_capture._last_recorded_thought_sequence
    assert recorded_sequence > 0

    replay_capture.note_thought(segment_text)  # 原文重放
    assert [dict(event) for event in replay_capture.feedback_events] == events_before
    assert replay_capture._pending_related_thought_sequence == recorded_sequence

    whitespace_capture = stream_capture.SessionTurnCapture(session_id="inv-dedupe-3", turn_id="inv-dedupe-3-t")
    whitespace_capture.note_thought("abc  def")
    whitespace_capture.close_latest_thought_boundary()
    events_before = [dict(event) for event in whitespace_capture.feedback_events]
    recorded_sequence = whitespace_capture._last_recorded_thought_sequence

    whitespace_capture.note_thought("abc def")  # 归一化相等但不等原文，仍判重
    assert [dict(event) for event in whitespace_capture.feedback_events] == events_before
    assert whitespace_capture._pending_related_thought_sequence == recorded_sequence
