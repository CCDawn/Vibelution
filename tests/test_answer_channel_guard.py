# -*- coding: utf-8 -*-
"""Answer-channel internal-format leak guard: gold-sample, anti-sample,
threshold, recovery, degraded-retry and release-with-markers tests.

Gold samples mirror the 2026-09-16 deepseek-v4.1-flash incidents:
- Case A: ``<tool calls>`` + ``<parameter name=...>`` with DSML-mangled
  closers (``</｜DSML｜ invoke>``) leaked as answer text.
- Case B: complete ``<analysis>``复盘 plus output-budget-truncated
  ``<summary>`` (~8k chars) leaked as the whole answer, zero user-facing text.
"""

from __future__ import annotations

import pytest

from core.llm.answer_channel_guard import (
    ANSWER_CHANNEL_LEAK_CATEGORY,
    build_answer_channel_guard,
    detect_answer_channel_leak,
    recover_answer_channel_leak,
    reset_answer_channel_leak_state,
)
from core.llm.errors import LLMError
from core.llm.reasoning_extractor import (
    extract_analysis_envelope_reasoning,
    strip_analysis_envelopes,
)
from core.llm.recovery import (
    DEGRADED_RETRY_ACTIONS,
    degraded_retry_overrides,
    plan_recovery,
)
from core.llm.types import CanonicalItemIdentity, TurnOutcome


def _identity(
    *,
    session_id: str = "session-leak",
    turn_id: str = "turn-leak",
    invocation_id: str = "invocation-leak",
) -> CanonicalItemIdentity:
    return CanonicalItemIdentity(
        session_id=session_id,
        turn_id=turn_id,
        invocation_id=invocation_id,
        iteration=0,
        item_id="answer-test",
    )


CASE_A_LEAK = (
    "<tool calls>\n"
    '<parameter name="cli_tool">git show 9ae85ebc7316d93a5f3262b40b6c20a2d94e96e'
    " -- core/web/services/session/directory_bridge.py</parameter>\n"
    "</invoke>\n"
    "</｜DSML｜ parameter>\n"
    "</｜DSML｜ invoke>\n"
    "</｜DSML｜ calls>"
)

_CASE_B_BODY = (
    "让我按时间顺序分析这次对话。\n\n"
    '**消息 1（用户）：** "你好" — 简单问候。我回复了问候并说明我能做什么。\n\n'
    '**消息 2（用户）：** "你能用什么工具" — 询问可用工具。我列出了工具类别。\n\n'
    "**我的调查（助手工具调用）：**\n"
    "1. 对 .ts 文件执行 grep_search_tool，搜索 contextWindow — 找到 40 个匹配。\n"
    "2. 对 .py 文件执行 grep_search_tool，搜索 300000 — 找到 5 个文件。\n"
    "关键发现：agent.py 第 809-830 行读取 context_window 并计算有效上限。\n"
)
CASE_B_LEAK = (
    "<analysis>\n"
    + _CASE_B_BODY
    + "</analysis>\n\n<summary>\n## 九节式总结\n"
    + "上下文窗口为 1M 而非配置 300k 的原因：provider 默认值覆盖了本地配置。"
    "需要检查 agentEffectiveConfigurationPresentation.ts 与 ConfigRoute.tsx 的展示逻辑，"
    "确认 1M 值是硬编码还是来自 provider 默认值。"
    "同时检查 agent.py 第 809-830 行的 context_window 读取逻辑，"
    "确认运行时是否优先读取 provider 上报的窗口大小而忽略 config.toml 的 300k 设置，"
    "然后向用户解释差异来源并给出收紧配置的建议。\n"
)


@pytest.fixture(autouse=True)
def _reset_guard_state():
    reset_answer_channel_leak_state()
    yield
    reset_answer_channel_leak_state()


# ---------------------------------------------------------------------------
# Gold samples
# ---------------------------------------------------------------------------


def test_gold_case_a_tool_call_leak_is_detected():
    finding = detect_answer_channel_leak(CASE_A_LEAK)
    assert finding is not None
    assert set(finding.marker_names) >= {"tool_calls_tag", "parameter_tag", "dsml_marker"}
    assert "front_position" in finding.triggered_by


