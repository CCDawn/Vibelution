# -*- coding: utf-8 -*-
"""Micro-compaction hybrid metering anchor + working-set re-injection tests.

Anchor: provider-usage base (usage ledger, read-only) + local estimate of the
increment after the last committed assistant, with ``tokenSource`` audit and
pure-estimate fallback. Re-injection: cleared ``read_file_tool`` groups
rebuilt as synthetic system-role Read reminders with dedupe / .git exclusion /
file-count and token limits / pointer downgrade / determinism / idempotency.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from core.infrastructure import developer_sandbox
from core.chat.microcompact import (
    DEFAULT_REINJECTION_MAX_FILES,
    WORKING_SET_REINJECTION_HEADER,
    WORKING_SET_REINJECTION_TOOL,
    apply_micro_compact_projection,
    empty_micro_compact_state,
)
from core.chat.microcompact_anchor import (
    empty_anchor_audit,
    estimate_tokens_with_anchor,
    load_provider_usage_anchor,
)
from core.llm.usage_ledger import (
    UsageLedgerEvent,
    record_usage_event,
)
from tools.token_manager import estimate_messages_tokens_uncached


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------


def _big_text(seed: str, *, chars: int = 6_000) -> str:
    unit = f"{seed} stable line of file content for projection\n"
    repeats = max(1, chars // len(unit))
    return (unit * repeats)[:chars]


def _read_group(
    index: int,
    path: str | None,
    *,
    tool: str = WORKING_SET_REINJECTION_TOOL,
    chars: int = 6_000,
    content: str | None = None,
) -> list[dict]:
    call_id = f"call_{index:02d}"
    args = json.dumps({"file_path": path} if path else {})
    result = content if content is not None else _big_text(f"seed-{index}", chars=chars)
    return [
        {
            "role": "assistant",
            "content": f"call {index}",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool, "arguments": args},
                }
            ],
        },
        {"role": "tool", "content": result, "tool_call_id": call_id},
    ]


def _history(*tool_groups: list[dict]) -> list[dict]:
    messages: list[dict] = [{"role": "user", "content": "开始调查"}]
    for group in tool_groups:
        messages.extend(group)
    messages.append({"role": "user", "content": "继续"})
    return messages


def _reinforcement_entries(state: dict) -> list[dict]:
    return (state.get("reinjection") or {}).get("entries") or []


# ---------------------------------------------------------------------------
# Anchor: pure hybrid estimate
# ---------------------------------------------------------------------------


def test_anchor_hit_uses_total_tokens_base_and_estimates_only_increment():
    assistant_reply = "回答 " * 200
    tool_result = "x" * 4_000
    messages = [
        {"role": "user", "content": "问题一"},
        {"role": "assistant", "content": assistant_reply},
        {"role": "tool", "content": tool_result, "tool_call_id": "t1"},
    ]
    tokens, audit = estimate_tokens_with_anchor(
        messages,
        anchor={
            "totalTokens": 90_000,
            "inputTokens": 88_000,
            "eventId": "evt-1",
            "recordedAt": "2026-01-01T00:00:00Z",
        },
    )
    # Base covers everything through the assistant output; only the tool
    # result after the assistant is estimated locally.
    assert audit["tokenSource"] == "anchor+estimate"
    assert audit["anchorTokens"] == 90_000
    assert audit["incrementalStartIndex"] == 2
    expected_increment = estimate_messages_tokens_uncached([messages[2]])
    assert audit["incrementalTokens"] == expected_increment
    assert tokens == 90_000 + expected_increment
    assert audit["anchorEventId"] == "evt-1"
    assert audit["anchorRecordedAt"] == "2026-01-01T00:00:00Z"


def test_anchor_input_only_base_counts_assistant_message_as_increment():
    messages = [
        {"role": "user", "content": "问题一"},
        {"role": "assistant", "content": "回答内容 " * 100},
        {"role": "tool", "content": "y" * 2_000, "tool_call_id": "t1"},
    ]
    tokens, audit = estimate_tokens_with_anchor(
        messages,
        anchor={"inputTokens": 88_000},
    )
    # Provider input only covers the request before the assistant, so the
    # assistant message itself stays in the local increment (index 1).
    assert audit["tokenSource"] == "anchor+estimate"
    assert audit["anchorTokens"] == 88_000
    assert audit["incrementalStartIndex"] == 1
    expected_increment = estimate_messages_tokens_uncached(messages[1:])
    assert tokens == 88_000 + expected_increment


def test_anchor_with_empty_increment_reports_provider_usage_source():
    messages = [
        {"role": "user", "content": "问题一"},
        {"role": "assistant", "content": "回答"},
    ]
    tokens, audit = estimate_tokens_with_anchor(
        messages,
        anchor={"totalTokens": 90_000},
    )
    assert tokens == 90_000
    assert audit["tokenSource"] == "provider_usage"
    assert audit["incrementalTokens"] == 0


def test_anchor_missing_falls_back_to_pure_estimate():
    messages = [
        {"role": "user", "content": "问题一"},
        {"role": "assistant", "content": "回答内容"},
        {"role": "tool", "content": "z" * 1_000, "tool_call_id": "t1"},
    ]
    pure = estimate_messages_tokens_uncached(messages)
    tokens, audit = estimate_tokens_with_anchor(messages, anchor=None)
    assert tokens == pure
    assert audit["tokenSource"] == "estimate"
    assert audit["anchorTokens"] == 0

    # Caller-computed fallback wins over recomputation (behavior identical to
    # the pre-anchor gate, which already had the pure number).
    tokens_fallback, audit_fallback = estimate_tokens_with_anchor(
        messages, anchor=None, fallback_tokens=12_345
    )
    assert tokens_fallback == 12_345
    assert audit_fallback["tokenSource"] == "estimate"


def test_anchor_with_zero_tokens_or_missing_assistant_falls_back():
    messages = [
        {"role": "user", "content": "问题一"},
        {"role": "assistant", "content": "回答"},
    ]
    # Anchor without any usable token counts.
    tokens, audit = estimate_tokens_with_anchor(
        messages, anchor={"totalTokens": 0, "inputTokens": 0}, fallback_tokens=999
    )
    assert tokens == 999
    assert audit["tokenSource"] == "estimate"
    # Anchor exists but the last committed assistant is not in this view
    # (windowed seed / replayed suffix): hybrid would double-count, so fall back.
    tokens_no_assistant, audit_no_assistant = estimate_tokens_with_anchor(
        [{"role": "user", "content": "只有用户消息"}],
        anchor={"totalTokens": 90_000},
        fallback_tokens=777,
    )
    assert tokens_no_assistant == 777
    assert audit_no_assistant["tokenSource"] == "estimate"


def test_empty_anchor_audit_shape():
    assert empty_anchor_audit() == {
        "tokenSource": "estimate",
        "anchorTokens": 0,
        "incrementalTokens": 0,
        "incrementalStartIndex": -1,
        "anchorEventId": "",
        "anchorRecordedAt": "",
    }


# ---------------------------------------------------------------------------
# Anchor: ledger lookup (read-only)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_usage_ledger_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        developer_sandbox,
        "resolve_workspace_home",
        lambda *args, **kwargs: tmp_path / "workspace",
    )


def _iso_at(minutes_ago: int) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_load_provider_usage_anchor_reads_latest_conversation_row(tmp_path):
    root = tmp_path / "project"
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=_iso_at(30),
            source="provider_usage",
            scope_kind="chat_session",
            session_id="conv-1",
            conversation_id="conv-1",
            input_tokens=10_000,
            output_tokens=500,
            total_tokens=10_500,
        ),
        project_root=root,
    )
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=_iso_at(5),
            source="provider_usage",
            scope_kind="chat_session",
            session_id="conv-1",
            conversation_id="conv-1",
            input_tokens=20_000,
            output_tokens=800,
            total_tokens=20_800,
        ),
        project_root=root,
    )
    anchor = load_provider_usage_anchor(conversation_id="conv-1", project_root=root)
    assert anchor is not None
    assert anchor["inputTokens"] == 20_000
    assert anchor["totalTokens"] == 20_800
    assert anchor["eventId"].startswith("usage-")


def test_load_provider_usage_anchor_ignores_estimated_and_other_conversations(tmp_path):
    root = tmp_path / "project"
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=_iso_at(2),
            source="estimated",
            scope_kind="chat_session",
            session_id="conv-2",
            conversation_id="conv-2",
            input_tokens=99_999,
            output_tokens=1,
            total_tokens=100_000,
        ),
        project_root=root,
    )
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=_iso_at(40),
            source="provider_usage",
            scope_kind="chat_session",
            session_id="other-conv",
            conversation_id="other-conv",
            input_tokens=1_000,
            output_tokens=10,
            total_tokens=1_010,
        ),
        project_root=root,
    )
    assert (
        load_provider_usage_anchor(conversation_id="conv-2", project_root=root) is None
    )
    other = load_provider_usage_anchor(conversation_id="other-conv", project_root=root)
    assert other is not None and other["inputTokens"] == 1_000


def test_load_provider_usage_anchor_falls_back_to_session_column(tmp_path):
    root = tmp_path / "project"
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=_iso_at(1),
            source="provider_usage",
            scope_kind="chat_session",
            session_id="sess-only",
            conversation_id="",
            input_tokens=4_321,
            output_tokens=11,
            total_tokens=4_332,
        ),
        project_root=root,
    )
    anchor = load_provider_usage_anchor(
        conversation_id="sess-only", session_id="sess-only", project_root=root
    )
    assert anchor is not None and anchor["totalTokens"] == 4_332


def test_load_provider_usage_anchor_missing_ledger_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.chat.microcompact_anchor.usage_ledger_path",
        lambda project_root=None: tmp_path / "nowhere" / "usage_ledger.sqlite3",
    )
    assert load_provider_usage_anchor(conversation_id="conv-x") is None
    assert load_provider_usage_anchor(conversation_id="", session_id="") is None


# ---------------------------------------------------------------------------
# Working-set re-injection
# ---------------------------------------------------------------------------


def test_reinjection_restores_cleared_file_reads_most_recent_first():
    messages = _history(
        _read_group(1, "src/one.py"),
        _read_group(2, "src/two.py"),
        _read_group(3, "src/three.py"),
        _read_group(4, "docs/four.md"),
        _read_group(5, "cli-out", tool="cli_tool"),
        _read_group(6, "src/five.py"),
        _read_group(7, "src/six.py"),
        _read_group(8, "src/seven.py"),
    )
    projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    reinjection = state["reinjection"]
    # Groups 1-3 are cleared; 6-8 have no file_path and cli_tool/glob-style
    # groups carry no file content. Most recent cleared read first.
    assert reinjection["injectedFiles"] == ["src/three.py", "src/two.py", "src/one.py"]
    assert reinjection["downgradedFiles"] == []
    entries = _reinforcement_entries(state)
    assert [entry["role"] for entry in entries] == ["system", "system", "system"]
    first_body = entries[0]["content"]
    assert first_body.startswith(WORKING_SET_REINJECTION_HEADER)
    assert "文件: src/three.py" in first_body
    assert "引用: tool-result-ref:" in first_body
    assert "工具调用ID: call_03" in first_body
    assert "原始SHA256: " in first_body
    assert "read_file_tool" in first_body
    # The restored content is the original read result.
    assert _big_text("seed-3")[:40] in first_body
    # Reminders ride at the tail of the projection.
    assert projected[-3:] == entries
    # The reference matches the cleared placeholder's reference for the same
    # call (shared recoverability contract).
    metadata = entries[0]["metadata"]["workingSetReinjection"]
    assert metadata["mode"] == "full"
    assert metadata["toolCallId"] == "call_03"


def test_reinjection_dedupes_paths_keeping_latest_content():
    latest_content = _big_text("latest", chars=5_000)
    old_content = _big_text("old", chars=6_000)
    messages = _history(
        _read_group(1, "src/same.py", content=old_content),
        _read_group(2, "src/fillera.py"),
        _read_group(3, "src/same.py", content=latest_content),
        _read_group(4, "src/fillerb.py"),
        _read_group(5, "src/fillerc.py"),
        _read_group(6, "src/fillerd.py"),
        _read_group(7, "src/keep7.py"),
        _read_group(8, "src/keep8.py"),
    )
    _projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    reinjection = state["reinjection"]
    # Groups 1-3 are the cleared window; same.py appears twice there and the
    # most recent read (group 3) wins.
    assert reinjection["injectedFiles"].count("src/same.py") == 1
    entries = _reinforcement_entries(state)
    same_entries = [
        entry
        for entry in entries
        if entry["metadata"]["workingSetReinjection"].get("path") == "src/same.py"
    ]
    assert len(same_entries) == 1
    assert latest_content[:40] in same_entries[0]["content"]
    assert old_content[:40] not in same_entries[0]["content"]


def test_reinjection_excludes_git_paths():
    messages = _history(
        _read_group(
            1,
            "repo/.git/objects/ab/cdef",
            content=_big_text("git", chars=5_000),
        ),
        _read_group(2, "src/normal.py"),
        _read_group(3, "src/fillera.py"),
        _read_group(4, "src/fillerb.py"),
        _read_group(5, "src/fillerc.py"),
        _read_group(6, "src/fillerd.py"),
        _read_group(7, "src/keep7.py"),
        _read_group(8, "src/keep8.py"),
    )
    _projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    reinjection = state["reinjection"]
    assert reinjection["skippedGitPathCount"] == 1
    all_paths = reinjection["injectedFiles"] + reinjection["downgradedFiles"]
    assert all(".git/" not in path for path in all_paths)


def test_reinjection_caps_file_count_at_five():
    groups = [
        _read_group(index, f"src/file_{index}.py", chars=3_000) for index in range(1, 9)
    ]
    messages = _history(*groups)
    _projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    assert state["clearedGroups"] == 3
    reinjection = state["reinjection"]
    assert (
        len(reinjection["injectedFiles"]) + len(reinjection["downgradedFiles"])
        <= DEFAULT_REINJECTION_MAX_FILES
    )
    assert len(_reinforcement_entries(state)) <= DEFAULT_REINJECTION_MAX_FILES


def test_reinjection_downgrades_oversized_file_to_pointer():
    oversized = "大" * 40_000  # way past the 5k-token per-file cap
    messages = _history(
        _read_group(1, "src/huge.py", content=oversized),
        _read_group(2, "src/small.py", chars=2_000),
        _read_group(3, "src/fillera.py", chars=2_000),
        _read_group(4, "src/fillerb.py", chars=2_000),
        _read_group(5, "src/fillerc.py", chars=2_000),
        _read_group(6, "src/fillerd.py", chars=2_000),
        _read_group(7, "src/keep7.py", chars=2_000),
        _read_group(8, "src/keep8.py", chars=2_000),
    )
    _projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    reinjection = state["reinjection"]
    assert "src/huge.py" in reinjection["downgradedFiles"]
    pointer_entries = [
        entry
        for entry in _reinforcement_entries(state)
        if entry["metadata"]["workingSetReinjection"].get("path") == "src/huge.py"
    ]
    assert len(pointer_entries) == 1
    pointer = pointer_entries[0]
    assert pointer["metadata"]["workingSetReinjection"]["mode"] == "pointer"
    assert pointer["content"].startswith(WORKING_SET_REINJECTION_HEADER)
    assert "src/huge.py" in pointer["content"]
    assert "read_file_tool 重读" in pointer["content"]
    assert "大" * 100 not in pointer["content"]


def test_reinjection_enforces_total_token_budget():
    # Each file sits under the per-file cap, but the configured batch budget
    # only fits one: later candidates degrade to pointers.
    messages = _history(
        _read_group(1, "src/bulk_1.py", chars=6_000),
        _read_group(2, "src/bulk_2.py", chars=6_000),
        _read_group(3, "src/bulk_3.py", chars=6_000),
        _read_group(4, "src/keep4.py", chars=2_000),
        _read_group(5, "src/keep5.py", chars=2_000),
        _read_group(6, "src/keep6.py", chars=2_000),
        _read_group(7, "src/keep7.py", chars=2_000),
        _read_group(8, "src/keep8.py", chars=2_000),
    )
    _projected, state = apply_micro_compact_projection(
        messages,
        min_savings_tokens=0,
        reinjection_max_total_tokens=3_000,
    )
    assert state["applied"] is True
    reinjection = state["reinjection"]
    assert reinjection["totalTokens"] <= 3_000
    full_count = len(reinjection["injectedFiles"])
    assert full_count >= 1
    assert len(reinjection["downgradedFiles"]) >= 1
    # The most recent cleared read (group 3) is the first candidate and stays full.
    assert reinjection["injectedFiles"][0] == "src/bulk_3.py"


def test_reinjection_skips_paths_still_live_in_preserved_tail():
    # src/tail.py is read twice: once in the cleared window, once inside the
    # kept recent tail. The live read wins — no reminder for that path.
    messages = _history(
        _read_group(1, "src/tail.py", content=_big_text("older", chars=6_000)),
        _read_group(2, "src/cleared.py"),
        _read_group(3, "src/fillera.py"),
        _read_group(4, "src/fillerb.py"),
        _read_group(5, "src/fillerc.py"),
        _read_group(6, "src/fillerd.py"),
        _read_group(7, "src/keep7.py"),
        _read_group(8, "src/tail.py", content=_big_text("newer", chars=6_000)),
    )
    _projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    reinjection = state["reinjection"]
    assert "src/tail.py" in reinjection["skippedPreservedPaths"]
    all_paths = reinjection["injectedFiles"] + reinjection["downgradedFiles"]
    assert "src/tail.py" not in all_paths
    assert "src/cleared.py" in reinjection["injectedFiles"]


def test_reinjection_skips_groups_whose_results_stay_live():
    # The non-whitelisted cli_tool group is never cleared, so even though it
    # carries a file_path argument its content is still live: no candidate.
    messages = _history(
        _read_group(1, "src/live.py", tool="cli_tool"),
        _read_group(2, "src/cleared.py"),
        _read_group(3, "src/fillera.py"),
        _read_group(4, "src/fillerb.py"),
        _read_group(5, "src/fillerc.py"),
        _read_group(6, "src/fillerd.py"),
        _read_group(7, "src/keep7.py"),
        _read_group(8, "src/keep8.py"),
    )
    _projected, state = apply_micro_compact_projection(messages, min_savings_tokens=0)
    assert state["applied"] is True
    reinjection = state["reinjection"]
    all_paths = reinjection["injectedFiles"] + reinjection["downgradedFiles"]
    assert "src/live.py" not in all_paths


def test_reinjection_deterministic_and_idempotent():
    groups = [
        _read_group(index, f"src/det_{index}.py", chars=4_000) for index in range(1, 9)
    ]
    messages = _history(*groups)
    first_projected, first_state = apply_micro_compact_projection(
        messages, session_id="sess-det", min_savings_tokens=0
    )
    second_projected, second_state = apply_micro_compact_projection(
        messages, session_id="sess-det", min_savings_tokens=0
    )
    assert first_projected == second_projected
    assert (
        first_state["reinjection"]["injectedFiles"]
        == second_state["reinjection"]["injectedFiles"]
    )
    assert _reinforcement_entries(first_state) == _reinforcement_entries(second_state)

    # Idempotency: re-projecting the already-projected list finds no clearable
    # groups (placeholders are retention surface) and appends nothing.
    reapplied, reapplied_state = apply_micro_compact_projection(
        first_projected, session_id="sess-det", min_savings_tokens=0
    )
    assert reapplied_state["applied"] is False
    assert reapplied_state["rollbackReason"] == "no_clearable_groups"
    assert reapplied == first_projected


def test_reinjection_disabled_leaves_projection_unchanged():
    groups = [
        _read_group(index, f"src/off_{index}.py", chars=4_000) for index in range(1, 9)
    ]
    messages = _history(*groups)
    projected, state = apply_micro_compact_projection(
        messages,
        min_savings_tokens=0,
        reinjection_enabled=False,
    )
    assert state["applied"] is True
    assert state["reinjection"]["entries"] == []
    reminder_messages = [
        message
        for message in projected
        if isinstance(message, dict)
        and isinstance(message.get("metadata"), dict)
        and "workingSetReinjection" in message["metadata"]
    ]
    assert reminder_messages == []


def test_reinjection_not_applied_when_projection_rolls_back():
    messages = _history(
        _read_group(1, "src/tiny.py", chars=40),
        _read_group(2, "src/tinyb.py", chars=40),
        _read_group(3, "src/tinyc.py", chars=40),
        _read_group(4, "src/tinyd.py", chars=40),
        _read_group(5, "src/tinye.py", chars=40),
        _read_group(6, "src/tinyf.py", chars=40),
    )
    projected, state = apply_micro_compact_projection(
        messages, min_savings_tokens=100_000
    )
    assert state["applied"] is False
    assert projected == messages
    assert state["reinjection"]["entries"] == []


def test_reinjection_state_defaults_in_empty_state():
    state = empty_micro_compact_state()
    assert state["reinjection"]["mode"] == "working_set_reinjection"
    assert state["reinjection"]["entries"] == []
    assert state["tokenMetering"] == {"tokenSource": "estimate"}
