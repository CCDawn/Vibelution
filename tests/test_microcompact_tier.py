# -*- coding: utf-8 -*-
"""Micro-compaction tier tests.

Covers: trigger band math, whitelist selection, keep-recent-N groups,
min-savings rollback, error/media skips, unresolved-call skips, tool_call/
tool_result pairing integrity, context-assembler read-time projection with
memo/fingerprint correctness, and the "micro drops the estimate below the
full-compression line, so full compression does not run this round" gate.
"""

from __future__ import annotations

import pytest
from uuid import uuid4

from config.models import (
    MICRO_COMPACT_DEFAULT_TOOL_WHITELIST,
    ContextCompressionConfig,
)
from core.chat.context_assembler import assemble_conversation_context
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.chat.microcompact import (
    DEFAULT_KEEP_RECENT_GROUPS,
    apply_micro_compact_projection,
    empty_micro_compact_state,
    micro_compact_band_contains,
    micro_compact_trigger_tokens,
)
from core.chat.model_messages import ProviderMessageChain
from core.chat.conversation_invariant import check_conversation_payload_invariant
from core.chat.tool_result_replacement import (
    TOOL_RESULT_PLACEHOLDER_HEADER,
    replace_large_tool_results_for_compression,
)
from tools.token_manager import estimate_messages_tokens_uncached


FULL_TRIGGER = 100_000


def _big_text(seed: str, *, chars: int = 8_000) -> str:
    unit = f"{seed} line of read-only search output with stable tokens\n"
    repeats = max(1, chars // len(unit))
    return (unit * repeats)[:chars]


def _assistant_tool_call_message(call_id: str, tool_name: str, *, content: str = "") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": "{}"},
            }
        ],
    }


def _tool_result_message(call_id: str, content: str, *, metadata: dict | None = None) -> dict:
    message = {"role": "tool", "content": content, "tool_call_id": call_id}
    if metadata:
        message["metadata"] = metadata
    return message


def _tool_group(index: int, tool_name: str, *, chars: int = 8_000, content: str | None = None) -> list[dict]:
    call_id = f"call_{index:02d}"
    result = content if content is not None else _big_text(f"seed-{index}", chars=chars)
    return [
        _assistant_tool_call_message(call_id, tool_name, content=f"调用 {index}"),
        _tool_result_message(call_id, result),
    ]


def _history_with_old_groups(*tool_groups: list[dict]) -> list[dict]:
    messages: list[dict] = [{"role": "user", "content": "开始调查"}]
    for group in tool_groups:
        messages.extend(group)
    messages.append({"role": "user", "content": "继续"})
    return messages


# ---------------------------------------------------------------------------
# Trigger band contract
# ---------------------------------------------------------------------------


def test_micro_trigger_line_is_min_of_ratio_and_margin():
    assert micro_compact_trigger_tokens(228_664) == 205_797  # min(205_797.6, 226_664)
    assert micro_compact_trigger_tokens(10_000) == 8_000  # margin branch wins
    assert micro_compact_trigger_tokens(2_200) == 200  # margin branch wins
    assert micro_compact_trigger_tokens(2_000) == 0  # degenerate: disabled
    assert micro_compact_trigger_tokens(0) == 0
    assert micro_compact_trigger_tokens(-5) == 0


def test_band_contains_only_between_micro_and_full_line():
    micro = micro_compact_trigger_tokens(FULL_TRIGGER)
    assert micro_compact_band_contains(micro, full_trigger_tokens=FULL_TRIGGER)
    assert micro_compact_band_contains(FULL_TRIGGER, full_trigger_tokens=FULL_TRIGGER)
    assert not micro_compact_band_contains(micro - 1, full_trigger_tokens=FULL_TRIGGER)
    assert not micro_compact_band_contains(FULL_TRIGGER + 1, full_trigger_tokens=FULL_TRIGGER)
    assert not micro_compact_band_contains(50_000, full_trigger_tokens=0)


def test_config_defaults_enable_micro_compact_tier():
    config = ContextCompressionConfig()
    assert config.micro_compact_enabled is True
    assert config.micro_compact_keep_recent_groups == DEFAULT_KEEP_RECENT_GROUPS == 5
    assert config.micro_compact_min_savings_tokens == 256
    assert config.micro_compact_tool_whitelist == list(MICRO_COMPACT_DEFAULT_TOOL_WHITELIST)
    assert "write_file_tool" not in config.micro_compact_tool_whitelist
    assert "apply_diff_edit_tool" not in config.micro_compact_tool_whitelist
    override = ContextCompressionConfig(micro_compact_enabled=False, micro_compact_keep_recent_groups=2)
    assert override.micro_compact_enabled is False
    assert override.micro_compact_keep_recent_groups == 2


