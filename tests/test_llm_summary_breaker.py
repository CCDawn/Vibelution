"""LLM summary failure breaker + explicit degradation tests.

Pins the compaction-review decision: a failing DEEP/EMERGENCY LLM summary must
fall back to the rule summary audibly (structured scene event with the failure
summary, fallback type and consecutive-failure count), trip a circuit breaker
after 3 consecutive failures that degrades *automatic* full compression to the
rule summary, reset on one success, and never intercept manual/explicit
compression requests. Threshold 0 disables the pause but keeps the explicit
fallback events. Design anchor: ZCode CLI compact/policy.ts
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from core.orchestration import llm_summary_breaker
from core.orchestration.agent_modes import AgentMode
from core.orchestration.turn_compression import compress_turn_messages
from tools.compression_strategy import CompressionConfig, CompressionLevel
from tools.token_manager import EnhancedTokenCompressor


@pytest.fixture(autouse=True)
def _isolated_breaker_state():
    llm_summary_breaker.reset_all()
    yield
    llm_summary_breaker.reset_all()


# ---------------------------------------------------------------------------
# Breaker unit semantics
# ---------------------------------------------------------------------------


def test_record_failure_counts_and_trips_at_threshold():
    for expected in (1, 2):
        state = llm_summary_breaker.record_failure(
            "s-break", error_text=f"boom {expected}", threshold=3
        )
        assert state["consecutiveFailures"] == expected
        assert state["breakerTripped"] is False
        assert state["breakerOpen"] is False

    state = llm_summary_breaker.record_failure("s-break", error_text="boom 3", threshold=3)
    assert state["consecutiveFailures"] == 3
    assert state["breakerTripped"] is True
    assert state["breakerOpen"] is True
    assert llm_summary_breaker.is_open("s-break") is True
    assert llm_summary_breaker.consecutive_failures("s-break") == 3


def test_success_resets_counter_and_releases_breaker():
    for _ in range(3):
        llm_summary_breaker.record_failure("s-reset", error_text="down", threshold=3)
    assert llm_summary_breaker.is_open("s-reset") is True

    state = llm_summary_breaker.record_success("s-reset")
    assert state["breakerReleased"] is True
    assert state["consecutiveFailures"] == 0
    assert llm_summary_breaker.is_open("s-reset") is False

    # One more failure after release starts from 1 and does not trip.
    state = llm_summary_breaker.record_failure("s-reset", error_text="down again", threshold=3)
    assert state["consecutiveFailures"] == 1
    assert state["breakerTripped"] is False


def test_threshold_zero_disables_trip_but_keeps_counting():
    for _ in range(5):
        state = llm_summary_breaker.record_failure("s-zero", error_text="down", threshold=0)
    assert state["consecutiveFailures"] == 5
    assert state["breakerOpen"] is False
    assert llm_summary_breaker.is_open("s-zero") is False


def test_scopes_are_isolated_by_session():
    for _ in range(3):
        llm_summary_breaker.record_failure("s-a", error_text="down", threshold=3)
    assert llm_summary_breaker.is_open("s-a") is True
    assert llm_summary_breaker.is_open("s-b") is False
    assert llm_summary_breaker.consecutive_failures("s-b") == 0


def test_error_summary_is_bounded_and_single_line():
    state = llm_summary_breaker.record_failure(
        "s-err", error_text="line1\nline2\n" + "x" * 400, threshold=3
    )
    summary = state["errorSummary"]
    assert len(summary) <= llm_summary_breaker._ERROR_SUMMARY_MAX_CHARS
    assert "\n" not in summary
    assert summary.startswith("line1 line2")


def test_reporter_emits_fallback_trip_and_release_events():
    events: list[dict] = []

    def recorder(*args, **kwargs):
        events.append({"args": args, "kwargs": kwargs})

    reporter = llm_summary_breaker.SummaryBreakerReporter(
        session_id="s-report",
        turn_id="t1",
        iteration=4,
        threshold=3,
        trigger_source="auto",
        recorder=recorder,
    )

    reporter.on_failure("provider timeout")
    codes = [e["args"][1] for e in events]
    assert codes == ["agent.context_compression.llm_summary_fallback"]
    fields = events[0]["kwargs"]["fields"]
    assert fields["consecutiveFailures"] == 1
    assert fields["fallbackType"] == "rule_based_summary"
    assert fields["errorSummary"] == "provider timeout"
    assert fields["sessionId"] == "s-report"

    reporter.on_failure("provider timeout")
    reporter.on_failure("provider timeout")
    codes = [e["args"][1] for e in events]
    assert codes[-1] == "agent.context_compression.llm_summary_breaker_tripped"
    trip = events[-1]["kwargs"]
    assert trip["outcome"] == "paused"
    assert trip["fields"]["consecutiveFailures"] == 3

    reporter.on_success()
    codes = [e["args"][1] for e in events]
    assert codes[-1] == "agent.context_compression.llm_summary_breaker_released"
    release = events[-1]["kwargs"]
    assert release["outcome"] == "resumed"
    assert release["fields"]["consecutiveFailures"] == 0


def test_reporter_threshold_zero_keeps_fallback_events_without_trip():
    events: list[dict] = []
    reporter = llm_summary_breaker.SummaryBreakerReporter(
        session_id="s-report-zero",
        threshold=0,
        recorder=lambda *a, **k: events.append({"args": a, "kwargs": k}),
    )
    for _ in range(5):
        reporter.on_failure("down")
    reporter.on_success()

    codes = [e["args"][1] for e in events]
    assert codes.count("agent.context_compression.llm_summary_fallback") == 5
    assert "agent.context_compression.llm_summary_breaker_tripped" not in codes
    assert "agent.context_compression.llm_summary_breaker_released" not in codes


# ---------------------------------------------------------------------------
# Integration: real compressor + compress_turn_messages trigger chain
# ---------------------------------------------------------------------------


class _FailingSummaryLlm:
    """Compression LLM whose invoke always raises (provider down)."""

    def invoke(self, messages, tools=None, metadata=None):
        raise RuntimeError("simulated summary provider outage")


class _SucceedingSummaryLlm:
    """Compression LLM returning a normal summary."""

    def invoke(self, messages, tools=None, metadata=None):
        class _Response:
            content = "LLM 摘要内容"

        return _Response()


class _FakeUi:
    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []
        self.events: list[dict] = []

    def add_log(self, message: str, level: str = "INFO") -> None:
        self.logs.append((level, message))

    def note_context_compression_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class _DeepStrategy:
    def determine_level_with_iteration(self, *args):
        return CompressionLevel.DEEP

    def get_config(self, level, current_tokens, budget):
        return CompressionConfig(level=level, summary_max_chars=120, keep_ai_messages=2)


def _estimate(messages) -> int:
    return sum(len(str(getattr(item, "content", "") or "")) for item in messages)


def _compressor_with(llm) -> EnhancedTokenCompressor:
    return EnhancedTokenCompressor(token_budget=4000, compression_llm=llm)


def _messages() -> list:
    return [
        HumanMessage(content="外部任务：写一个爬虫"),
        AIMessage(content="第一轮回答 " + "a" * 200),
        AIMessage(content="第二轮回答 " + "b" * 200),
        AIMessage(content="第三轮回答 " + "c" * 200),
        AIMessage(content="第四轮回答 " + "d" * 200),
    ]


def _run_compression(
    *,
    compressor,
    config,
    trigger_source="auto",
    session_id="s-int",
    events=None,
    ui=None,
):
    ui = ui or _FakeUi()
    result = compress_turn_messages(
        messages=_messages(),
        iteration=4,
        reason="token pressure",
        token_compressor=compressor,
        config=config,
        effective_max_token_limit=1000,
        threshold_tokens=800,
        runtime_agent_binding={"agentId": "agent-1", "directSessionId": session_id},
        project_root="",
        mode=AgentMode.CHAT,
        last_compression_iteration=0,
        compression_min_iteration_gap=3,
        compression_count_this_turn=0,
        compression_strategy=_DeepStrategy(),
        prompt_manager=None,
        turn_runtime_fn=lambda: {"sessionId": session_id, "runId": "t1"},
        estimate_tokens_fn=_estimate,
        get_ui_fn=lambda: ui,
        get_state_manager_fn=lambda: type("S", (), {"set_state": staticmethod(lambda *a, **k: None)})(),
        scene_recorder_fn=lambda *a, **k: events.append({"args": a, "kwargs": k}) if events is not None else None,
        trigger_source=trigger_source,
    )
    return result, ui


def _feature_config(threshold: int = 3):
    from types import SimpleNamespace

    return SimpleNamespace(
        mental_model=SimpleNamespace(enabled=False),
        context_compression=SimpleNamespace(
            enabled=True,
            max_compressions_per_session=20,
            effectiveness_threshold=0.0,
            llm_summary_failure_breaker_threshold=threshold,
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


def _event_codes(events) -> list[str]:
    return [e["args"][1] for e in events]


def test_single_llm_failure_falls_back_to_rule_summary_with_event():
    events: list[dict] = []
    compressor = _compressor_with(_FailingSummaryLlm())
    config = _feature_config(threshold=3)

    compressed, should_break, applied, count, last_iter = _run_compression(
        compressor=compressor,
        config=config,
        trigger_source="auto",
        session_id="s-single",
        events=events,
    )[0]

    assert should_break is False
    assert applied is True  # rule summary still shrank the context
    assert count == 1

    codes = _event_codes(events)
    assert "agent.context_compression.llm_summary_fallback" in codes
    fallback = next(
        e for e in events
        if e["args"][1] == "agent.context_compression.llm_summary_fallback"
    )
    fields = fallback["kwargs"]["fields"]
    assert fields["consecutiveFailures"] == 1
    assert fields["fallbackType"] == "rule_based_summary"
    assert "simulated summary provider outage" in fields["errorSummary"]
    assert fields["sessionId"] == "s-single"

    assert llm_summary_breaker.consecutive_failures("s-single") == 1
    assert llm_summary_breaker.is_open("s-single") is False

    # The compressor actually attempted the LLM (use_llm_summary=True) and the
    # degradation was reported through the reporter hook, not the silent path.
    summary_messages = [m for m in compressed if "历史摘要" in str(getattr(m, "content", ""))]
    assert summary_messages, "rule fallback summary must still be applied"


def test_three_consecutive_failures_trip_breaker_and_pause_auto_compression():
    events: list[dict] = []
    compressor = _compressor_with(_FailingSummaryLlm())
    config = _feature_config(threshold=3)

    for round_index in range(3):
        _run_compression(
            compressor=compressor,
            config=config,
            trigger_source="auto",
            session_id="s-trip",
            events=events,
        )
    assert llm_summary_breaker.is_open("s-trip") is True
    assert _event_codes(events).count(
        "agent.context_compression.llm_summary_breaker_tripped"
    ) == 1

    # Next automatic compression under token pressure: explicitly degraded.
    events.clear()
    ui = _FakeUi()
    compressed, should_break, applied, count, last_iter = _run_compression(
        compressor=compressor,
        config=config,
        trigger_source="auto",
        session_id="s-trip",
        events=events,
        ui=ui,
    )[0]

    codes = _event_codes(events)
    assert "agent.context_compression.llm_summary_degraded" in codes
    degraded = next(
        e for e in events
        if e["args"][1] == "agent.context_compression.llm_summary_degraded"
    )
    fields = degraded["kwargs"]["fields"]
    assert fields["guardReason"] == llm_summary_breaker.BREAKER_GUARD_REASON
    assert fields["consecutiveFailures"] == 3
    assert fields["fallbackType"] == "rule_based_breaker_open"
    assert degraded["kwargs"]["outcome"] == "degraded"

    # The failing LLM was not attempted again: count stays at 3 and the
    # compressor received use_llm_summary=False.
    assert llm_summary_breaker.consecutive_failures("s-trip") == 3
    assert applied is True  # rule summary still relieved the pressure
    assert "agent.context_compression.llm_summary_fallback" not in codes

    ui_warns = [msg for level, msg in ui.logs if level == "WARN"]
    assert any("连败熔断" in msg for msg in ui_warns)


def test_manual_compression_not_intercepted_while_breaker_open():
    events: list[dict] = []
    config = _feature_config(threshold=3)
    failing = _compressor_with(_FailingSummaryLlm())

    for _ in range(3):
        _run_compression(
            compressor=failing,
            config=config,
            trigger_source="auto",
            session_id="s-manual",
            events=events,
        )
    assert llm_summary_breaker.is_open("s-manual") is True

    # Manual/explicit compression must still attempt the LLM summary.
    events.clear()
    _run_compression(
        compressor=failing,
        config=config,
        trigger_source="manual",
        session_id="s-manual",
        events=events,
    )

    codes = _event_codes(events)
    assert "agent.context_compression.llm_summary_degraded" not in codes
    assert "agent.context_compression.llm_summary_fallback" in codes
    assert llm_summary_breaker.consecutive_failures("s-manual") == 4


def test_success_releases_breaker_and_auto_compression_resumes_llm():
    events: list[dict] = []
    config = _feature_config(threshold=3)
    failing = _compressor_with(_FailingSummaryLlm())

    for _ in range(3):
        _run_compression(
            compressor=failing,
            config=config,
            trigger_source="auto",
            session_id="s-release",
            events=events,
        )
    assert llm_summary_breaker.is_open("s-release") is True

    # A manual compression with a healthy LLM succeeds and releases the breaker.
    events.clear()
    healthy = _compressor_with(_SucceedingSummaryLlm())
    _run_compression(
        compressor=healthy,
        config=config,
        trigger_source="manual",
        session_id="s-release",
        events=events,
    )
    codes = _event_codes(events)
    assert "agent.context_compression.llm_summary_breaker_released" in codes
    assert llm_summary_breaker.is_open("s-release") is False
    assert llm_summary_breaker.consecutive_failures("s-release") == 0

    # The next automatic compression attempts the LLM again (not degraded).
    events.clear()
    _run_compression(
        compressor=healthy,
        config=config,
        trigger_source="auto",
        session_id="s-release",
        events=events,
    )
    assert "agent.context_compression.llm_summary_degraded" not in _event_codes(events)
    assert llm_summary_breaker.consecutive_failures("s-release") == 0


def test_threshold_zero_disables_pause_but_keeps_fallback_events():
    events: list[dict] = []
    compressor = _compressor_with(_FailingSummaryLlm())
    config = _feature_config(threshold=0)

    for _ in range(5):
        _run_compression(
            compressor=compressor,
            config=config,
            trigger_source="auto",
            session_id="s-disabled",
            events=events,
        )

    assert llm_summary_breaker.is_open("s-disabled") is False
    codes = _event_codes(events)
    assert "agent.context_compression.llm_summary_breaker_tripped" not in codes
    assert "agent.context_compression.llm_summary_degraded" not in codes
    # Every failed attempt stayed audible.
    assert codes.count("agent.context_compression.llm_summary_fallback") == 5
    assert llm_summary_breaker.consecutive_failures("s-disabled") == 5
