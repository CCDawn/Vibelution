"""Guard and break-path tests for turn context compression.

`compress_turn_messages` was extracted from agent.py without a focused unit
file. These tests pin skip reasons, count/iteration bookkeeping, and the
emergency vs chat early-exit contract using injected fakes.
"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

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


class _FakeOutputCompressor:
    """compress() 直接返回 CompressionOutput（携带 summarized 边界）的假压缩器。"""

    def __init__(self, output) -> None:
        self.output = output

    def compress(self, messages, **kwargs):
        return self.output


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
        turn_runtime_fn=kwargs.pop("turn_runtime_fn", lambda: {"sessionId": "s1", "runId": "t1"}),
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


def test_compression_uses_current_session_for_checkpoint_and_tool_references(monkeypatch, tmp_path):
    from core.chat import conversation_ledger, tool_result_replacement
    from core.web.services import agent_directory_service

    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "a1",
            "sessionId": "workspace-session",
            "turnId": "workspace-turn",
        },
    )
    checkpoints = []
    references = []
    monkeypatch.setattr(
        conversation_ledger,
        "append_context_compression_checkpoint",
        lambda root, session_id, **kw: checkpoints.append((session_id, kw)) or object(),
    )
    monkeypatch.setattr(
        tool_result_replacement,
        "replace_large_tool_results_for_compression",
        lambda messages, **kw: (
            references.append(kw["session_id"]) or messages,
            {"replacements": []},
        ),
    )
    extras = {}
    _run(
        messages=[AIMessage(content="long-context-message")],
        compressor=_FakeCompressor([AIMessage(content="x")]),
        config=_feature_config(),
        project_root=str(tmp_path),
        turn_runtime_fn=dict,
        extra=extras,
        retention_contract={"sessionId": "s1", "agentId": "a1"},
    )

    assert checkpoints[0][0] == "workspace-session"
    assert checkpoints[0][1]["turn_id"] == "workspace-turn"
    assert "sessionId=workspace-session" in checkpoints[0][1]["summary"]
    assert "sessionId=s1" not in checkpoints[0][1]["summary"]
    assert references == ["workspace-session"]
    assert extras["events"][0]["kwargs"]["fields"]["sessionId"] == "workspace-session"


def test_parallel_compression_keeps_shared_agent_sessions_separate(
    monkeypatch, tmp_path
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from core.chat import conversation_ledger
    from core.web.services import agent_directory_service

    current = agent_directory_service._CURRENT_AGENT_RUNTIME
    barrier = Barrier(2)
    checkpoints = []
    monkeypatch.setattr(
        conversation_ledger,
        "append_context_compression_checkpoint",
        lambda root, session_id, **kw: (
            checkpoints.append((session_id, kw["turn_id"])) or object()
        ),
    )

    def compress(session_id):
        token = current.set(
            {"agentId": "a1", "sessionId": session_id, "turnId": f"{session_id}-turn"}
        )
        try:
            barrier.wait(timeout=5)
            return _run(
                messages=[AIMessage(content="long-context-message")],
                compressor=_FakeCompressor([AIMessage(content="x")]),
                config=_feature_config(),
                project_root=str(tmp_path),
                turn_runtime_fn=dict,
            )
        finally:
            current.reset(token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compress, ["workspace-a", "workspace-b"]))
    assert all(result[2] for result in results)
    assert sorted(checkpoints) == [
        ("workspace-a", "workspace-a-turn"),
        ("workspace-b", "workspace-b-turn"),
    ]


def test_next_turn_replays_compression_from_its_own_ledger(monkeypatch, tmp_path):
    from core.chat import conversation_ledger as ledger
    from core.chat import turn_journal
    from core.web.services import agent_directory_service
    from tools.token_manager import CompressionOutput, CompressionResult

    monkeypatch.setattr(
        turn_journal, "turn_journal_workspace_root", lambda root: tmp_path / "workspace"
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "a1",
            "sessionId": "workspace-session",
            "turnId": "current-turn",
        },
    )
    for session_id in ("s1", "workspace-session"):
        ledger.append_conversation_event(
            tmp_path,
            session_id,
            "old-turn",
            ledger.EVENT_USER_MESSAGE,
            payload={"content": f"original history of {session_id}"},
        )
    historical_message = HumanMessage(content="original history of workspace-session")
    _run(
        messages=[historical_message],
        compressor=_FakeOutputCompressor(CompressionOutput(
            [AIMessage(content="x")],
            CompressionResult("retained task summary", 40, 1),
            summarized_messages=[historical_message],
        )),
        config=_feature_config(),
        project_root=str(tmp_path),
        turn_runtime_fn=dict,
    )

    events = ledger.load_conversation_events(tmp_path, "workspace-session")
    checkpoints = [
        event
        for event in events
        if event.event_type == ledger.EVENT_COMPACTION_CHECKPOINT
    ]
    assert len(checkpoints) == 1
    assert checkpoints[0].payload["coveredEventIds"] == [events[0].event_id]
    replay = ledger.conversation_model_messages_from_events(events)
    assert "retained task summary" in str(replay)
    assert "original history of workspace-session" not in str(replay)
    other_events = ledger.load_conversation_events(tmp_path, "s1")
    assert len(other_events) == 1
    assert "original history of s1" in str(ledger.conversation_model_messages_from_events(other_events))


def test_checkpoint_receives_exact_summarized_boundary(monkeypatch, tmp_path):
    """F2 接线：checkpoint 必须拿到压缩真正折叠的消息集；无法证明边界时保持旧行为。"""
    from core.chat import conversation_ledger
    from core.web.services import agent_directory_service
    from tools.token_manager import CompressionOutput, CompressionResult

    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "a1",
            "sessionId": "workspace-session",
            "turnId": "workspace-turn",
        },
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        conversation_ledger,
        "append_context_compression_checkpoint",
        lambda root, session_id, **kw: captured.append(dict(kw)) or object(),
    )

    folded = AIMessage(content="folded-history-message")
    boundary_output = CompressionOutput(
        [AIMessage(content="x")],
        CompressionResult(
            summary="ok",
            tokens_before=100,
            tokens_after=10,
            pairs_compressed=1,
            compression_type="active",
        ),
        summarized_messages=[folded],
    )
    _run(
        messages=[AIMessage(content="long-context-message")],
        compressor=_FakeOutputCompressor(boundary_output),
        config=_feature_config(),
        project_root=str(tmp_path),
        turn_runtime_fn=dict,
    )
    assert captured
    assert captured[0]["summarized_messages"] == [folded]
    assert captured[0]["retained_messages"] == boundary_output.messages
    assert captured[0]["source_messages"] == [AIMessage(content="long-context-message")]

    # 旧式压缩器不伪造摘要覆盖域；source/retained 仍显式描述实际替换边界。
    captured.clear()
    _run(
        messages=[AIMessage(content="long-context-message")],
        compressor=_FakeCompressor([AIMessage(content="x")], summary="ok"),
        config=_feature_config(),
        project_root=str(tmp_path),
        turn_runtime_fn=dict,
    )
    assert captured
    assert "summarized_messages" not in captured[0]
    assert "source_messages" in captured[0]
    assert "retained_messages" in captured[0]


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

    assert skipped_disabled == (original, False, False, 0, 0, "")
    assert skipped_none == (original, False, False, 0, 0, "")
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
    assert gap == (original, False, False, 1, 4, "")
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
    assert maxed == (original, False, False, 2, 0, "")
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


def test_budget_fallback_continues_when_required_context_exceeds_soft_target():
    current_request = HumanMessage(content="q" * 700)
    original = [AIMessage(content="old" * 1000), current_request]
    rules = SystemMessage(content="r" * 50)
    extras = {}
    result = _run(
        messages=original,
        compressor=_FakeCompressor([rules, AIMessage(content="k" * 400), current_request]),
        config=_feature_config(), extra=extras,
        context_input_hard_limit=1000, post_compression_target_tokens=600,
    )
    assert result[0] == [rules, current_request]
    assert result[1] is False
    assert result[2] is True
    assert any(item["args"][1] == "agent.context_compression.target_unreachable" for item in extras["events"])
    fallback = next(item for item in extras["events"] if item["args"][1] == "agent.context_compression.token_budget_applied")
    assert fallback["kwargs"]["fields"]["sendTokens"] <= 1000
    assert fallback["kwargs"]["fields"]["retiredMessageCount"] == 1


def test_budget_fallback_reaches_target_even_when_summary_fits_hard_limit():
    current_request = HumanMessage(content="current request")
    rules = SystemMessage(content="rules and history summary")
    original = [AIMessage(content="old" * 1000), current_request]
    extras = {}
    result = _run(
        messages=original,
        compressor=_FakeCompressor([rules, AIMessage(content="k" * 800), current_request]),
        config=_feature_config(), extra=extras,
        context_input_hard_limit=1000, post_compression_target_tokens=600,
    )
    assert result[0] == [rules, current_request]
    assert result[1] is False
    fallback = next(item for item in extras["events"] if item["args"][1] == "agent.context_compression.token_budget_applied")
    assert fallback["kwargs"]["fields"]["sendTokens"] <= 600
    assert fallback["kwargs"]["fields"]["targetUnreachable"] is False


def test_budget_window_without_summary_cannot_retire_history_only_in_memory():
    current_request = HumanMessage(content="current request")
    original = [AIMessage(content="old" * 1000), current_request]
    extras = {}
    result = _run(
        messages=original,
        compressor=_FakeCompressor([AIMessage(content="k" * 800), current_request], summary=""),
        config=_feature_config(), extra=extras,
        context_input_hard_limit=1000, post_compression_target_tokens=600,
    )
    assert result[0] == original
    assert result[1] is True
    assert result[2] is False
    blocked = next(item for item in extras["events"] if item["args"][1] == "agent.context_budget_exhausted")
    assert blocked["kwargs"]["fields"]["guardReason"] == "budget_window_requires_summary"


def test_budget_window_persists_replacement_even_below_savings_threshold(monkeypatch, tmp_path):
    captured = []
    extras = {}
    monkeypatch.setattr(
        "core.chat.conversation_ledger.append_context_compression_checkpoint",
        lambda *args, **kwargs: captured.append(kwargs) or object(),
    )
    rules, current_request = SystemMessage(content="r" * 20), HumanMessage(content="q" * 850)
    original = [rules, AIMessage(content="old" * 40), current_request]
    result = _run(
        messages=original,
        compressor=_FakeCompressor([rules, AIMessage(content="k" * 40), current_request]),
        config=_feature_config(threshold=0.5), project_root=str(tmp_path), extra=extras,
        context_input_hard_limit=1000, post_compression_target_tokens=600,
    )
    assert result[1] is False
    assert captured, extras
    assert captured[0]["effectiveness_ratio"] < 0.5
    assert captured[0]["effective"] is True
    assert captured[0]["source_messages"] == original
    assert captured[0]["retained_messages"] == [rules, current_request]


@pytest.mark.parametrize("checkpoint_result", ["raises", "none"])
@pytest.mark.parametrize("attempt_result", ["written", "none", "raises"])
def test_budget_window_requires_a_real_checkpoint_before_continuing(
    monkeypatch, tmp_path, checkpoint_result, attempt_result,
):
    attempts = []

    def checkpoint(*args, **kwargs):
        if checkpoint_result == "raises":
            raise OSError("checkpoint unavailable")
        return None

    def attempt(*args, **kwargs):
        attempts.append(kwargs)
        if attempt_result == "raises":
            raise OSError("attempt unavailable")
        return SimpleNamespace(event_id="attempt-only") if attempt_result == "written" else None

    monkeypatch.setattr("core.chat.conversation_ledger.append_context_compression_checkpoint", checkpoint)
    monkeypatch.setattr("core.chat.conversation_ledger.append_context_compression_attempt", attempt)
    rules = SystemMessage(content="rules and history summary")
    current_request = HumanMessage(content="current request")
    original = [rules, AIMessage(content="old" * 1000), current_request]
    extras = {}
    result = _run(
        messages=original,
        compressor=_FakeCompressor([rules, AIMessage(content="k" * 800), current_request]),
        config=_feature_config(), extra=extras, project_root=str(tmp_path),
        context_input_hard_limit=1000, post_compression_target_tokens=600,
    )
    assert result == (original, True, False, 0, 0, "context_budget_exhausted")
    assert attempts[0]["status"] == "failed_preserved"
    assert attempts[0]["summary"] == ""
    assert not extras["ui"].events
    assert not any(item["args"][1] == "agent.context_compression.token_budget_applied" for item in extras["events"])
    blocked = next(item for item in extras["events"] if item["args"][1] == "agent.context_budget_exhausted")
    assert blocked["kwargs"]["fields"]["guardReason"] == "budget_window_checkpoint_not_written"
    failed = next(item for item in extras["events"] if item["args"][1] == "agent.context_compression_checkpoint_failed")
    assert failed["kwargs"]["fields"]["stage"] == "checkpoint"
    assert failed["kwargs"]["fields"]["errorType"] == ("OSError" if checkpoint_result == "raises" else "RuntimeError")


def test_unreachable_target_without_removable_history_does_not_report_budget_applied():
    rules, current_request = SystemMessage(content="r" * 20), HumanMessage(content="q" * 850)
    extras = {}
    result = _run(
        messages=[AIMessage(content="old" * 1000), current_request],
        compressor=_FakeCompressor([rules, current_request]),
        config=_feature_config(), extra=extras,
        context_input_hard_limit=1000, post_compression_target_tokens=600,
    )
    assert result[0] == [rules, current_request]
    assert result[1] is False
    codes = [item["args"][1] for item in extras["events"]]
    assert "agent.context_compression.target_unreachable" in codes
    assert "agent.context_compression.token_budget_applied" not in codes


def test_budget_fallback_fails_closed_when_required_context_and_notice_exceed_hard_limit():
    current_request = HumanMessage(content="q" * 950)
    rules = SystemMessage(content="r" * 20)
    original = [AIMessage(content="old" * 1000), current_request]
    extras = {}
    result = _run(
        messages=original, compressor=_FakeCompressor([rules, current_request]),
        config=_feature_config(), extra=extras,
        context_input_hard_limit=1000, post_compression_target_tokens=600,
    )
    assert result[0] == original
    assert result[1] is True
    assert result[2] is False
    assert any(item["args"][1] == "agent.context_budget_exhausted" for item in extras["events"])
    assert not extras["ui"].events


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
    assert evolution[1] is False
    assert chat[2] is True
    assert evolution[2] is True
    # 提前收轮走专属 stop_reason，不再借 should_break 预算通道。
    assert chat[5] == ""
    assert evolution[5] == "emergency_compression"


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

    assert result[1] is False
    assert result[3] == 1
    assert result[4] == 31
    assert result[5] == "iteration_limit_reached"


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
    assert gap == (original, False, False, 1, 4, "")
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


def test_compressor_new_unresolved_call_fails_closed_before_normalize():
    """压缩新引入的未决 tool call 必须触发门 fail-closed，而不是被静默修复。

    保留门在 normalize 之前对原始压缩输出判定；normalize 只负责修复输入中
    既有的链路损伤。新引入的断裂走 agent.context_budget_exhausted。
    """
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

    assert result[0] == original
    assert result[0] is not original
    assert result[1] is True
    blocked = [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_budget_exhausted"
    ]
    assert blocked
    fields = blocked[0]["kwargs"]["fields"]
    assert fields["guardReason"] == "retention_missing"
    assert fields["retentionBefore"]["unresolvedCallCount"] == 0
    assert fields["retentionAfter"]["unresolvedCallCount"] == 1
    # 门失败时不做 normalize，也不写 checkpoint。
    assert not [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_compression.tool_chain_normalized"
    ]


def test_compressor_new_orphan_result_fails_closed_before_normalize():
    """压缩 retire 掉 call 侧却保留结果侧（新增孤儿结果）同样 fail-closed。"""
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

    assert result[0] == original
    assert result[1] is True
    blocked = [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_budget_exhausted"
    ]
    assert blocked
    fields = blocked[0]["kwargs"]["fields"]
    assert fields["guardReason"] == "retention_missing"
    assert fields["retentionAfter"]["orphanResultCount"] == 1
    assert not [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_compression.tool_chain_normalized"
    ]


def test_pre_existing_unresolved_call_is_still_normalized():
    """输入中既有的链路损伤不由门拦截，normalize 仍是门通过后的显式修复步骤。"""
    original = [
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "pre-existing"}]),
    ]
    carried = [
        AIMessage(content="kept note", tool_calls=[{"name": "t", "args": {}, "id": "pre-existing"}]),
    ]
    extras = {}

    result = _run(
        messages=original,
        compressor=_FakeCompressor(carried, summary="ok summary"),
        config=_feature_config(),
        extra=extras,
        iteration=6,
    )

    assert result[1] is False
    assert isinstance(result[0][-1], ToolMessage)
    assert result[0][-1].tool_call_id == "pre-existing"
    assert result[0][-1].content == ABORTED_TOOL_RESULT_CONTENT
    normalized = [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_compression.tool_chain_normalized"
    ]
    assert normalized
    assert normalized[0]["kwargs"]["fields"]["synthesizedAbortedResults"] == 1
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


def test_iteration_limit_stop_reason_says_what_happened_not_budget():
    """回归：10-23 事故——iteration>30 借 should_break 返回，调用方误标为
    context_budget_exhausted（压缩明明成功）。新契约下 stop_reason 专属，
    UI 文案与日志都说「迭代上限」而非「预算」。"""
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]
    extras = {}

    result = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra=extras,
        mode=AgentMode.CHAT,
        iteration=39,
    )

    assert result[1] is False
    assert result[2] is True
    assert result[5] == "iteration_limit_reached"
    warn_logs = [message for level, message in extras["ui"].logs if level == "WARN"]
    assert any("已超上限" in message and "迭代 39" in message for message in warn_logs)
    assert not any("安全输入预算" in message for message in warn_logs)
    assert not any("提前结束当前轮次" in message for message in warn_logs)


def test_iteration_at_limit_boundary_keeps_running():
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]

    result = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra={},
        mode=AgentMode.CHAT,
        iteration=30,
    )

    assert result[1] is False
    assert result[5] == ""


def test_emergency_chat_reports_iteration_limit_instead_of_emergency():
    original = [AIMessage(content="long-context-message")]
    compressed = [AIMessage(content="x")]

    low_iter = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra={},
        mode=AgentMode.CHAT,
        compression_strategy=_FakeStrategy(CompressionLevel.EMERGENCY),
        iteration=2,
    )
    over_limit = _run(
        messages=original,
        compressor=_FakeCompressor(compressed),
        config=_feature_config(),
        extra={},
        mode=AgentMode.CHAT,
        compression_strategy=_FakeStrategy(CompressionLevel.EMERGENCY),
        iteration=31,
    )

    assert low_iter[5] == ""
    assert over_limit[5] == "iteration_limit_reached"


def test_fail_closed_budget_paths_keep_budget_stop_reason(monkeypatch, tmp_path):
    """retention/预算 fail-closed 路径的 stop_reason 必须仍是预算语义，且优先
    于迭代上限分支：iteration=39 时真实预算失败不得被「迭代上限」文案吞掉。"""
    from core.orchestration.turn_compression import STOP_REASON_CONTEXT_BUDGET_EXHAUSTED

    monkeypatch.setattr(
        "core.chat.conversation_ledger.append_context_compression_checkpoint",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("checkpoint unavailable")),
    )
    monkeypatch.setattr(
        "core.chat.conversation_ledger.append_context_compression_attempt",
        lambda *args, **kwargs: None,
    )
    rules = SystemMessage(content="rules and history summary")
    current_request = HumanMessage(content="current request")
    original = [rules, AIMessage(content="old" * 1000), current_request]
    extras = {}

    result = _run(
        messages=original,
        compressor=_FakeCompressor([rules, AIMessage(content="k" * 800), current_request]),
        config=_feature_config(),
        extra=extras,
        project_root=str(tmp_path),
        mode=AgentMode.CHAT,
        iteration=39,
        context_input_hard_limit=1000,
        post_compression_target_tokens=600,
    )

    assert result[1] is True
    assert result[5] == STOP_REASON_CONTEXT_BUDGET_EXHAUSTED
    exhausted = [
        item
        for item in extras["events"]
        if item["args"][1] == "agent.context_budget_exhausted"
    ]
    assert exhausted
    assert exhausted[0]["kwargs"]["outcome"] == "blocked"
