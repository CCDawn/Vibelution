"""Contract: a replacement checkpoint must retire the history it dropped.

The kept-window boundary is the only durable proof that survives downstream
rewrites of the payload (redaction, tool-result replacement, truncation). When
message-level identity matching finds nothing to retire, retirement falls back
to that boundary so the next replay cannot rebuild the full history and
re-trigger compression on every turn.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_context_compression_checkpoint,
    append_conversation_event,
    conversation_model_messages_from_events,
    load_conversation_events,
)


def _append(project_root, session_id, turn, kind, content):
    return append_conversation_event(
        project_root,
        session_id,
        turn,
        kind,
        status="completed",
        payload={"content": content},
    )


def test_replacement_checkpoint_retires_dropped_history_when_identity_match_fails(tmp_path):
    session_id = "retire-fallback"
    _append(tmp_path, session_id, "old", EVENT_USER_MESSAGE, "DROP-ME-OLD-REQUEST")
    _append(tmp_path, session_id, "old", EVENT_ASSISTANT_MESSAGE, "DROP-ME-OLD-ANSWER")
    kept_event = _append(tmp_path, session_id, "current", EVENT_USER_MESSAGE, "KEEP-ME-CURRENT")

    source_messages = conversation_model_messages_from_events(
        load_conversation_events(tmp_path, session_id)
    )
    assert len(source_messages) == 3
    retained_message = source_messages[-1]
    assert "KEEP-ME-CURRENT" in str(retained_message.get("content"))

    # Simulate a payload rewritten downstream: the summarized messages no
    # longer compare equal to their journal events, so identity matching alone
    # proves nothing. Only the retained boundary remains provable.
    rewritten_summary_input = [
        HumanMessage(content="DROP-ME-OLD-REQUEST [rewritten by compression]"),
        HumanMessage(content="DROP-ME-OLD-ANSWER [rewritten by compression]"),
    ]

    checkpoint = append_context_compression_checkpoint(
        tmp_path,
        session_id,
        turn_id="current",
        current_turn_id="current",
        summary="folded old history",
        level="standard",
        reason="context_pressure",
        before_tokens=1000,
        after_tokens=100,
        summarized_messages=rewritten_summary_input,
        source_messages=source_messages,
        retained_messages=[retained_message],
    )

    assert checkpoint is not None
    payload = checkpoint.payload
    assert payload["retentionMode"] == "replacement"
    assert payload["retiredEventCount"] >= 1, payload
    retired_ids = payload["retiredEventIds"]
    assert retired_ids, payload
    assert kept_event.event_id not in retired_ids

    replay = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
    contents = [str(message.get("content") or "") for message in replay]
    assert all("DROP-ME-OLD-REQUEST" not in content for content in contents), contents
    assert any("KEEP-ME-CURRENT" in content for content in contents), contents
    assert any(
        str((message.get("metadata") or {}).get("kind") or "") == "compaction_checkpoint"
        for message in replay
    ), replay


def test_replacement_checkpoint_retires_nothing_without_a_retained_boundary(tmp_path):
    """No provable kept window means no retirement: over-retiring loses history."""

    session_id = "retire-no-boundary"
    old_event = _append(tmp_path, session_id, "old", EVENT_USER_MESSAGE, "KEEP-EVERYTHING")

    checkpoint = append_context_compression_checkpoint(
        tmp_path,
        session_id,
        turn_id="old",
        current_turn_id="old",
        summary="folded old history",
        level="standard",
        reason="context_pressure",
        before_tokens=1000,
        after_tokens=100,
        summarized_messages=[HumanMessage(content="nothing matches this")],
        source_messages=[{"role": "user", "content": "unmatched source"}],
        retained_messages=[{"role": "user", "content": "unmatched retention"}],
    )

    assert checkpoint is not None
    payload = checkpoint.payload
    assert payload["retentionMode"] == "replacement"
    assert payload["retiredEventCount"] == 0, payload
    assert old_event.event_id not in payload["retiredEventIds"]