def test_gold_case_a_unrecoverable_fragment_escalates_to_retry():
    outcome = TurnOutcome.final_answer(identity=_identity(), text=CASE_A_LEAK)
    finding = detect_answer_channel_leak(outcome.final_text)
    # Conservative: no <invoke name= structure start, so no tool-call is
    # hallucinated and no user text survives — recovery must fail.
    assert recover_answer_channel_leak(outcome, finding) is None


def test_gold_case_b_truncated_analysis_leak_detection_and_release():
    outcome = TurnOutcome.final_answer(identity=_identity(), text=CASE_B_LEAK)
    finding = detect_answer_channel_leak(outcome.final_text)
    assert finding is not None
    assert {"analysis_tag", "summary_tag"} <= set(finding.marker_names)
    # Recovery strips both envelopes; residual is empty (pure leak) so the
    # guard escalates to the degraded retry instead of releasing.
    assert recover_answer_channel_leak(outcome, finding) is None


def test_gold_case_b_complete_envelope_recovers_reasoning_when_answer_present():
    # Complete <analysis> envelope followed by the real answer: recovery
    # routes the复盘 to the reasoning channel and releases the answer.
    text = "<analysis>\n" + _CASE_B_BODY + "</analysis>\n\n这是给你的正式回答：上下文窗口是 1M。"
    outcome = TurnOutcome.final_answer(identity=_identity(), text=text)
    finding = detect_answer_channel_leak(outcome.final_text)
    recovered = recover_answer_channel_leak(outcome, finding)
    assert recovered is not None and recovered.kind == "final_answer"
    assert recovered.final_text.startswith("这是给你的正式回答")
    assert "<analysis>" not in recovered.final_text
    reasoning_events = [e for e in recovered.events if e.kind == "reasoning_delta"]
    assert reasoning_events and "按时间顺序分析" in reasoning_events[0].text
    assert recovered.metadata["leakRecovered"] is True


def test_gold_case_b_unclosed_long_envelope_swallows_residual_and_escalates():
    # Unclosed long <summary> (truncation form): everything after the open is
    # internal summary continuation, so residual is empty and the guard must
    # escalate to the degraded retry instead of releasing partial复盘.
    text = CASE_B_LEAK + "\n\n这是给你的正式回答：上下文窗口是 1M。"
    outcome = TurnOutcome.final_answer(identity=_identity(), text=text)
    finding = detect_answer_channel_leak(outcome.final_text)
    assert recover_answer_channel_leak(outcome, finding) is None


# ---------------------------------------------------------------------------
# Anti-samples (false-positive guards)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,text",
    [
        (
            "normal_markdown",
            "# 标题\n\n这是**加粗**正文，包含 [链接](http://x) 和列表：\n\n- 项目一\n- 项目二\n\n> 引用：模型有时会输出奇怪的标签。",
        ),
        (
            "fenced_xml_teaching",
            "把工具调用写成 XML：\n\n```xml\n<invoke name=\"read_file\">\n"
            "<parameter name=\"path\">a.py</parameter>\n</invoke>\n```\n\n以上是教学示例。",
        ),
        (
            "unclosed_fenced_xml",
            "下面是示例代码：\n\n```\n<tool calls>\n"
            '<parameter name="cli_tool">git status</parameter>\n\n注意其中 parameter 标签的写法。',
        ),
        (
            "tilde_fenced_xml",
            "~~~\n<tool calls>\n<parameter name=\"x\">y</parameter>\n~~~\n\n正文继续。",
        ),
        (
            "inline_code_discussion",
            "模型把内部格式 `<analysis>` 和 `<summary>` 泄漏为答复，需要把这类标签剥掉。",
        ),
        (
            "plain_word_summary",
            "## 总结\n\n上下文窗口为 1M，因为 provider 默认覆盖了本地配置的 300k。",
        ),
    ],
)
def test_anti_samples_do_not_trigger(label: str, text: str):
    assert detect_answer_channel_leak(text) is None, label


