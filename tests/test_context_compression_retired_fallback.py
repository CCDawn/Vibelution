"""Contract: a replacement checkpoint must retire the history it dropped.

The kept-window boundary is the only durable proof that survives downstream
rewrites of the payload (redaction, tool-result replacement, truncation). When
message-level identity matching finds nothing to retire, retirement falls back
to that boundary so the next replay cannot rebuild the full history and
re-trigger compression on every turn.
"""

from __future__ import annotations

import pytest
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


@pytest.mark.parametrize("level", ["standard", "deep"])
def test_budgeted_long_facts_survive_real_checkpoint_replay_and_second_compression(tmp_path, monkeypatch, level):
    import json
    from types import SimpleNamespace
    from langchain_core.messages import SystemMessage
    from core.infrastructure import developer_sandbox
    from core.orchestration.turn_message_assembly import langchain_messages_from_conversation_layer
    from core.web.services import agent_directory_service
    from tests.test_compression_summary_retention import _compressor
    from tests.test_turn_compression import _feature_config, _run
    from tools.compression_strategy import CompressionConfig, CompressionLevel
    from tools.compression_summary_retention import retained_user_facts
    from tools.token_manager import estimate_messages_tokens

    config_path = tmp_path / "operator.toml"
    config_path.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *_a, **_k: tmp_path / "workspace")
    session_id = "long-facts-replay"
    fact = "Remember this exact identifier: " + "LITERAL-FACT-" * 850 + "."
    assert len(fact) > 8_000
    old_history = "SOURCE-ONLY-LARGE-HISTORY " * 3000 + "\n" + fact
    source_event = _append(tmp_path, session_id, "old", EVENT_USER_MESSAGE, old_history)
    _append(tmp_path, session_id, "old", EVENT_ASSISTANT_MESSAGE, "Completed earlier work.")
    _append(tmp_path, session_id, "kept", EVENT_USER_MESSAGE, "Earlier filler.")
    _append(tmp_path, session_id, "kept", EVENT_ASSISTANT_MESSAGE, "Kept window starts.")
    kept_fact = "Remember this kept identifier: KEPT-B-203."
    kept_event = _append(tmp_path, session_id, "kept", EVENT_USER_MESSAGE, kept_fact)
    _append(tmp_path, session_id, "kept", EVENT_ASSISTANT_MESSAGE, "Kept window ends.")
    _append(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE, "Continue first step.")
    compressor = _compressor(monkeypatch, llm=True)
    chosen_level = CompressionLevel[level.upper()]
    strategy = SimpleNamespace(
        determine_level_with_iteration=lambda *_a: chosen_level,
        get_config=lambda *_a: CompressionConfig(level=chosen_level,
            summary_max_chars=100, keep_ai_messages=2, preserve_errors=False),
    )
    estimate = estimate_messages_tokens
    prior_checkpoint = None
    for number in (1, 2):
        turn = f"turn-{number}"
        monkeypatch.setattr(agent_directory_service, "current_agent_runtime",
            lambda turn=turn: {"sessionId": session_id, "turnId": turn, "agentId": "ordinary-agent"})
        events = load_conversation_events(tmp_path, session_id)
        source = conversation_model_messages_from_events(events)
        messages = [SystemMessage(content="policy"), *langchain_messages_from_conversation_layer(source)]
        assert estimate(messages) > 18_000
        extras = {}
        result = _run(messages=messages, compressor=compressor, config=_feature_config(), extra=extras,
            project_root=str(tmp_path), compression_strategy=strategy,
            context_input_hard_limit=40_000, post_compression_target_tokens=15_000,
            threshold_tokens=18_000, effective_max_token_limit=40_000,
            estimate_tokens_fn=estimate, iteration=number * 4,
            turn_runtime_fn=lambda turn=turn: {"sessionId": session_id, "runId": turn})
        assert result[1] is False, json.dumps({"round": number, "guards": [event["kwargs"]["fields"].get("guardReason")
            for event in extras["events"] if event["args"][1] == "agent.context_budget_exhausted"]})
        checkpoints = [event for event in load_conversation_events(tmp_path, session_id)
                       if event.event_type == "compaction_checkpoint"]
        assert len(checkpoints) == number
        checkpoint = checkpoints[-1]
        assert retained_user_facts([], [checkpoint.payload["summary"]]) == [fact, kept_fact]
        assert len(checkpoint.payload["summary"]) > 8_000
        covered = checkpoint.payload["coveredEventIds"]
        assert (source_event.event_id if number == 1 else prior_checkpoint.event_id) in covered
        if number == 1:
            assert kept_event.event_id not in covered
            assert kept_event.event_id not in checkpoint.payload.get("retiredEventIds", [])
        replay = conversation_model_messages_from_events(load_conversation_events(tmp_path, session_id))
        assert not any(row.get("metadata", {}).get("eventId") == source_event.event_id for row in replay)
        checkpoint_rows = [row for row in replay if row.get("metadata", {}).get("kind") == "compaction_checkpoint"]
        assert len(checkpoint_rows) == 1
        assert retained_user_facts([], [checkpoint_rows[0]["content"]]) == [fact, kept_fact]
        assert all("SOURCE-ONLY-LARGE-HISTORY" not in row.get("content", "") for row in replay)
        assert estimate(replay) < 20_000
        prior_checkpoint = checkpoint
        if number == 1:
            _append(tmp_path, session_id, turn, EVENT_ASSISTANT_MESSAGE, "SECOND-ROUND-NOISE " * 4000)
            _append(tmp_path, session_id, "turn-2", EVENT_USER_MESSAGE, "Continue second step.")


