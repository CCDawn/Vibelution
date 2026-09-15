"""Guard and break-path tests for turn context compression.

`compress_turn_messages` was extracted from agent.py without a focused unit
file. These tests pin skip reasons, count/iteration bookkeeping, and the
emergency vs chat early-exit contract using injected fakes.
"""

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core.orchestration.agent_modes import AgentMode
from core.orchestration.turn_compression import (
    ABORTED_TOOL_RESULT_CONTENT,
    compress_turn_messages,
    normalize_tool_call_pairing,
)
from tools.compression_strategy import CompressionConfig, CompressionLevel


class _FakeUi:
    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []
        self.events: list[dict] = []

    def add_log(self, message: str, level: str = "INFO") -> None:
        self.logs.append((level, message))

    def note_context_compression_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class _FakeCompressor:
    def __init__(self, result, summary: str = "compressed") -> None:
        self.result = result
        self.summary = summary
        self.calls: list[dict] = []

    def compress(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), **kwargs})
        return self.result, self.summary


class _FakeStrategy:
    def __init__(self, level: CompressionLevel = CompressionLevel.STANDARD) -> None:
        self.level = level

    def determine_level_with_iteration(self, *args):
        return self.level

    def get_config(self, level, current_tokens, budget):
        return CompressionConfig(level=level, summary_max_chars=80, keep_ai_messages=2)


def _feature_config(*, enabled: bool = True, max_compressions: int = 3, threshold: float = 0.0):
    return SimpleNamespace(
        mental_model=SimpleNamespace(enabled=False),
        context_compression=SimpleNamespace(
            enabled=enabled,
            max_compressions_per_session=max_compressions,
            effectiveness_threshold=threshold,
        ),
        pet=SimpleNamespace(enabled=False),
        memory=SimpleNamespace(
            semantic_memory_enabled=False,
            llm_extraction_enabled=False,
            llm_summary_enabled=False,
        ),
        supervised_evolution=SimpleNamespace(enabled=False, mental_model_enabled=False),
        agent=SimpleNamespace(
            modes=SimpleNamespace(
                supervised_evolution_enabled=False,
                self_evolution_enabled=False,
            )
        ),
    )


def _estimate(messages) -> int:
    return sum(len(str(getattr(item, "content", "") or "")) for item in messages)


def _run(*, messages, compressor, config, extra=None, **kwargs):
    events: list[dict] = []
    ui = _FakeUi()
    result = compress_turn_messages(
        messages=messages,
        iteration=kwargs.pop("iteration", 4),
        reason=kwargs.pop("reason", "test"),
        token_compressor=compressor,
        config=config,
        effective_max_token_limit=kwargs.pop("effective_max_token_limit", 1000),
        threshold_tokens=kwargs.pop("threshold_tokens", 800),
        runtime_agent_binding={"agentId": "a1", "directSessionId": "s1"},
        project_root=kwargs.pop("project_root", ""),
        mode=kwargs.pop("mode", AgentMode.CHAT),
        last_compression_iteration=kwargs.pop("last_compression_iteration", 0),
        compression_min_iteration_gap=kwargs.pop("compression_min_iteration_gap", 3),
        compression_count_this_turn=kwargs.pop("compression_count_this_turn", 0),
        compression_strategy=kwargs.pop("compression_strategy", _FakeStrategy()),
        prompt_manager=None,
        turn_runtime_fn=lambda: {"sessionId": "s1", "runId": "t1"},
        estimate_tokens_fn=_estimate,
        get_ui_fn=lambda: ui,
        get_state_manager_fn=lambda: SimpleNamespace(set_state=lambda *a, **k: None),
        scene_recorder_fn=lambda *a, **k: events.append({"args": a, "kwargs": k}),
        **kwargs,
    )
    if extra is not None:
        extra["ui"] = ui
        extra["events"] = events
    return result


def test_disabled_feature_or_missing_compressor_skips_without_counting():
    original = [HumanMessage(content="hello"), AIMessage(content="world")]
    compressor = _FakeCompressor(original)

    skipped_disabled = _run(
        messages=original,
        compressor=compressor,
        config=_feature_config(enabled=False),
        extra={},
    )
    skipped_none = _run(
        messages=original,
        compressor=None,
        config=_feature_config(enabled=True),
        extra={},
    )

    assert skipped_disabled == (original, False, False, 0, 0)
    assert skipped_none == (original, False, False, 0, 0)
    assert compressor.calls == []