# ---------------------------------------------------------------------------
# Threshold boundaries
# ---------------------------------------------------------------------------


def test_threshold_single_marker_past_front_below_count_is_ignored():
    body = "正常正文。" * 120  # ~480 chars, marker far past the front 20%
    text = body + body + "<analysis>"
    assert detect_answer_channel_leak(text) is None


def test_threshold_marker_inside_front_20pct_triggers():
    head = "正常正文。" * 4
    text = head + "<analysis>" + ("更多正文。" * 100)
    finding = detect_answer_channel_leak(text)
    assert finding is not None
    assert "front_position" in finding.triggered_by


def test_threshold_two_markers_past_front_trigger_on_count():
    body = "正常正文。" * 120
    text = body + "<analysis>" + body + "<summary>"
    finding = detect_answer_channel_leak(text)
    assert finding is not None
    assert "marker_count" in finding.triggered_by


def test_threshold_short_pure_leak_single_marker_triggers():
    text = '<tool calls>\n<parameter name="x">y</parameter>'
    finding = detect_answer_channel_leak(text)
    assert finding is not None
    assert "short_pure_leak" in finding.triggered_by


def test_threshold_short_text_with_real_answer_single_marker_ignored():
    # Short but with substantial residual answer beyond the leak fragment:
    # fence-protected tag plus a real sentence does not escalate.
    text = "把 `<invoke>` 写进代码块即可：\n\n```\n<invoke name=\"x\"></invoke>\n```\n完成。"
    assert detect_answer_channel_leak(text) is None


def test_threshold_terminal_incomplete_tightens_to_any_marker():
    body = "正常正文。" * 120
    text = body + "<analysis>"
    assert detect_answer_channel_leak(text, terminal_incomplete=True) is not None


def test_fence_awareness_covers_unclosed_fence_to_eof():
    text = "教学示例：\n\n```\n<analysis>泄漏教学</analysis>\n<summary>也在代码里</summary>\n"
    assert detect_answer_channel_leak(text) is None


# ---------------------------------------------------------------------------
# Stage 1 recovery details
# ---------------------------------------------------------------------------


def test_recovery_prefers_structured_reasoning_field():
    text = "<analysis>\n" + ("复盘。" * 50) + "\n</analysis>\n\n正式回答。"
    outcome = TurnOutcome.final_answer(
        identity=_identity(),
        text=text,
        events=(),
    )
    # Simulate provider-delivered reasoning by injecting a reasoning event.
    from core.llm.types import LLMProtocolEvent

    event = LLMProtocolEvent(
        kind="reasoning_delta",
        sequence=0,
        session_id=_identity().session_id,
        invocation_id=_identity().invocation_id,
        iteration=0,
        text="provider 思考内容",
    )
    outcome = TurnOutcome(
        kind="final_answer",
        identity=_identity(),
        events=(event,),
        final_text=text,
        terminal_event_seen=True,
    )
    finding = detect_answer_channel_leak(outcome.final_text)
    recovered = recover_answer_channel_leak(outcome, finding)
    assert recovered is not None
    # Envelope still stripped from the answer, but no duplicate reasoning
    # event is carved out of the body (structured field wins).
    assert "复盘" not in recovered.final_text
    reasoning_events = [e for e in recovered.events if e.kind == "reasoning_delta"]
    assert len(reasoning_events) == 1 and reasoning_events[0].text == "provider 思考内容"


def test_recovery_conservative_on_bare_unclosed_mid_text_tag():
    # A mid-text unclosed tag with a short body is prose, not an envelope:
    # recovery must not mangle the answer even when detection fires on count.
    text = "模型输出了 <analysis> 和 <summary> 标签说明内部格式泄漏了，需要剥离。"
    outcome = TurnOutcome.final_answer(identity=_identity(), text=text)
    finding = detect_answer_channel_leak(outcome.final_text)
    recovered = recover_answer_channel_leak(outcome, finding) if finding else outcome
    if recovered is not None:
        assert recovered.final_text == text or "模型输出了" in recovered.final_text