@pytest.mark.parametrize("source_kind", ["kept_user", "kept_checkpoint", "forged", "not_filtered", "future",
    "other_session", "scoped", "assistant", "tool", "hidden", "reordered", "forged_checkpoint", "derived_payload"])
def test_extra_checkpoint_facts_require_ordered_active_ordinary_user_sources(tmp_path, source_kind):
    from dataclasses import replace
    from core.chat.compaction_fact_recovery import recover_legacy_checkpoint_facts
    from tools.compression_summary_retention import compose_retained_summary

    session_id = "source-bound-extra-facts"
    fact_a = "Remember covered exact value: " + "LARGE-A-" * 1200 + "."
    fact_b = "Remember kept exact value: B-229."
    a = _append(tmp_path, session_id, "old", EVENT_USER_MESSAGE, fact_a)
    b = _append(tmp_path, session_id, "kept", EVENT_USER_MESSAGE, fact_b)
    kept_checkpoint = None
    if source_kind in {"kept_checkpoint", "forged_checkpoint"}:
        kept_checkpoint = append_conversation_event(tmp_path, session_id, "kept-cp", "compaction_checkpoint",
            status="completed", payload={"summary": compose_retained_summary([fact_b], [], "", 1000),
                "coveredEventIds": [b.event_id] if source_kind == "kept_checkpoint" else []})
    summary_facts = [fact_b, fact_a] if source_kind == "reordered" else [fact_a,
        "Remember FORGED value: C-991." if source_kind in {"forged", "derived_payload"} else fact_b]
    checkpoint = append_conversation_event(tmp_path, session_id, "current-cp", "compaction_checkpoint",
        status="completed", payload={"summary": compose_retained_summary(summary_facts, [], "", 20_000),
                                    "coveredEventIds": [a.event_id]})
    if source_kind == "future":
        b = replace(b, sequence=checkpoint.sequence + 1)
    elif source_kind == "other_session":
        b = replace(b, session_id="other-session")
    elif source_kind == "scoped":
        b = replace(b, payload={**b.payload, "scopeHash": "other-scope"})
    elif source_kind in {"assistant", "tool"}:
        b = replace(b, event_type=EVENT_ASSISTANT_MESSAGE if source_kind == "assistant" else "tool_result",
                    provider_role="assistant" if source_kind == "assistant" else "tool")
    elif source_kind == "hidden":
        b = replace(b, visible_in_model=False)
    events = [a, b, *([kept_checkpoint] if kept_checkpoint else []), checkpoint]
    filtered = [kept_checkpoint or b, checkpoint] if source_kind != "not_filtered" else [checkpoint]
    if source_kind == "derived_payload":
        filtered[0] = replace(b, payload={"content": summary_facts[-1]})
    recovered = recover_legacy_checkpoint_facts(events, filtered)
    restored_a = a.event_id in {event.event_id for event in recovered}
    assert restored_a is (source_kind not in {"kept_user", "kept_checkpoint"})