def test_iteration_gap_and_max_compressions_skip_without_calling_compressor():
    original = [AIMessage(content="keep")]
    compressor = _FakeCompressor([AIMessage(content="x")])
    extras = {}

    gap = _run(
        messages=original,
        compressor=compressor,
        config=_feature_config(),
        extra=extras,
        iteration=5,
        last_compression_iteration=4,
        compression_min_iteration_gap=3,
        compression_count_this_turn=1,
    )
    assert gap == (original, False, False, 1, 4)
    assert extras["events"][0]["kwargs"]["fields"]["guardReason"] == "iteration_gap"

    extras = {}
    maxed = _run(
        messages=original,
        compressor=compressor,
        config=_feature_config(max_compressions=2),
        extra=extras,
        iteration=9,
        last_compression_iteration=0,
        compression_count_this_turn=2,
    )
    assert maxed == (original, False, False, 2, 0)
    assert extras["events"][0]["kwargs"]["fields"]["guardReason"] == "max_compressions"
    assert compressor.calls == []


def test_successful_compression_updates_count_and_marks_applied():
    original = [AIMessage(content="a" * 40), AIMessage(content="b" * 40)]
    compressed = [AIMessage(content="short")]
    compressor = _FakeCompressor(compressed, summary="ok")

    result = _run(
        messages=original,
        compressor=compressor,
        config=_feature_config(),
        extra={},
        iteration=6,
        last_compression_iteration=0,
    )

    assert result[0] == compressed
    assert result[1] is False
    assert result[2] is True
    assert result[3] == 1
    assert result[4] == 6
    assert compressor.calls
    assert compressor.calls[0]["use_llm_summary"] is False


def test_explicit_trigger_source_overrides_reason_guessing():
    original = [AIMessage(content="a" * 40), AIMessage(content="b" * 40)]
    extras = {}

    result = _run(
        messages=original,
        compressor=_FakeCompressor([AIMessage(content="short")], summary="ok"),
        config=_feature_config(),
        extra=extras,
        iteration=6,
        trigger_source="provider_limit",
    )

    assert result[2] is True
    assert extras["ui"].events[-1]["trigger_source"] == "provider_limit"


def test_ineffective_compression_still_returns_compressor_output_and_consumes_slot():
    original = [AIMessage(content="same-size-message")]
    compressor = _FakeCompressor(original, summary="")
    extras = {}

    result = _run(
        messages=original,
        compressor=compressor,
        config=_feature_config(threshold=0.5),
        extra=extras,
        iteration=3,
    )

    assert result[0] is original
    assert result[2] is False
    assert result[3] == 1
    assert result[4] == 3
    skipped = [item for item in extras["events"] if item["args"][1] == "agent.context_compression.skipped"]
    assert skipped
    assert skipped[0]["kwargs"]["fields"]["guardReason"] == "no_compressible_history"


def test_emergency_breaks_non_chat_but_not_chat_mode():
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]
    strategy = _FakeStrategy(CompressionLevel.EMERGENCY)

    chat = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra={},
        mode=AgentMode.CHAT,
        compression_strategy=strategy,
        iteration=2,
    )
    evolution = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra={},
        mode=AgentMode.SELF_EVOLUTION,
        compression_strategy=strategy,
        iteration=2,
    )

    assert chat[1] is False
    assert evolution[1] is True
    assert chat[2] is True
    assert evolution[2] is True


def test_iteration_over_thirty_breaks_even_in_chat():
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]

    result = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra={},
        mode=AgentMode.CHAT,
        iteration=31,
    )

    assert result[1] is True
    assert result[3] == 1
    assert result[4] == 31