def test_recovery_converts_wellformed_tool_fragment():
    text = (
        "前面的说明。\n\n<tool calls>\n<invoke name=\"read_file_tool\">\n"
        "<parameter name=\"path\">a.py</parameter>\n</invoke>\n</tool calls>"
    )
    outcome = TurnOutcome.final_answer(identity=_identity(), text=text)
    finding = detect_answer_channel_leak(outcome.final_text)
    assert finding is not None
    recovered = recover_answer_channel_leak(outcome, finding)
    assert recovered is not None and recovered.kind == "tool_calls"
    assert recovered.tool_calls[0].name == "read_file_tool"
    assert recovered.tool_calls[0].arguments == {"path": "a.py"}


# ---------------------------------------------------------------------------
# reasoning_extractor analysis-envelope preconditions
# ---------------------------------------------------------------------------


def test_analysis_extractor_complete_envelope():
    text = "<analysis>\n" + ("复盘。" * 50) + "\n</analysis>\n\n回答。"
    extraction = extract_analysis_envelope_reasoning(text)
    assert extraction.source == "analysis_envelope" and "复盘" in extraction.text
    cleaned = strip_analysis_envelopes(text)
    assert "<analysis>" not in cleaned and "回答。" in cleaned


def test_analysis_extractor_unclosed_requires_front_and_long_body():
    long_body = "复盘内容。" * 100
    # Front position + long body: recovered.
    text = "<summary>\n" + long_body
    assert "复盘内容" in extract_analysis_envelope_reasoning(text).text
    # Mid-text unclosed short tag: treated as prose.
    prose = "正常开头。" * 100 + "<summary> 简短讨论 "
    assert extract_analysis_envelope_reasoning(prose).text == ""
    # Front position but short body: also prose (conservative).
    assert extract_analysis_envelope_reasoning("<summary>短").text == ""


# ---------------------------------------------------------------------------
# Stage 2/3: composed guard — retry then release with markers
# ---------------------------------------------------------------------------


def test_guard_raises_once_then_releases_with_markers():
    events: list[tuple] = []
    guarded = build_answer_channel_guard(
        lambda outcome: outcome,
        record_event=lambda *args, **kwargs: events.append((args, kwargs)),
        resolve_route=lambda: ("https://gateway.example", "deepseek-v4.1-flash"),
    )
    outcome = TurnOutcome.final_answer(identity=_identity(), text=CASE_B_LEAK)
    with pytest.raises(LLMError) as exc_info:
        guarded(outcome)
    assert exc_info.value.category == ANSWER_CHANNEL_LEAK_CATEGORY
    assert exc_info.value.retryable is True
    assert "analysis_tag" in exc_info.value.details["leakMarkers"]

    # Retry attempt (new invocation id, same session/turn): still leaking ->
    # release unchanged with leak metadata, scene events recorded.
    retry_outcome = TurnOutcome.final_answer(
        identity=_identity(invocation_id="invocation-retry"),
        text=CASE_B_LEAK,
    )
    released = guarded(retry_outcome)
    assert released.kind == "final_answer"
    assert released.final_text == CASE_B_LEAK
    assert released.metadata["leakRetried"] is True
    assert released.metadata["leakRecovered"] is False
    assert set(released.metadata["leakMarkers"]) >= {"analysis_tag", "summary_tag"}
    assert events, "answer_channel_leak_detected scene events must be recorded"
    from core.llm.answer_channel_guard import answer_channel_leak_route_counts

    counts = answer_channel_leak_route_counts()
    assert counts[("https://gateway.example", "deepseek-v4.1-flash")] == 1