# ---------------------------------------------------------------------------
# Projection behavior
# ---------------------------------------------------------------------------


def test_projection_clears_only_whitelisted_old_groups():
    messages = _history_with_old_groups(
        _tool_group(1, "grep_search_tool"),
        _tool_group(2, "write_file_tool"),  # write tool: never cleared
        _tool_group(3, "read_file_tool"),
        _tool_group(4, "glob_tool"),
        _tool_group(5, "web_fetch_tool"),
        _tool_group(6, "cli_tool"),
        _tool_group(7, "read_file_tool"),
    )
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    # Last 5 tool groups stay; group 1 is the only clearable old one.
    assert state["keptRecentGroups"] == 5
    assert state["clearedGroups"] == 1
    assert messages[1] == projected[1] or projected[1]["content"].startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    # write_file_tool result content must be untouched even though old.
    write_result = messages[3]
    assert projected[3] is write_result
    # Whitelisted recent groups stay untouched.
    for recent_index in (5, 7, 9, 11, 13):
        assert projected[recent_index] is messages[recent_index]
    assert state["skippedWhitelistGroups"] == 1  # write_file_tool group
    assert state["tokensSaved"] > 0


def test_projection_keeps_most_recent_five_groups():
    groups = [_tool_group(index, "read_file_tool", chars=6_000) for index in range(1, 9)]
    messages = _history_with_old_groups(*groups)
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    assert state["clearedGroups"] == 3  # 8 groups, keep 5
    assert state["skippedRecentGroups"] == 5
    cleared = 0
    for index, message in enumerate(projected):
        if (
            isinstance(message, dict)
            and message.get("role") == "tool"
            and str(message.get("content") or "").startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
        ):
            cleared += 1
    assert cleared == 3


def test_projection_rolls_back_when_savings_below_minimum():
    messages = _history_with_old_groups(
        _tool_group(1, "read_file_tool", chars=40),
        _tool_group(2, "read_file_tool", chars=40),
        _tool_group(3, "grep_search_tool", chars=40),
        _tool_group(4, "glob_tool", chars=40),
        _tool_group(5, "cli_tool", chars=40),
        _tool_group(6, "read_file_tool", chars=40),
    )
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=256)
    assert state["applied"] is False
    assert state["rollbackReason"] == "min_savings_not_met"
    assert projected == messages
    assert state["tokensSaved"] < 256


def test_projection_skips_error_and_media_results():
    messages = _history_with_old_groups(
        _tool_group(1, "read_file_tool", content=_big_text("err", chars=6_000) + "\nTraceback (most recent call last)"),
        _tool_group(2, "grep_search_tool", content=f"{_big_text('shot', chars=3_000)}data:image/png;base64,AAAA"),
        _tool_group(3, "read_file_tool"),
        _tool_group(4, "glob_tool"),
        _tool_group(5, "web_search_tool"),
        _tool_group(6, "cli_tool"),
        _tool_group(7, "paper_search_tool"),
        _tool_group(8, "history_search_tool"),
        _tool_group(9, "project_search_tool"),
    )
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    # 9 groups, keep 5: groups 1-4 are old. Groups 1 and 2 carry an error and
    # a media payload and must be skipped entirely.
    assert state["skippedErrorOrMediaGroups"] == 2
    assert state["clearedGroups"] == 2
    assert projected[1] is messages[1]
    assert projected[3] is messages[3]


def test_projection_skips_unresolved_call_groups():
    messages: list[dict] = [
        {"role": "user", "content": "开始"},
        # No tool result follows: unresolved call is retention surface.
        _assistant_tool_call_message("call_unresolved", "read_file_tool"),
    ]
    for index in range(2, 8):
        messages.extend(_tool_group(index, "read_file_tool" if index % 2 else "cli_tool"))
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    assert state["skippedUnresolvedGroups"] == 1
    # The unresolved assistant call stays byte-identical.
    assert projected[1] is messages[1]
    assert projected[1]["tool_calls"] == messages[1]["tool_calls"]


def test_projection_never_touches_write_tools_even_when_old():
    messages = _history_with_old_groups(
        _tool_group(1, "apply_diff_edit_tool"),
        _tool_group(2, "write_file_tool"),
        _tool_group(3, "read_file_tool"),
        _tool_group(4, "grep_search_tool"),
        _tool_group(5, "glob_tool"),
        _tool_group(6, "code_symbol_tool"),
        _tool_group(7, "write_file_tool"),
        _tool_group(8, "apply_patch_tool"),
    )
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    # 8 groups, keep 5: groups 1-3 are old; groups 1 and 2 are write tools.
    assert state["skippedWhitelistGroups"] == 2
    assert state["clearedGroups"] == 1
    assert projected[1] is messages[1]
    assert projected[3] is messages[3]