def test_compress_coerces_iteration_gap_json_binding_and_rejects_character_split():
    original = [AIMessage(content="keep")]
    compressor = _FakeCompressor([AIMessage(content="x")])
    extras = {}

    gap = _run(
        messages=original,
        compressor=compressor,
        config=_feature_config(),
        extra=extras,
        iteration="5",
        last_compression_iteration="4",
        compression_min_iteration_gap="3",
        compression_count_this_turn="1",
    )
    assert gap == (original, False, False, 1, 4)
    assert extras["events"][0]["kwargs"]["fields"]["guardReason"] == "iteration_gap"
    assert extras["events"][0]["kwargs"]["fields"]["iteration"] == 5

    split_compressor = _FakeCompressor([], summary="ok")
    extras = {}
    events: list[dict] = []
    ui = _FakeUi()
    result = compress_turn_messages(
        messages="abc",
        iteration=4,
        reason=b"test",
        token_compressor=split_compressor,
        config=_feature_config(),
        effective_max_token_limit="bad",
        threshold_tokens="800",
        runtime_agent_binding='{"agent_id":"a9","direct_session_id":"s9"}',
        project_root="",
        mode=b"chat",
        last_compression_iteration=0,
        compression_min_iteration_gap=3,
        compression_count_this_turn=0,
        compression_strategy=_FakeStrategy(),
        prompt_manager=None,
        turn_runtime_fn=lambda: {"session_id": "s9", "run_id": "t9"},
        estimate_tokens_fn=_estimate,
        get_ui_fn=lambda: ui,
        get_state_manager_fn=lambda: SimpleNamespace(set_state=lambda *a, **k: None),
        scene_recorder_fn=lambda *a, **k: events.append({"args": a, "kwargs": k}),
    )
    assert result[0] == []
    assert split_compressor.calls[0]["messages"] == []
    assert events[0]["kwargs"]["fields"]["agentId"] == "a9"
    assert events[0]["kwargs"]["fields"]["sessionId"] == "s9"
    assert events[0]["kwargs"]["fields"]["turnId"] == "t9"
    assert events[0]["kwargs"]["fields"]["effectiveLimit"] == 1


def test_emergency_bytes_chat_mode_does_not_break():
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]
    result = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra={},
        mode=b"chat",
        compression_strategy=_FakeStrategy(CompressionLevel.EMERGENCY),
        iteration=2,
    )
    assert result[1] is False
    assert result[2] is True


def test_compress_unwraps_message_envelope_without_treating_true_as_iteration_one():
    original = [AIMessage(content="keep")]
    compressor = _FakeCompressor([AIMessage(content="x")])
    extras = {}
    result = _run(
        messages={"messages": original},
        compressor=compressor,
        config=_feature_config(),
        extra=extras,
        iteration=True,
    )
    assert compressor.calls[0]["messages"] == original
    assert result[1] is False
    assert result[4] == 0
    assert extras["events"][0]["kwargs"]["fields"]["iteration"] == 0

    json_compressor = _FakeCompressor([AIMessage(content="x")])
    json_result = _run(
        messages=b'{"history": [{"role": "assistant", "content": "keep"}]}',
        compressor=json_compressor,
        config=_feature_config(),
        extra={},
        iteration=4,
    )
    assert json_compressor.calls[0]["messages"] == [{"role": "assistant", "content": "keep"}]
    assert json_result[0] == [AIMessage(content="x")]


def test_ledger_checkpoint_failure_records_tokens_without_summary_body(monkeypatch, tmp_path):
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]
    extras = {}

    monkeypatch.setattr(
        "core.chat.conversation_ledger.append_context_compression_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("checkpoint boom")),
    )
    monkeypatch.setattr(
        "core.chat.conversation_ledger.append_context_compression_attempt",
        lambda *_args, **_kwargs: SimpleNamespace(event_id="attempt-1"),
    )

    result = _run(
        messages=original,
        compressor=_FakeCompressor(compressed, summary="secret compression summary"),
        config=_feature_config(),
        extra=extras,
        project_root=str(tmp_path),
        reason="context_pressure",
    )

    failed = [
        item for item in extras["events"] if item["args"][1] == "agent.context_compression_checkpoint_failed"
    ]
    assert failed
    fields = failed[0]["kwargs"]["fields"]
    assert fields["errorType"] == "RuntimeError"
    assert fields["sessionId"] == "s1"
    assert fields["turnId"] == "t1"
    assert fields["reason"] == "context_pressure"
    assert fields["stage"] == "checkpoint"
    assert fields["beforeTokens"] > fields["afterTokens"]
    assert "secret compression summary" not in str(extras["events"])
    assert [
        item for item in extras["events"] if item["args"][1] == "session.context_compression.ledger_failed"
    ] == []
    assert result[2] is True