def test_guard_clean_retry_attempt_reports_retried_telemetry():
    events: list[tuple] = []
    guarded = build_answer_channel_guard(
        lambda outcome: outcome,
        record_event=lambda *args, **kwargs: events.append((args, kwargs)),
        resolve_route=lambda: ("gw", "m"),
    )
    outcome = TurnOutcome.final_answer(identity=_identity(), text=CASE_B_LEAK)
    with pytest.raises(LLMError):
        guarded(outcome)
    clean_retry = TurnOutcome.final_answer(
        identity=_identity(invocation_id="invocation-retry"),
        text="这次是干净的回答。",
    )
    released = guarded(clean_retry)
    assert released.final_text == "这次是干净的回答。"
    assert released.metadata["leakRetried"] is True
    assert released.metadata["leakRecovered"] is True
    assert list(released.metadata["leakMarkers"]) == []


def test_guard_recovers_mixed_answer_without_retry():
    events: list[tuple] = []
    guarded = build_answer_channel_guard(
        lambda outcome: outcome,
        record_event=lambda *args, **kwargs: events.append((args, kwargs)),
        resolve_route=lambda: ("gw", "m"),
    )
    text = "<analysis>\n" + ("复盘。" * 60) + "\n</analysis>\n\n正式回答。"
    outcome = TurnOutcome.final_answer(identity=_identity(), text=text)
    released = guarded(outcome)
    assert released.kind == "final_answer"
    assert released.final_text == "正式回答。"
    assert released.metadata["leakRetried"] is False


def test_guard_ignores_clean_outcomes_and_tool_calls():
    guarded = build_answer_channel_guard(lambda outcome: outcome)
    outcome = TurnOutcome.final_answer(identity=_identity(), text="普通回答。")
    assert guarded(outcome).final_text == "普通回答。"
    tool_outcome = TurnOutcome(
        kind="tool_calls",
        identity=_identity(),
        final_text="<tool calls>",
        terminal_event_seen=True,
    )
    assert guarded(tool_outcome) is tool_outcome


def test_guard_recovery_does_not_escalate_twice_for_same_turn():
    guarded = build_answer_channel_guard(lambda outcome: outcome)
    # A recovered (non-empty residual) leak never raises, so a fresh leak on
    # the next iteration of the same turn still gets its own recovery pass.
    leak_text = "<analysis>\n" + ("复盘。" * 60) + "\n</analysis>\n\n第一次回答。"
    first = guarded(
        TurnOutcome.final_answer(identity=_identity(), text=leak_text)
    )
    assert first.final_text == "第一次回答。"
    second = guarded(
        TurnOutcome.final_answer(
            identity=_identity(invocation_id="invocation-2"),
            text=leak_text.replace("第一次", "第二次"),
        )
    )
    assert second.final_text == "第二次回答。"


# ---------------------------------------------------------------------------
# Recovery policy wiring
# ---------------------------------------------------------------------------


def test_answer_channel_leak_maps_to_retry_answer_without_tools():
    error = LLMError(ANSWER_CHANNEL_LEAK_CATEGORY, "leak", retryable=True)
    decision = plan_recovery(error, attempt=1, max_attempts=5)
    assert decision.category == ANSWER_CHANNEL_LEAK_CATEGORY
    assert decision.action == "retry_answer_without_tools"
    assert decision.action in DEGRADED_RETRY_ACTIONS
    assert degraded_retry_overrides(decision.action) == (True, True)
    assert decision.retryable is True
    assert decision.stop_current_turn is False


# ---------------------------------------------------------------------------
# Adapter integration: guard exception flows into the degraded retry path
# ---------------------------------------------------------------------------


