# -*- coding: utf-8 -*-
"""TTFT batch 8-G: context assembler prefix-identity memo regression gates.

Hard gates under test:
- Unchanged journal state re-assembles from the memo with zero projection
  replays and byte-identical output (warm vs forced cold).
- Mid-turn journal growth of the *current* turn never changes the assembled
  history window and reuses the cached projections.
- Growth across turn rollovers, rewind/edit markers, and compression
  checkpoints always reassembles byte-identically to a forced cold recompute
  (the append-only fast path may fall back, but never diverges).
- The incremental history-event builder produces exactly the events a full
  ``build_history_events`` replay produces, prefix-stable across appends.
- Concurrent assemblies of one session share memo state without corrupting
  results.
"""

from __future__ import annotations

import json
import random
import threading

import pytest

from core.chat import context_assembler
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


def _cold_and_warm(session_id: str, events, **kwargs):
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    forced = _assemble(session_id, str(events[-1].turn_id or ""), events, **kwargs)
    forced_snap = _snapshot(forced)
    warm = _assemble(session_id, str(events[-1].turn_id or ""), events, **kwargs)
    return forced_snap, _snapshot(warm)


# ---------------------------------------------------------------------------
# 1. unchanged state: memo hit with zero replays
# ---------------------------------------------------------------------------


def test_unchanged_state_reuses_projections_without_replay(tmp_path, monkeypatch):
    session_id = "ttft8g-unchanged"
    for turn in ("turn-1", "turn-2"):
        append_conversation_event(tmp_path, session_id, turn, EVENT_USER_MESSAGE,
                                  status="recorded", payload={"content": f"请求 {turn}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running", payload={"toolCall": {"id": f"call-{turn}", "name": "read_file_tool"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                  status="completed", payload={"toolCall": {"id": f"call-{turn}", "result": "文件内容" * 40}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_ASSISTANT_MESSAGE,
                                  status="completed", payload={"content": f"回复 {turn}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TURN_COMPLETED,
                                  status="completed", payload={})
    events = load_conversation_events(tmp_path, session_id)

    replays = {"count": 0}
    original = context_assembler.conversation_model_messages_from_events

    def counting(events_arg, **kwargs):
        replays["count"] += 1
        return original(events_arg, **kwargs)

    monkeypatch.setattr(context_assembler, "conversation_model_messages_from_events", counting)

    forced_snap, warm_snap = _cold_and_warm(session_id, events)
    assert warm_snap == forced_snap
    assert replays["count"] == 1, "unchanged journal state must hit the memo without replay"


# ---------------------------------------------------------------------------
# 2. mid-turn growth of the current turn never changes the history window
# ---------------------------------------------------------------------------


def test_midturn_current_turn_growth_keeps_window_and_reuses(tmp_path, monkeypatch):
    session_id = "ttft8g-midturn"
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE,
                              status="recorded", payload={"content": "第一轮"})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_ASSISTANT_MESSAGE,
                              status="completed", payload={"content": "第一轮回复"})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_TURN_COMPLETED,
                              status="completed", payload={})
    append_conversation_event(tmp_path, session_id, "turn-2", EVENT_USER_MESSAGE,
                              status="recorded", payload={"content": "第二轮"})
    events = load_conversation_events(tmp_path, session_id)

    first = _assemble(session_id, "turn-2", events)
    first_snap = _snapshot(first)

    # Current-turn events land mid-turn; the historical window must not move.
    append_conversation_event(tmp_path, session_id, "turn-2", EVENT_TOOL_CALL_STARTED,
                              status="running", payload={"toolCall": {"id": "call-2", "name": "grep_tool"}})
    append_conversation_event(tmp_path, session_id, "turn-2", EVENT_TOOL_RESULT,
                              status="completed", payload={"toolCall": {"id": "call-2", "result": "匹配行"}})
    grown = load_conversation_events(tmp_path, session_id)
    assert len(grown) > len(events)

    second = _assemble(session_id, "turn-2", grown)
    assert _snapshot(second) == first_snap, "current-turn growth must not change assembled history"

    # And the memo path agrees with a forced cold recompute.
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    third = _assemble(session_id, "turn-2", grown)
    assert _snapshot(third) == first_snap


# ---------------------------------------------------------------------------
# 3. turn rollover / markers / checkpoints: warm chain == forced cold, always
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra_events",
    [
        pytest.param([], id="plain-rollover"),
        pytest.param([
            ("turn-3", EVENT_USER_MESSAGE, "recorded", {"content": "第三轮"}),
            ("turn-3", EVENT_ASSISTANT_MESSAGE, "completed", {"content": "第三轮回复"}),
            ("turn-3", EVENT_TURN_COMPLETED, "completed", {}),
        ], id="two-rollover"),
        pytest.param([
            ("turn-2", EVENT_BRANCH_REBASE, "edited", {"operation": "edit", "fromEventId": ""}),
            ("turn-2", EVENT_USER_MESSAGE, "recorded", {"content": "改写后的第二轮"}),
            ("turn-2", EVENT_ASSISTANT_MESSAGE, "completed", {"content": "改写回复"}),
        ], id="edit-marker"),
        pytest.param([
            ("turn-2", EVENT_COMPACTION_CHECKPOINT, "completed",
             {"summary": "此前历史已压缩", "coveredEventIds": [], "coveredEventSeqStart": 0, "coveredEventSeqEnd": 3}),
        ], id="checkpoint-append"),
    ],
)
def test_growth_always_matches_forced_recompute(tmp_path, extra_events):
    session_id = "ttft8g-growth"
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE,
                              status="recorded", payload={"content": "第一轮"})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_ASSISTANT_MESSAGE,
                              status="completed", payload={"content": "第一轮回复"})
    append_conversation_event(tmp_path, session_id, "turn-1", EVENT_TURN_COMPLETED,
                              status="completed", payload={})
    base = load_conversation_events(tmp_path, session_id)
    _cold_and_warm(session_id, base)  # warm the memo on the base state

    for turn, event_type, status, payload in extra_events:
        append_conversation_event(tmp_path, session_id, turn, event_type,
                                  status=status, payload=payload)
    grown = load_conversation_events(tmp_path, session_id)

    forced_snap, warm_snap = _cold_and_warm(session_id, grown)
    assert warm_snap == forced_snap


