# -*- coding: utf-8 -*-
"""Sticky projection-lock regression tests.

DeepSeek-style provider prefix caches match request bytes exactly, so a tool
result that flips between verbatim and projected (placeholder / truncated)
forms across turns invalidates the whole cached prefix. These tests pin the
lock layer in ``core.chat.projection_stickiness``:

- a) consecutive assemblies over a growing ledger replay previously projected
  messages byte-identically, even when the current derivation rules would no
  longer project them (rollback / config flip / tier disabled), while newly
  qualifying entries may still be newly projected (monotone growth);
- b) a restart (fresh ledger load) reproduces the exact same assembled bytes;
- c) legacy ledgers without lock events keep today's first-round behavior;
- the lock events themselves stay out of model replay and preview fast paths.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from core.chat.context_assembler import assemble_conversation_context
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    conversation_model_messages_from_events,
    load_conversation_events,
    load_conversation_preview_slice,
)
from core.chat.microcompact import (
    DEFAULT_KEEP_RECENT_GROUPS,
    DEFAULT_MIN_SAVINGS_TOKENS,
    apply_micro_compact_projection,
)
from core.chat.projection_stickiness import (
    EVENT_TOOL_RESULT_PROJECTION_LOCK,
    LOCK_MODE_MICRO_COMPACT,
    persist_assembly_projection_locks,
    projection_locks_from_ledger_events,
)
from core.chat.tool_result_replacement import TOOL_RESULT_PLACEHOLDER_HEADER


def _big_text(seed: str, *, chars: int = 6_000) -> str:
    unit = f"{seed} line of read-only search output with stable tokens\n"
    repeats = max(1, chars // len(unit))
    return (unit * repeats)[:chars]


def _tool_group(index: int, tool_name: str = "grep_search_tool", *, chars: int = 6_000) -> list[dict]:
    call_id = f"call_{index:02d}"
    return [
        {
            "role": "assistant",
            "content": f"调用 {index}",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": _big_text(f"seed-{index}", chars=chars), "tool_call_id": call_id},
    ]


def _seed_ledger_with_groups(tmp_path, session_id: str, groups: list[list[dict]]) -> None:
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-000",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "开始调查"},
    )
    for index, group in enumerate(groups, start=1):
        _append_group_to_ledger(tmp_path, session_id, f"turn-{index:03d}", group)


def _append_group_to_ledger(tmp_path, session_id: str, turn_id: str, group: list[dict]) -> None:
    call = group[0]["tool_calls"][0]
    call_id = str(call.get("id") or "")
    tool_name = str((call.get("function") or {}).get("name") or call.get("name") or "")
    flat_call = {"id": call_id, "name": tool_name, "arguments": "{}"}
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="started",
        payload={"goal": turn_id},
    )
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": group[0].get("content") or ""},
    )
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": dict(flat_call)},
        tool_call_id=call_id,
    )
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {**flat_call, "result": group[1]["content"]}},
        tool_call_id=call_id,
    )


def _ledger_events_from_messages(tmp_path, session_id: str, messages: list[dict]):
    for index, message in enumerate(messages, start=1):
        turn_id = f"turn-{index:03d}"
        role = str(message.get("role") or "").strip().lower()
        if role == "user":
            append_conversation_event(
                tmp_path,
                session_id,
                turn_id,
                EVENT_USER_MESSAGE,
                status="recorded",
                payload={"content": message.get("content") or ""},
            )
            continue
        if role == "tool":
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            tool_call_id = str(message.get("tool_call_id") or message.get("toolCallId") or "").strip()
            tool_name = str(metadata.get("toolName") or metadata.get("tool_name") or "tool").strip()
            append_conversation_event(
                tmp_path,
                session_id,
                turn_id,
                EVENT_TOOL_RESULT,
                status="done",
                payload={
                    "toolCall": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "result": message.get("content") or "",
                    }
                },
                tool_call_id=tool_call_id,
            )
            continue
        if role == "assistant" and str(message.get("content") or "").strip():
            append_conversation_event(
                tmp_path,
                session_id,
                turn_id,
                EVENT_ASSISTANT_MESSAGE,
                status="completed",
                payload={"content": message.get("content") or ""},
            )
    return load_conversation_events(tmp_path, session_id)


def _tool_messages_by_call_id(messages: list[dict]) -> dict[str, dict]:
    return {
        str(message.get("tool_call_id") or ""): message
        for message in messages
        if message.get("role") == "tool"
    }


def _lock_event_count(events) -> int:
    return sum(1 for event in events if event.event_type == EVENT_TOOL_RESULT_PROJECTION_LOCK)


# ---------------------------------------------------------------------------
# a) Two consecutive rounds over a growing ledger
# ---------------------------------------------------------------------------


def test_micro_compact_locked_forms_survive_rule_flip_and_tier_toggle(tmp_path):
    session_id = f"sticky-micro-{uuid4().hex[:12]}"
    groups = [_tool_group(index) for index in range(1, 8)]
    _seed_ledger_with_groups(tmp_path, session_id, groups)
    events_round1 = load_conversation_events(tmp_path, session_id)

    round1 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r1",
        ledger_events=events_round1,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
        micro_compact_keep_recent_groups=DEFAULT_KEEP_RECENT_GROUPS,
        micro_compact_min_savings_tokens=DEFAULT_MIN_SAVINGS_TOKENS,
    )
    assert round1.micro_compact_state["applied"] is True
    assert round1.micro_compact_state["clearedGroups"] == 2
    round1_tools = _tool_messages_by_call_id(round1.history_messages)
    assert round1_tools["call_01"]["content"].startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    assert round1_tools["call_02"]["content"].startswith(TOOL_RESULT_PLACEHOLDER_HEADER)

    persisted = persist_assembly_projection_locks(
        tmp_path,
        session_id,
        turn_id="turn-r1",
        ledger_events=events_round1,
        micro_compact_state=round1.micro_compact_state,
    )
    assert persisted is not None

    # Round 2: a new group arrived AND the whitelist flipped, so the raw
    # derivation alone would clear nothing this turn.
    groups.append(_tool_group(8))
    _append_group_to_ledger(tmp_path, session_id, "turn-008", groups[-1])
    events_round2 = load_conversation_events(tmp_path, session_id)
    assert _lock_event_count(events_round2) == 1

    round2 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r2",
        ledger_events=events_round2,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
        micro_compact_keep_recent_groups=DEFAULT_KEEP_RECENT_GROUPS,
        micro_compact_min_savings_tokens=DEFAULT_MIN_SAVINGS_TOKENS,
        micro_compact_tool_whitelist=["nonexistent_tool"],
    )
    # The sticky layer restored the locked forms even though the raw rules
    # rolled the whole projection back.
    assert round2.micro_compact_state["stickyRestored"] == 2
    assert round2.micro_compact_state["applied"] is True
    assert round2.history_messages[: len(round1.history_messages)] == round1.history_messages
    round2_tools = _tool_messages_by_call_id(round2.history_messages)
    assert round2_tools["call_01"] == round1_tools["call_01"]
    assert round2_tools["call_02"] == round1_tools["call_02"]
    # Unlocked entries keep following the current rules: the brand-new group
    # stays verbatim under the flipped whitelist.
    assert not round2_tools["call_08"]["content"].startswith(TOOL_RESULT_PLACEHOLDER_HEADER)

    # Tier fully disabled: previously projected entries never regress to
    # verbatim (the lock outlives the feature flag).
    round2_off = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r2-off",
        ledger_events=events_round2,
        recent_message_limit=None,
    )
    assert round2_off.history_messages == round2.history_messages

    # Monotone growth: back on the default whitelist, the raw rules newly
    # qualify group 3 while groups 1-2 keep their locked bytes.
    round3 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r3",
        ledger_events=events_round2,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
        micro_compact_keep_recent_groups=DEFAULT_KEEP_RECENT_GROUPS,
        micro_compact_min_savings_tokens=DEFAULT_MIN_SAVINGS_TOKENS,
    )
    round3_tools = _tool_messages_by_call_id(round3.history_messages)
    assert round3_tools["call_01"] == round1_tools["call_01"]
    assert round3_tools["call_02"] == round1_tools["call_02"]
    assert round3_tools["call_03"]["content"].startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    assert not round3_tools["call_08"]["content"].startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    # Round 3 newly projected group 3 -> its lock persists on the next round.
    persist_assembly_projection_locks(
        tmp_path,
        session_id,
        turn_id="turn-r3",
        ledger_events=events_round2,
        micro_compact_state=round3.micro_compact_state,
    )
    assert _lock_event_count(load_conversation_events(tmp_path, session_id)) == 2


def test_replacement_lock_keeps_placeholder_when_tier_disabled(tmp_path):
    session_id = f"sticky-replace-{uuid4().hex[:12]}"
    large_result = "terminal-line\n" * 700
    messages = [
        {"role": "user", "content": "跑一下测试"},
        {
            "role": "tool",
            "tool_call_id": "call_large",
            "content": large_result,
            "metadata": {"toolName": "cli_tool"},
        },
        {"role": "assistant", "content": "完成"},
    ]
    events = _ledger_events_from_messages(tmp_path, session_id, messages)

    round1 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r1",
        ledger_events=events,
        recent_message_limit=None,
        replace_large_tool_results_for_compression=True,
        tool_result_replacement_char_limit=200,
    )
    round1_tool = _tool_messages_by_call_id(round1.history_messages)["call_large"]
    assert round1_tool["content"].startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    assert round1.tool_result_replacement_state["replacements"]

    persist_assembly_projection_locks(
        tmp_path,
        session_id,
        turn_id="turn-r1",
        ledger_events=events,
        tool_result_replacement_state=round1.tool_result_replacement_state,
    )

    round2 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r2",
        ledger_events=load_conversation_events(tmp_path, session_id),
        recent_message_limit=None,
    )
    round2_tool = _tool_messages_by_call_id(round2.history_messages)["call_large"]
    assert round2_tool == round1_tool
    assert round2.tool_result_replacement_state["stickyRestored"] == 1

    # The ledger itself stays untouched: the original result is still the
    # audit authority and remains recoverable by tool_call_id.
    result_event = next(
        event
        for event in load_conversation_events(tmp_path, session_id)
        if event.event_type == EVENT_TOOL_RESULT
    )
    assert large_result.strip()[:40] in str((result_event.payload.get("toolCall") or {}).get("result") or "")


def test_agent_inbox_trim_lock_replays_with_locked_limit(tmp_path):
    session_id = f"sticky-inbox-{uuid4().hex[:12]}"
    big_tool = ("结构化检索正文\n" * 200)[:2_000]
    long_assistant = "旧长回答\n" + ("详细分析\n" * 400)
    messages = [
        {"role": "user", "content": "旧资料搜索任务"},
        {
            "role": "tool",
            "tool_call_id": "call_fetch",
            "content": big_tool,
            "metadata": {"toolName": "web_fetch_tool"},
        },
        {"role": "assistant", "content": long_assistant},
    ]
    events = _ledger_events_from_messages(tmp_path, session_id, messages)

    round1 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r1",
        ledger_events=events,
        recent_message_limit=None,
        history_seed_profile="agent_inbox",
        tool_result_replacement_char_limit=450,
    )
    round1_tool = _tool_messages_by_call_id(round1.history_messages)["call_fetch"]
    assert "原始字符数" in round1_tool["content"]
    assert len(round1_tool["content"]) < len(big_tool)
    round1_assistant = next(
        message
        for message in round1.history_messages
        if message.get("role") == "assistant" and "旧长回答" in str(message.get("content") or "")
    )
    assert "历史 assistant 回复已压缩" in round1_assistant["content"]
    assert round1.history_seed_compaction_state["projectionEntries"]

    persist_assembly_projection_locks(
        tmp_path,
        session_id,
        turn_id="turn-r1",
        ledger_events=events,
        history_seed_compaction_state=round1.history_seed_compaction_state,
    )

    # Round 2 raises the tool trim limit (config/constant drift): without the
    # lock the trim bytes would change; the lock replays round 1's form.
    round2 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r2",
        ledger_events=load_conversation_events(tmp_path, session_id),
        recent_message_limit=None,
        history_seed_profile="agent_inbox",
        tool_result_replacement_char_limit=900,
    )
    assert round2.history_messages == round1.history_messages


# ---------------------------------------------------------------------------
# b) Restart stability
# ---------------------------------------------------------------------------


def test_locks_survive_restart_and_persist_dedupes(tmp_path):
    session_id = f"sticky-restart-{uuid4().hex[:12]}"
    groups = [_tool_group(index) for index in range(1, 8)]
    _seed_ledger_with_groups(tmp_path, session_id, groups)
    events_round1 = load_conversation_events(tmp_path, session_id)

    round1 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r1",
        ledger_events=events_round1,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
    )
    persist_assembly_projection_locks(
        tmp_path,
        session_id,
        turn_id="turn-r1",
        ledger_events=events_round1,
        micro_compact_state=round1.micro_compact_state,
    )

    # "Restart": a fresh process only ever sees the on-disk ledger. The lock
    # index rebuilds from the persisted events and the assembled bytes match
    # the pre-restart projection exactly.
    reloaded_events = load_conversation_events(tmp_path, session_id)
    locks = projection_locks_from_ledger_events(reloaded_events)
    assert locks.has_mode(LOCK_MODE_MICRO_COMPACT)
    after_restart = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r2",
        ledger_events=reloaded_events,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
    )
    assert after_restart.history_messages == round1.history_messages

    # Re-running persistence for the same forms must not append duplicates.
    persist_assembly_projection_locks(
        tmp_path,
        session_id,
        turn_id="turn-r2",
        ledger_events=reloaded_events,
        micro_compact_state=after_restart.micro_compact_state,
    )
    assert _lock_event_count(load_conversation_events(tmp_path, session_id)) == 1


# ---------------------------------------------------------------------------
# c) Legacy sessions without lock records keep today's first-round behavior
# ---------------------------------------------------------------------------


def test_legacy_ledger_first_round_matches_raw_rules(tmp_path):
    session_id = f"sticky-legacy-{uuid4().hex[:12]}"
    groups = [_tool_group(index) for index in range(1, 8)]
    _seed_ledger_with_groups(tmp_path, session_id, groups)
    events = load_conversation_events(tmp_path, session_id)
    assert _lock_event_count(events) == 0

    baseline = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-baseline",
        ledger_events=events,
        recent_message_limit=None,
    )
    assembled = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r1",
        ledger_events=events,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
        micro_compact_keep_recent_groups=DEFAULT_KEEP_RECENT_GROUPS,
        micro_compact_min_savings_tokens=DEFAULT_MIN_SAVINGS_TOKENS,
    )
    # Identical to the pre-lock behavior: the raw projection applied to the
    # same history, no sticky restores, no lock events written implicitly.
    expected_messages, expected_state = apply_micro_compact_projection(
        baseline.history_messages,
        session_id=session_id,
        keep_recent_groups=DEFAULT_KEEP_RECENT_GROUPS,
        min_savings_tokens=DEFAULT_MIN_SAVINGS_TOKENS,
    )
    assert assembled.history_messages == expected_messages
    assert assembled.micro_compact_state["applied"] == expected_state["applied"]
    assert assembled.micro_compact_state["clearedGroups"] == expected_state["clearedGroups"]
    assert "stickyRestored" not in assembled.micro_compact_state
    assert _lock_event_count(load_conversation_events(tmp_path, session_id)) == 0


# ---------------------------------------------------------------------------
# Lock events stay invisible to model replay and preview fast paths
# ---------------------------------------------------------------------------


def test_lock_events_are_never_model_visible_or_preview_breaking(tmp_path):
    session_id = f"sticky-invisible-{uuid4().hex[:12]}"
    groups = [_tool_group(index) for index in range(1, 8)]
    _seed_ledger_with_groups(tmp_path, session_id, groups)
    events_before = load_conversation_events(tmp_path, session_id)
    replay_before = conversation_model_messages_from_events(events_before)

    round1 = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r1",
        ledger_events=events_before,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
    )
    persist_assembly_projection_locks(
        tmp_path,
        session_id,
        turn_id="turn-r1",
        ledger_events=events_before,
        micro_compact_state=round1.micro_compact_state,
    )

    events_after = load_conversation_events(tmp_path, session_id)
    assert _lock_event_count(events_after) == 1
    lock_event = next(event for event in events_after if event.event_type == EVENT_TOOL_RESULT_PROJECTION_LOCK)
    assert lock_event.visible_in_model is False
    assert conversation_model_messages_from_events(events_after) == replay_before
    preview = load_conversation_preview_slice(tmp_path, session_id, event_limit=16)
    assert preview.safe is True


# ---------------------------------------------------------------------------
# Production write path: session_service wrapper persists after assembly
# ---------------------------------------------------------------------------


def test_session_service_wrapper_persists_locks_end_to_end(tmp_path, monkeypatch):
    session_service = pytest.importorskip("core.web.services.session_service")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_id = f"sticky-wrapper-{uuid4().hex[:12]}"
    groups = [_tool_group(index) for index in range(1, 8)]
    _seed_ledger_with_groups(tmp_path, session_id, groups)
    events = load_conversation_events(tmp_path, session_id)

    round1 = session_service.assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r1",
        ledger_events=events,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
    )
    assert round1.micro_compact_state["applied"] is True
    after = load_conversation_events(tmp_path, session_id)
    assert _lock_event_count(after) == 1

    # Second turn through the wrapper: no duplicate lock batch, and the
    # assembled history is byte-identical to turn 1.
    round2 = session_service.assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-r2",
        ledger_events=after,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
    )
    assert round2.history_messages == round1.history_messages
    assert _lock_event_count(load_conversation_events(tmp_path, session_id)) == 1