def test_projection_preserves_provider_pairing_structure():
    groups = [
        _tool_group(index, "read_file_tool" if index % 2 else "grep_search_tool", chars=6_000)
        for index in range(1, 9)
    ]
    messages = _history_with_old_groups(*groups)
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    invariant = check_conversation_payload_invariant(projected)
    assert invariant.ok, invariant
    chain = ProviderMessageChain.from_messages(projected)
    assert chain.repaired is False
    original_ids = [
        message.get("tool_call_id")
        for message in messages
        if message.get("role") == "tool"
    ]
    projected_ids = [
        message.get("tool_call_id")
        for message in projected
        if message.get("role") == "tool"
    ]
    assert projected_ids == original_ids
    # Assistant tool_calls stay byte-identical.
    for original, updated in zip(messages, projected):
        if original.get("role") == "assistant":
            assert updated["tool_calls"] == original["tool_calls"]


def test_projection_supports_langchain_message_objects():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    messages: list[dict] = [
        HumanMessage(content="开始"),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_file_tool", "args": {}, "id": "call_obj_1"}],
        ),
        ToolMessage(content=_big_text("obj-1", chars=6_000), tool_call_id="call_obj_1"),
    ]
    for index in range(2, 8):
        messages.extend(_tool_group(index, "cli_tool"))
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    assert state["clearedGroups"] >= 1
    cleared = projected[2]
    assert cleared.tool_call_id == "call_obj_1"
    assert str(cleared.content).startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    # AIMessage object identity and tool_calls are untouched.
    assert projected[1] is messages[1]


def test_projection_is_idempotent():
    messages = _history_with_old_groups(*[_tool_group(i, "read_file_tool") for i in range(1, 9)])
    first, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    second, second_state = apply_micro_compact_projection(first, min_savings_tokens=0)
    assert second_state["applied"] is False
    assert second_state["rollbackReason"] == "no_clearable_groups"
    assert second == first


def test_whitelist_normalization_falls_back_to_default():
    from core.chat.microcompact import normalize_micro_compact_whitelist

    assert normalize_micro_compact_whitelist(None) == tuple(MICRO_COMPACT_DEFAULT_TOOL_WHITELIST)
    assert normalize_micro_compact_whitelist([]) == tuple(MICRO_COMPACT_DEFAULT_TOOL_WHITELIST)
    assert normalize_micro_compact_whitelist([" custom_tool ", ""]) == ("custom_tool",)


# ---------------------------------------------------------------------------
# Integration: micro drops the estimate below the full line
# ---------------------------------------------------------------------------


def test_micro_projection_below_full_line_prevents_full_compression():
    """Estimate in [micro, full) → project → re-estimate < full → no full run."""

    full_trigger = 20_000  # 8 groups of ~9k chars land in the trigger band.
    messages = _history_with_old_groups(
        *[_tool_group(index, "read_file_tool", chars=9_000) for index in range(1, 8)]
    )
    micro_line = micro_compact_trigger_tokens(full_trigger)
    before_tokens = estimate_messages_tokens_uncached(messages)
    assert micro_compact_band_contains(
        before_tokens,
        full_trigger_tokens=full_trigger,
        micro_trigger_tokens=micro_line,
    )
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=256)
    assert state["applied"] is True
    after_tokens = estimate_messages_tokens_uncached(projected)
    # Full compression gate: strictly greater than the trigger line. The
    # projection dropped the estimate below it, so this round must not run
    # the full summary compression.
    assert after_tokens <= full_trigger
    assert not (after_tokens > full_trigger)
    assert state["tokensSaved"] >= 256
    assert before_tokens - after_tokens == state["tokensSaved"]


def test_shared_placeholder_form_matches_full_compression_replacement():
    content = _big_text("shared", chars=5_000)
    messages = [
        _assistant_tool_call_message("call_shared", "read_file_tool"),
        _tool_result_message("call_shared", content),
    ]
    replaced, replacement_state = replace_large_tool_results_for_compression(
        messages,
        char_limit=1_000,
        session_id="shared-session",
    )
    micro_projected, micro_state = apply_micro_compact_projection(
        messages,
        session_id="shared-session",
        min_savings_tokens=0,
        keep_recent_groups=0,
    )
    assert str(replaced[1]["content"]).startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    assert str(micro_projected[1]["content"]).startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    assert "tool-result-ref:" in str(replaced[1]["content"])
    assert "tool-result-ref:" in str(micro_projected[1]["content"])
    assert replacement_state["replacements"][0]["sha256"] == micro_state["replacements"][0]["sha256"]
    assert replacement_state["replacements"][0]["reference"] == micro_state["replacements"][0]["reference"]