# ---------------------------------------------------------------------------
# 4. incremental history events: prefix-stable and equal to a full replay
# ---------------------------------------------------------------------------


def test_history_events_delta_matches_full_replay(tmp_path):
    session_id = "ttft8g-events"
    full_events = []
    for turn in ("turn-1", "turn-2"):
        append_conversation_event(tmp_path, session_id, turn, EVENT_USER_MESSAGE,
                                  status="recorded", payload={"content": f"请求 {turn}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running", payload={"toolCall": {"id": f"call-{turn}-a", "name": "read_file_tool"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                  status="completed", payload={"toolCall": {"id": f"call-{turn}-a", "result": "内容"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running", payload={"toolCall": {"id": f"call-{turn}-b", "name": "grep_tool"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                  status="completed", payload={"toolCall": {"id": f"call-{turn}-b", "result": "匹配"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_ASSISTANT_MESSAGE,
                                  status="completed", payload={"content": f"回复 {turn}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TURN_COMPLETED,
                                  status="completed", payload={})
        full_events = load_conversation_events(tmp_path, session_id)

    half = [event for event in full_events if event.turn_id == "turn-1"]
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    half_assembled = _assemble(session_id, "turn-2", half)
    half_ids = [event.event_id for event in half_assembled.events]
    warm = _assemble(session_id, "turn-2", full_events)
    context_assembler._ASSEMBLY_MEMO._entries.clear()
    cold = _assemble(session_id, "turn-2", full_events)

    warm_ids = [event.event_id for event in warm.events]
    cold_ids = [event.event_id for event in cold.events]
    assert warm_ids == cold_ids, "appended-tail event building must equal a full replay"
    assert warm_ids[: len(half_ids)] == half_ids, (
        "event ids must be prefix-stable across appends"
    )


# ---------------------------------------------------------------------------
# 5. randomized ledger growth: warm chain always equals forced cold
# ---------------------------------------------------------------------------


def test_randomized_growth_chain_matches_forced_recompute(tmp_path):
    rng = random.Random(20261022)
    session_id = "ttft8g-random"

    def append(turn, event_type, status, payload):
        append_conversation_event(tmp_path, session, turn, event_type,
                                  status=status, payload=payload)

    case_configs = [
        {},
        {"replace_large_tool_results_for_compression": True},
        {"micro_compact_old_tool_results": True},
    ]
    call_counter = 0
    turn_index = 0
    for case_index, config in enumerate(case_configs):
        context_assembler._ASSEMBLY_MEMO._entries.clear()
        session = f"{session_id}-case{case_index}"
        for _ in range(4):
            turn_index += 1
            turn = f"turn-{turn_index}"
            append(turn, EVENT_USER_MESSAGE, "recorded",
                   {"content": f"随机请求 {turn_index} " + "x" * rng.randint(1, 40)})
            for _ in range(rng.randint(0, 2)):
                call_counter += 1
                call_id = f"call-{call_counter}"
                append(turn, EVENT_TOOL_CALL_STARTED, "running",
                       {"toolCall": {"id": call_id, "name": rng.choice(["read_file_tool", "grep_tool", "run_cmd_tool"])}})
                append(turn, EVENT_TOOL_RESULT, "completed",
                       {"toolCall": {"id": call_id, "result": "结果 " * rng.randint(1, 60)}})
            if rng.random() < 0.2:
                append(turn, "turn_interrupted", "interrupted", {"reason": "user_cancelled"})
            else:
                append(turn, EVENT_ASSISTANT_MESSAGE, "completed",
                       {"content": f"随机回复 {turn_index}"})
            events = load_conversation_events(tmp_path, session)
            assert events, "random turn must journal at least one event"

            # warm chain over a random growth point, then forced cold compare
            cut = rng.randint(1, max(1, len(events) - 1))
            partial = events[:cut]
            _assemble(session, str(partial[-1].turn_id or ""), partial, **config)
            forced_snap, warm_snap = _cold_and_warm(session, events, **config)
            assert warm_snap == forced_snap, (
                f"incremental chain diverged for config={config} at turn {turn_index}"
            )


# ---------------------------------------------------------------------------
# 6. thread safety: concurrent assemblies of one session stay correct
# ---------------------------------------------------------------------------


def test_concurrent_assemblies_are_consistent(tmp_path):
    session_id = "ttft8g-threads"
    for turn in ("turn-1", "turn-2"):
        append_conversation_event(tmp_path, session_id, turn, EVENT_USER_MESSAGE,
                                  status="recorded", payload={"content": f"请求 {turn}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_CALL_STARTED,
                                  status="running", payload={"toolCall": {"id": f"call-{turn}", "name": "read_file_tool"}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TOOL_RESULT,
                                  status="completed", payload={"toolCall": {"id": f"call-{turn}", "result": "内容" * 30}})
        append_conversation_event(tmp_path, session_id, turn, EVENT_ASSISTANT_MESSAGE,
                                  status="completed", payload={"content": f"回复 {turn}"})
        append_conversation_event(tmp_path, session_id, turn, EVENT_TURN_COMPLETED,
                                  status="completed", payload={})
    events = load_conversation_events(tmp_path, session_id)

    context_assembler._ASSEMBLY_MEMO._entries.clear()
    reference = _snapshot(_assemble(session_id, "turn-2", events))
    results: list = []
    errors: list = []

    def worker():
        try:
            for _ in range(6):
                context_assembler._ASSEMBLY_MEMO._entries.clear()
                assembled = _assemble(session_id, "turn-2", events)
                results.append(_snapshot(assembled))
        except Exception as exc:  # pragma: no cover - surfaced via assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f"concurrent assembly raised: {errors}"
    assert all(snapshot == reference for snapshot in results), (
        "concurrent memo use must not corrupt assembly output"
    )