def test_normalize_tool_call_pairing_drops_orphans_and_synthesizes_aborted():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "web_search_tool", "args": {}, "id": "call-1"}]),
        ToolMessage(content="orphan result without call", tool_call_id="call-gone"),
        AIMessage(content="", tool_calls=[{"name": "fetch_tool", "args": {}, "id": "call-2"}]),
    ]

    normalized, stats = normalize_tool_call_pairing(messages)

    assert stats == {"droppedOrphanResults": 1, "synthesizedAbortedResults": 2}
    assert [getattr(item, "tool_call_id", None) for item in normalized] == [
        None,
        "call-1",
        None,
        "call-2",
    ]
    assert isinstance(normalized[1], ToolMessage)
    assert normalized[1].content == ABORTED_TOOL_RESULT_CONTENT
    assert normalized[1].name == "web_search_tool"
    assert normalized[3].content == ABORTED_TOOL_RESULT_CONTENT


def test_normalize_tool_call_pairing_handles_provider_dict_messages():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "d1", "function": {"name": "shell"}}]},
        {"role": "tool", "content": "stale", "tool_call_id": "d9"},
    ]

    normalized, stats = normalize_tool_call_pairing(messages)

    assert stats == {"droppedOrphanResults": 1, "synthesizedAbortedResults": 1}
    assert normalized[0]["tool_calls"][0]["id"] == "d1"
    repaired = normalized[1]
    assert repaired["role"] == "tool"
    assert repaired["tool_call_id"] == "d1"
    assert repaired["content"] == ABORTED_TOOL_RESULT_CONTENT
    assert repaired["metadata"]["kind"] == "interrupted_tool_result"
    assert repaired["metadata"]["status"] == "aborted"
    assert repaired["metadata"]["toolName"] == "shell"


def test_compressor_unresolved_call_is_normalized_and_audited():
    original = [AIMessage(content="long-context-message")]
    broken = [AIMessage(content="", tool_calls=[{"name": "fetch_tool", "args": {}, "id": "call-new"}])]
    extras = {}

    result = _run(
        messages=original,
        compressor=_FakeCompressor(broken, summary="broken summary"),
        config=_feature_config(),
        extra=extras,
        iteration=6,
    )

    assert result[1] is False
    assert isinstance(result[0][-1], ToolMessage)
    assert result[0][-1].tool_call_id == "call-new"
    assert result[0][-1].content == ABORTED_TOOL_RESULT_CONTENT
    normalized = [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_compression.tool_chain_normalized"
    ]
    assert normalized
    fields = normalized[0]["kwargs"]["fields"]
    assert fields["synthesizedAbortedResults"] == 1
    assert fields["droppedOrphanResults"] == 0
    assert not [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_budget_exhausted"
    ]


def test_compressor_orphan_result_is_dropped_before_the_gate():
    original = [
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
        ToolMessage(content="r1", tool_call_id="c1"),
    ]
    broken = [
        AIMessage(content="summary note"),
        ToolMessage(content="late result", tool_call_id="c-gone"),
    ]
    extras = {}

    result = _run(
        messages=original,
        compressor=_FakeCompressor(broken, summary="broken summary"),
        config=_feature_config(),
        extra=extras,
        iteration=6,
    )

    assert result[1] is False
    assert all(getattr(item, "tool_call_id", None) != "c-gone" for item in result[0])
    normalized = [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_compression.tool_chain_normalized"
    ]
    assert normalized
    assert normalized[0]["kwargs"]["fields"]["droppedOrphanResults"] == 1
    assert not [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_budget_exhausted"
    ]


def test_ledger_fallback_failure_records_session_ledger_failed(monkeypatch, tmp_path):
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]
    extras = {}

    monkeypatch.setattr(
        "core.chat.conversation_ledger.append_context_compression_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("checkpoint boom")),
    )
    monkeypatch.setattr(
        "core.chat.conversation_ledger.append_context_compression_attempt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("attempt boom")),
    )

    _run(
        messages=original,
        compressor=_FakeCompressor(compressed, summary="secret compression summary"),
        config=_feature_config(),
        extra=extras,
        project_root=str(tmp_path),
        reason="context_pressure",
    )

    ledger_failed = [
        item for item in extras["events"] if item["args"][1] == "session.context_compression.ledger_failed"
    ]
    assert ledger_failed
    fields = ledger_failed[0]["kwargs"]["fields"]
    assert ledger_failed[0]["kwargs"]["level"] == "warning"
    assert ledger_failed[0]["kwargs"]["outcome"] == "failed"
    assert fields["errorType"] == "OSError"
    assert fields["checkpointErrorType"] == "RuntimeError"
    assert fields["stage"] == "attempt_fallback"
    assert fields["beforeTokens"] > 0
    assert fields["reason"] == "context_pressure"
    assert "secret compression summary" not in str(extras["events"])
