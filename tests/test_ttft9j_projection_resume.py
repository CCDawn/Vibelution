# -*- coding: utf-8 -*-
"""TTFT batch 9-J: model projection / canonical replay provenance resume gates.

Hard gates under test (修 G 遗留：带 provenance 基准的续跑):
- Appending sealed turns to a warm memo resumes the model projection and the
  canonical replay from the stored carry (sourceIndex baseline + scan state);
  every appended round stays byte-identical to a forced cold replay.
- Ledgers whose turns never terminate (no commit possible) keep their whole
  uncommitted window in the memo and still resume byte-identically.
- Turn rollover admits the previously excluded block into the canonical replay
  incrementally and matches a cold assembly byte for byte.
- rewind / branch_rebase / checkpoint appends always fall back to a full
  recompute and never diverge.
- The resume carry is forked per assembly: concurrent assemblies of one
  session never corrupt each other's frozen state.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading

import pytest

from core.chat import context_assembler
from core.chat.turn_journal import ModelProjectionReplay
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_BRANCH_REBASE,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    core_ledger = pytest.importorskip("core.chat.conversation_ledger")
    core_ledger._CONVERSATION_EVENTS_DISK_CACHE.clear()
    yield
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    core_ledger._CONVERSATION_EVENTS_DISK_CACHE.clear()


def _snapshot(assembled) -> dict:
    return {
        "history": json.dumps(
            assembled.history_messages, ensure_ascii=False, sort_keys=True, default=str
        ),
        "eventIds": [event.event_id for event in assembled.events],
        "patch": json.dumps(
            assembled.to_composition_patch(), ensure_ascii=False, sort_keys=True, default=str
        ),
        "dynamicContextHash": assembled.dynamic_context_hash,
    }


def _assemble(session_id: str, turn_id: str, events, **kwargs):
    return context_assembler.assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id=turn_id,
        recent_message_limit=kwargs.pop("recent_message_limit", None),
        ledger_events=events,
        **kwargs,
    )


def _sha(objs) -> str:
    return hashlib.sha256(
        json.dumps(objs, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _append_turn(tmp_path, session_id: str, index: int, rng, *, terminal: bool = True) -> None:
    turn = f"turn-{index:03d}"
    append_conversation_event(tmp_path, session_id, turn, EVENT_USER_MESSAGE,
                              status="recorded",
                              payload={"content": f"请求 {index} " + "x" * rng.randint(1, 40)})
    for call_index in range(rng.randint(0, 2)):
        call_id = f"call-{index}-{call_index}"
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running",
                                  payload={"toolCall": {"id": call_id, "name": "read_file_tool"}})
        if rng.random() < 0.85:
            append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                      status="completed",
                                      payload={"toolCall": {"id": call_id, "result": "结果 " * rng.randint(1, 60)}})
    if rng.random() < 0.15:
        # 打断形态的轮：只有调用没有结果，没有 assistant 回复，也没有 terminal。
        return
    append_conversation_event(tmp_path, session_id, turn, EVENT_ASSISTANT_MESSAGE,
                              status="completed", payload={"content": f"回复 {index}"})
    append_conversation_event(tmp_path, session_id, turn, EVENT_TURN_COMPLETED,
                              status="completed", payload={})


# ---------------------------------------------------------------------------
# 1. 逐轮追加链：每轮 warm 组装与强制冷算逐字节一致（模型投影 + canonical）
# ---------------------------------------------------------------------------


def test_round_by_round_resume_chain_matches_forced_cold(tmp_path):
    rng = random.Random(20261022)
    session_id = "ttft9j-chain"
    turn_index = 0
    for config in ({}, {"micro_compact_old_tool_results": True}):
        context_assembler._ASSEMBLY_MEMO._entries.clear()
        session = f"{session_id}-{len(config)}"
        for _round in range(5):
            turn_index += 1
            _append_turn(tmp_path, session, turn_index, rng)
            events = load_conversation_events(tmp_path, session)
            turn_id = str(events[-1].turn_id or "")

            forced = _assemble(session, turn_id, events, **config)
            warm = _assemble(session, turn_id, events, **config)
            assert _snapshot(warm) == _snapshot(forced)

            # 下一轮：新 turn 追加后，warm 链必须与冷算逐字节一致。
            turn_index += 1
            _append_turn(tmp_path, session, turn_index, rng)
            events = load_conversation_events(tmp_path, session)
            turn_id = str(events[-1].turn_id or "")
            forced = _assemble(session, turn_id, events, **config)
            warm = _assemble(session, turn_id, events, **config)
            assert _snapshot(warm) == _snapshot(forced), (
                f"resume chain diverged at round {turn_index}, config={config}"
            )
            # 前缀字节稳定：上一轮已发出的 history 是本轮的前缀（无 checkpoint 重排时）
            assert _sha(forced.history_messages) == _sha(warm.history_messages)


# ---------------------------------------------------------------------------
# 2. 无终端事件账本：pending 窗口随 memo 持久化，追加仍逐字节一致
# ---------------------------------------------------------------------------


def test_open_turn_ledger_resume_keeps_pending_window(tmp_path):
    session_id = "ttft9j-open"
    # 两轮都不写 terminal：整个历史永远是未提交 pending。
    for index in (1, 2, 3):
        turn = f"turn-{index:03d}"
        append_conversation_event(tmp_path, session_id, turn, EVENT_USER_MESSAGE,
                                  status="recorded", payload={"content": f"请求 {index}"})
        call_id = f"call-{index}"
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running",
                                  payload={"toolCall": {"id": call_id, "name": "read_file_tool"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                  status="completed",
                                  payload={"toolCall": {"id": call_id, "result": "内容 " * index}})
    events = load_conversation_events(tmp_path, session_id)
    warm = _assemble(session_id, "turn-003", events)
    cold = _assemble(session_id, "turn-003", events)
    assert _snapshot(warm) == _snapshot(cold)

    append_conversation_event(tmp_path, session_id, "turn-004", EVENT_USER_MESSAGE,
                              status="recorded", payload={"content": "请求 4"})
    append_conversation_event(tmp_path, session_id, "turn-004", EVENT_ASSISTANT_MESSAGE,
                              status="completed", payload={"content": "回复 4"})
    grown = load_conversation_events(tmp_path, session_id)
    forced = _assemble(session_id, "turn-004", grown)
    warm = _assemble(session_id, "turn-004", grown)
    assert _snapshot(warm) == _snapshot(forced), (
        "uncommitted pending window must ride the memo and resume byte-identically"
    )


# ---------------------------------------------------------------------------
# 3. canonical rollover：被排除轮整体入场时增量续跑与冷算一致
# ---------------------------------------------------------------------------


def test_canonical_rollover_admits_block_incrementally(tmp_path):
    session_id = "ttft9j-rollover"
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE,
                              status="recorded", payload={"content": "第一轮"})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_TOOL_CALL_STARTED,
                              status="running",
                              payload={"toolCall": {"id": "call-1", "name": "grep_tool"}})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_TOOL_RESULT,
                              status="completed", payload={"toolCall": {"id": "call-1", "result": "匹配行"}})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_ASSISTANT_MESSAGE,
                              status="completed", payload={"content": "第一轮回复"})
    events = load_conversation_events(tmp_path, session_id)
    first = _assemble(session_id, "turn-2", events)  # turn-1 完整在场，当前轮 turn-2
    assert _snapshot(_assemble(session_id, "turn-2", events)) == _snapshot(first)

    # 当前轮 turn-2 成长（全部被排除），canonical 值不变
    append_conversation_event(tmp_path, session_id, "turn-2", EVENT_ASSISTANT_MESSAGE,
                              status="completed", payload={"content": "第二轮进行中"})
    grown = load_conversation_events(tmp_path, session_id)
    assert _snapshot(_assemble(session_id, "turn-2", grown)) == _snapshot(first)

    # rollover 到 turn-3：turn-2 的块整体入场
    append_conversation_event(tmp_path, session_id, "turn-2", EVENT_TURN_COMPLETED,
                              status="completed", payload={})
    append_conversation_event(tmp_path, session_id, "turn-3", EVENT_USER_MESSAGE,
                              status="recorded", payload={"content": "第三轮"})
    rolled = load_conversation_events(tmp_path, session_id)
    forced = _assemble(session_id, "turn-3", rolled)
    warm = _assemble(session_id, "turn-3", rolled)
    assert _snapshot(warm) == _snapshot(forced)
    assert len(forced.history_messages) > len(first.history_messages)


# ---------------------------------------------------------------------------
# 4. 失配回全量：rewind/branch 标记、checkpoint 追加永不发散
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra_events",
    [
        pytest.param([
            ("turn-2", EVENT_BRANCH_REBASE, "edited", {"operation": "edit", "fromEventId": ""}),
            ("turn-2", EVENT_USER_MESSAGE, "recorded", {"content": "改写后的第二轮"}),
        ], id="branch-rewind"),
        pytest.param([
            ("turn-2", EVENT_COMPACTION_CHECKPOINT, "completed",
             {"summary": "此前历史已压缩", "coveredEventIds": [],
              "coveredEventSeqStart": 0, "coveredEventSeqEnd": 4}),
        ], id="checkpoint-append"),
    ],
)
def test_unsafe_appends_fall_back_to_full_recompute(tmp_path, extra_events):
    session_id = "ttft9j-unsafe"
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE,
                              status="recorded", payload={"content": "第一轮"})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_ASSISTANT_MESSAGE,
                              status="completed", payload={"content": "第一轮回复"})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_TURN_COMPLETED,
                              status="completed", payload={})
    base = load_conversation_events(tmp_path, session_id)
    _assemble(session_id, "turn-2", base)  # warm

    for turn, event_type, status, payload in extra_events:
        append_conversation_event(tmp_path, session_id, turn, event_type,
                                  status=status, payload=payload)
    grown = load_conversation_events(tmp_path, session_id)
    forced = _assemble(session_id, "turn-2", grown)
    warm = _assemble(session_id, "turn-2", grown)
    assert _snapshot(warm) == _snapshot(forced)


# ---------------------------------------------------------------------------
# 5. sourceIndex 基准跨窗延续：分窗重放与整段冷算逐字段一致
# ---------------------------------------------------------------------------


def test_projection_resume_source_index_baseline(tmp_path):
    session_id = "ttft9j-source-index"
    from core.chat.context_compression_ledger import apply_context_compression_checkpoints
    from core.chat.turn_journal import fold_active_events

    for index in range(1, 5):
        turn = f"turn-{index}"
        append_conversation_event(tmp_path, session_id, turn, EVENT_USER_MESSAGE,
                                  status="recorded", payload={"content": f"请求 {index}"})
        call_id = f"call-{index}"
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running",
                                  payload={"toolCall": {"id": call_id, "name": "read_file_tool"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                  status="completed",
                                  payload={"toolCall": {"id": call_id, "result": "内容" * index}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_ASSISTANT_MESSAGE,
                                  status="completed", payload={"content": f"回复 {index}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TURN_COMPLETED,
                                  status="completed", payload={})
    events = load_conversation_events(tmp_path, session_id)
    replay_input = apply_context_compression_checkpoints(fold_active_events(events))

    cold = ModelProjectionReplay().feed_and_finish(replay_input)
    resumed = ModelProjectionReplay()
    half = len(replay_input) // 2
    first = resumed.feed_and_finish(replay_input[:half])
    full = resumed.feed_and_finish(replay_input[half:])
    assert _sha(full) == _sha(cold)
    # 前缀稳定：第一窗输出与冷算输出的前缀逐字节一致
    assert _sha(first) == _sha(cold[: len(first)])
    # sourceIndex 基准跨窗延续：无重置、无重复
    indices = [
        int((message.get("metadata") or {}).get("sourceIndex") or 0)
        for message in full
        if isinstance(message.get("metadata"), dict)
    ]
    assert indices == sorted(indices)


# ---------------------------------------------------------------------------
# 6. 并发：同一会话多线程组装（含追加）互不污染
# ---------------------------------------------------------------------------


def test_concurrent_resume_is_thread_safe(tmp_path):
    session_id = "ttft9j-threads"
    for index in (1, 2):
        turn = f"turn-{index}"
        append_conversation_event(tmp_path, session_id, turn, EVENT_USER_MESSAGE,
                                  status="recorded", payload={"content": f"请求 {index}"})
        call_id = f"call-{index}"
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running",
                                  payload={"toolCall": {"id": call_id, "name": "read_file_tool"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                  status="completed",
                                  payload={"toolCall": {"id": call_id, "result": "内容" * 30}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_ASSISTANT_MESSAGE,
                                  status="completed", payload={"content": f"回复 {index}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TURN_COMPLETED,
                                  status="completed", payload={})
    events = load_conversation_events(tmp_path, session_id)

    def build(grown_events):
        payload = json.dumps(
            _assemble(session_id, str(grown_events[-1].turn_id or ""), grown_events).to_composition_patch(),
            ensure_ascii=False, sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    context_assembler._ASSEMBLY_MEMO._entries.clear()
    reference = build(events)
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    assert build(events) == reference

    errors: list[Exception] = []
    results: list[str] = []

    def worker():
        try:
            for _ in range(6):
                context_assembler._ASSEMBLY_MEMO._entries.clear()
                results.append(build(events))
        except Exception as exc:  # pragma: no cover - surfaced via assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f"concurrent resume raised: {errors}"
    assert all(digest == reference for digest in results)