def _adapter_hooks(invoke_outcome, *, record_scene_event, plan_recovery_hook=None, stop_error_cls=None):
    from types import SimpleNamespace

    from core.orchestration.turn_llm_adapter import AgentLlmTurnHooks

    class DummyLLM:
        profile_id = "primary"

        def effective_route_identity(self):
            return ("primary",)

        def effective_route_id(self):
            return "primary-route"

        def project_outcome_message(self, outcome):
            from langchain_core.messages import AIMessage

            return AIMessage(content=outcome.final_text)

    class _DummyContext:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _DummyUI:
        def thinking(self, _label):
            return _DummyContext()

        def add_log(self, *_args, **_kwargs):
            return None

    return AgentLlmTurnHooks(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **_kwargs: DummyLLM(),
        should_stream=lambda *_args, **_kwargs: False,
        build_invocation_context=lambda **_kwargs: SimpleNamespace(
            to_metadata=lambda client=None: {"invocationId": "inv-1"}
        ),
        invoke_outcome=invoke_outcome,
        run_streaming_outcome=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-stream path must not stream")
        ),
        canonicalize=build_answer_channel_guard(
            lambda outcome: outcome,
            record_event=record_scene_event,
            resolve_route=lambda: ("gw", "m"),
        ),
        plan_recovery=plan_recovery_hook or plan_recovery,
        record_scene_event=record_scene_event,
        record_route_success=lambda **_kwargs: None,
        request_compression=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("leak path must not compress")
        ),
        debug_logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        error_logger=SimpleNamespace(log_error=lambda *_args, **_kwargs: None),
        config=SimpleNamespace(
            llm=SimpleNamespace(model_name="m", provider="relay", api_base="", api_timeout=30)
        ),
        force_disable_tools=False,
        stop_error_cls=stop_error_cls or type("_NoopStop", (Exception,), {}),
    )


def test_adapter_degraded_retry_after_leak_recovers_turn():
    from langchain_core.messages import AIMessage

    from core.orchestration.turn_llm_adapter import invoke_agent_llm_turn

    class TurnStopRequested(Exception):
        pass

    calls = {"n": 0}
    leaked = TurnOutcome.final_answer(identity=_identity(), text=CASE_B_LEAK)

    def invoke_outcome(_client, _messages, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return leaked
        return TurnOutcome.final_answer(
            identity=_identity(invocation_id="inv-retry"),
            text="重试后的干净回答。",
        )

    scene_events: list[tuple] = []
    hooks = _adapter_hooks(
        invoke_outcome,
        record_scene_event=lambda *args, **kwargs: scene_events.append((args, kwargs)),
        stop_error_cls=TurnStopRequested,
    )
    result = invoke_agent_llm_turn(messages=[AIMessage(content="hi")], hooks=hooks)
    assert calls["n"] == 2, "guard must trigger exactly one degraded retry"
    assert result.degraded_actions == ["retry_answer_without_tools"]
    outcome, message = result.payload
    assert outcome.final_text == "重试后的干净回答。"
    assert message.content == "重试后的干净回答。"
    detected = [
        kwargs for _args, kwargs in scene_events
        if (kwargs.get("event_code") if "event_code" in kwargs else _args[1] if len(_args) > 1 else "")
        == "answer_channel_leak_detected"
    ]
    assert detected, "leak detection scene event must be recorded"


def test_adapter_second_leak_releases_with_markers_and_scene_event():
    from langchain_core.messages import AIMessage

    from core.orchestration.turn_llm_adapter import invoke_agent_llm_turn

    class TurnStopRequested(Exception):
        pass

    calls = {"n": 0}

    def invoke_outcome(_client, _messages, **_kwargs):
        calls["n"] += 1
        invocation = "inv-1" if calls["n"] == 1 else "inv-retry"
        return TurnOutcome.final_answer(
            identity=_identity(invocation_id=invocation),
            text=CASE_B_LEAK,
        )

    scene_events: list[tuple] = []
    hooks = _adapter_hooks(
        invoke_outcome,
        record_scene_event=lambda *args, **kwargs: scene_events.append((args, kwargs)),
        stop_error_cls=TurnStopRequested,
    )
    result = invoke_agent_llm_turn(messages=[AIMessage(content="hi")], hooks=hooks)
    assert calls["n"] == 2, "release path must not retry a third time"
    outcome, message = result.payload
    assert outcome.kind == "final_answer"
    assert outcome.metadata["leakRetried"] is True
    assert outcome.metadata["leakRecovered"] is False
    assert message.content == CASE_B_LEAK
    detected = [
        (args, kwargs)
        for args, kwargs in scene_events
        if len(args) > 1 and args[1] == "answer_channel_leak_detected"
    ]
    assert len(detected) >= 2, "both leak detections must emit scene events"