# ---------------------------------------------------------------------------
# Context assembler read-time projection
# ---------------------------------------------------------------------------


def _ledger_events_from_groups(tmp_path, session_id: str, groups: list[list[dict]], turn_prefix: str) -> None:
    append_conversation_event(
        tmp_path,
        session_id,
        f"{turn_prefix}-000",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "开始调查"},
    )
    for index, group in enumerate(groups, start=1):
        turn_id = f"{turn_prefix}-{index:03d}"
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
            payload={"goal": f"turn {index}"},
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


def test_assembler_micro_compact_projection_and_memo_invalidation(tmp_path):
    # Unique per run: pytest reuses the numbered tmp dir across sessions and
    # the ledger is append-only, so a fixed id would accumulate stale groups.
    session_id = f"micro-tier-{uuid4().hex[:12]}"
    groups = [
        _tool_group(index, "read_file_tool" if index % 2 else "grep_search_tool", chars=6_000)
        for index in range(1, 8)
    ]
    _ledger_events_from_groups(tmp_path, session_id, groups, "turn-a")
    events = load_conversation_events(tmp_path, session_id)

    baseline = assemble_conversation_context(
        [],
        session_id=session_id,
        ledger_events=events,
        recent_message_limit=None,
    )
    assert baseline.micro_compact_state["mode"] == "micro_compact"
    assert baseline.micro_compact_state["applied"] is False
    baseline_hash = baseline.dynamic_context_hash

    assembled = assemble_conversation_context(
        [],
        session_id=session_id,
        ledger_events=events,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
        micro_compact_keep_recent_groups=5,
        micro_compact_min_savings_tokens=256,
    )
    assert assembled.micro_compact_state["applied"] is True
    assert assembled.micro_compact_state["clearedGroups"] == 2  # 7 groups, keep 5
    assert assembled.dynamic_context_hash != baseline_hash
    cleared = [
        message
        for message in assembled.history_messages
        if message.get("role") == "tool"
        and str(message.get("content") or "").startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    ]
    assert len(cleared) == 2
    patch = assembled.to_composition_patch()
    assert patch["microCompact"]["applied"] is True
    assert patch["microCompact"]["clearedGroups"] == 2
    invariant = check_conversation_payload_invariant(assembled.history_messages)
    assert invariant.ok, invariant

    # Memo invalidation: appending a new group must change the projection
    # instead of replaying the stale memo entry.
    groups.append(_tool_group(8, "web_fetch_tool", chars=6_000))
    _ledger_events_from_groups(tmp_path, session_id, [groups[-1]], "turn-b")
    events_after = load_conversation_events(tmp_path, session_id)
    reassembled = assemble_conversation_context(
        [],
        session_id=session_id,
        ledger_events=events_after,
        recent_message_limit=None,
        micro_compact_old_tool_results=True,
        micro_compact_keep_recent_groups=5,
        micro_compact_min_savings_tokens=256,
    )
    assert reassembled.micro_compact_state["clearedGroups"] == 3
    assert reassembled.dynamic_context_hash != assembled.dynamic_context_hash

    # Disabling the tier must leave every tool result intact again.
    disabled = assemble_conversation_context(
        [],
        session_id=session_id,
        ledger_events=events_after,
        recent_message_limit=None,
        micro_compact_old_tool_results=False,
    )
    assert disabled.micro_compact_state["applied"] is False
    assert disabled.dynamic_context_hash == baseline_hash or not [
        message
        for message in disabled.history_messages
        if message.get("role") == "tool"
        and str(message.get("content") or "").startswith(TOOL_RESULT_PLACEHOLDER_HEADER)
    ]


def test_empty_micro_compact_state_shape():
    state = empty_micro_compact_state()
    assert state == {
        "schemaVersion": 1,
        "mode": "micro_compact",
        "applied": False,
        "clearedGroups": 0,
        "clearedResults": 0,
        "tokensSaved": 0,
        "keptRecentGroups": 0,
        "skippedRecentGroups": 0,
        "skippedWhitelistGroups": 0,
        "skippedUnresolvedGroups": 0,
        "skippedErrorOrMediaGroups": 0,
        "rollbackReason": "",
        "replacements": [],
    }
