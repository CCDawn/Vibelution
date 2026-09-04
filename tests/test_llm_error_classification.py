# -*- coding: utf-8 -*-
"""集中 LLM 错误分类器（core/llm/error_classification.py）的表驱动与 parity 测试。

锁定三件事：

1. 每类异常样例 → (category, disposition) 的映射表；未知错误 fail-closed。
2. review runners 三个错误函数改造前后的行为 parity（样例输入 → 硬编码
   期望值，与改造前实现逐一对齐）。
3. Challenge receipt 失败的新异常类型及其 RuntimeError 兼容 catch。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.llm.client import _llm_retry_event_fields
from core.llm.error_classification import (
    BUDGET_OR_CONTEXT,
    PERMANENT,
    TRANSIENT_RETRYABLE,
    classify_error,
)
from core.llm.errors import classify_exception
from core.llm.types import (
    LLMError,
    LLMOutputTruncatedError,
    LLMRouteGateTimeoutError,
)
from core.research.workflow.contracts import ContractValidationError

# ---------------------------------------------------------------------------
# 表驱动：异常样例 → (category, disposition)
# ---------------------------------------------------------------------------

_CLASSIFICATION_TABLE = [
    # --- 传输族：连接重置 / 读超时 / 5xx / 429 → transient_retryable ------
    ("connection reset by peer", "network_error", TRANSIENT_RETRYABLE),
    ("Connection aborted by host", "network_error", TRANSIENT_RETRYABLE),
    ("peer closed connection without eof", "network_error", TRANSIENT_RETRYABLE),
    ("httpx.ReadTimeout: read timed out", "timeout", TRANSIENT_RETRYABLE),
    ("429 too many requests", "rate_limit", TRANSIENT_RETRYABLE),
    ("rate limit exceeded, retry later", "rate_limit", TRANSIENT_RETRYABLE),
    ("HTTP 500 internal failure", "server_error", TRANSIENT_RETRYABLE),
    ("502 bad gateway", "server_error", TRANSIENT_RETRYABLE),
    ("503 service unavailable", "server_error", TRANSIENT_RETRYABLE),
    ("litellm.InternalServerError: upstream failed", "server_error", TRANSIENT_RETRYABLE),
    # --- 预算/上下文族 → budget_or_context --------------------------------
    ("maximum context length exceeded", "context_length_error", BUDGET_OR_CONTEXT),
    ("insufficient_quota: billing limit reached", "quota_error", BUDGET_OR_CONTEXT),
    # --- 永久族：鉴权 / schema 拒绝 / capability / 配置 --------------------
    ("401 unauthorized", "auth_error", PERMANENT),
    ("invalid params, duplicate tool_call id: call_1", "tool_protocol_error", PERMANENT),
    ("chat content is empty", "empty_content_error", PERMANENT),
    ("bad request: 400", "provider_protocol_error", PERMANENT),
    ("profile `primary` 不支持 tool support", "capability_error", PERMANENT),
    ("missing profile for role", "configuration_error", PERMANENT),
    # --- 未知错误 fail-closed：保持不可重试，绝不放宽 ----------------------
    ("something completely unknown happened", "provider_protocol_error", PERMANENT),
]

_NON_LLM_CASES = [
    (Exception(message), category, disposition)
    for message, category, disposition in _CLASSIFICATION_TABLE
]


@pytest.mark.parametrize(
    ("message", "expected_category", "expected_disposition"),
    _NON_LLM_CASES,
    ids=[case[0][:32] for case in _CLASSIFICATION_TABLE],
)
def test_classification_table_bare_exceptions(message, expected_category, expected_disposition):
    classification = classify_error(Exception(message))

    assert classification.category == expected_category
    assert classification.disposition == expected_disposition


@pytest.mark.parametrize(
    ("exc", "expected_category", "expected_disposition"),
    [
        # provider 后端透传的 LLMError：完全尊重 retryable 标志。
        (
            LLMError("rate_limit_error", "Anthropic HTTP 429", retryable=True),
            "rate_limit_error",
            TRANSIENT_RETRYABLE,
        ),
        (
            LLMError("provider_error", "Anthropic HTTP 502", retryable=True),
            "provider_error",
            TRANSIENT_RETRYABLE,
        ),
        (
            LLMError("authentication_error", "Anthropic HTTP 401", retryable=False),
            "authentication_error",
            PERMANENT,
        ),
        (
            LLMError("invalid_request_error", "Anthropic HTTP 400", retryable=False),
            "invalid_request_error",
            PERMANENT,
        ),
        (LLMRouteGateTimeoutError(wait_seconds=2.0), "gate_timeout", TRANSIENT_RETRYABLE),
        (LLMOutputTruncatedError(), "output_truncated", BUDGET_OR_CONTEXT),
        (KeyboardInterrupt(), "user_interrupt", PERMANENT),
    ],
    ids=[
        "anthropic-429",
        "anthropic-502",
        "anthropic-401",
        "anthropic-400",
        "route-gate-timeout",
        "output-truncated",
        "user-interrupt",
    ],
)
def test_classification_table_llm_error_passthrough(exc, expected_category, expected_disposition):
    classification = classify_error(exc)

    assert classification.category == expected_category
    assert classification.disposition == expected_disposition
    # LLMError 输入零拷贝透传：调用方可继续用同一对象 raise；
    # 非 LLMError（如 KeyboardInterrupt）走归一化新建。
    if isinstance(exc, LLMError):
        assert classification.error is exc


def test_unknown_error_is_fail_closed_and_never_retryable():
    classification = classify_error(Exception("totally novel provider glitch"))

    assert classification.disposition == PERMANENT
    assert classification.retryable is False
    assert not classification.is_transient_retryable


def test_http_408_bare_exception_is_request_timeout_retryable():
    # classify_exception 的关键词表没有 408（会误归 provider_protocol_error）；
    # 集中分类器的显式规则层把它提升为 timeout 同族可重试。
    bare = classify_exception(Exception("HTTP 408"))
    assert bare.category == "provider_protocol_error"
    assert bare.retryable is False

    classification = classify_error(Exception("HTTP 408"))
    assert classification.category == "timeout"
    assert classification.disposition == TRANSIENT_RETRYABLE


def test_http_408_rule_ignores_digit_substrings():
    # "4080" 里的 408 不是独立 token，不得误命中。
    classification = classify_error(Exception("error code 4080 while streaming"))
    assert classification.disposition == PERMANENT


def test_http_408_rule_never_touches_llm_error_passthrough():
    # provider 后端透传的 LLMError 保持 retryable 判定平价，408 规则不生效。
    exc = LLMError("provider_protocol_error", "HTTP 408 from gateway", retryable=False)
    classification = classify_error(exc)
    assert classification.disposition == PERMANENT


# ---------------------------------------------------------------------------
# HTTP 429 显式规则（408 先例）：数字边界收紧 + litellm 类型证据补漏
# ---------------------------------------------------------------------------


def test_http_429_digit_substring_is_demoted_fail_closed():
    # 关键词表用子串判定，"1429" 会被误报成 rate_limit；显式规则要求 429
    # 是独立 token，纯子串命中降级回 provider_protocol_error fail-closed。
    bare = classify_exception(Exception("HTTP 1429 trace-id=1"))
    assert bare.category == "rate_limit"
    assert bare.retryable is True

    classification = classify_error(Exception("HTTP 1429 trace-id=1"))
    assert classification.category == "provider_protocol_error"
    assert classification.disposition == PERMANENT
    assert classification.retryable is False


def test_http_429_independent_token_and_phrase_stay_rate_limit():
    # 独立 token 与 "rate limit" 短语是合法证据，不受收紧影响。
    for message in (
        "HTTP 429 too many requests",
        "rate limit exceeded, retry later",
        "litellm.RateLimitError: Rate limit error: 429 Too Many Requests",
    ):
        classification = classify_error(Exception(message))
        assert classification.category == "rate_limit", message
        assert classification.disposition == TRANSIENT_RETRYABLE, message


def test_litellm_rate_limit_error_type_is_promoted_to_rate_limit():
    # litellm.RateLimitError 消息缺 "429"/"rate limit" 关键词时，关键词表会
    # 误归不可重试的 provider_protocol_error；类型证据补漏提升为
    # rate_limit 同族可重试（生产通道走 litellm）。
    pytest.importorskip("litellm")
    from litellm import RateLimitError as LiteLLMRateLimitError

    bare = classify_exception(
        LiteLLMRateLimitError(
            message="Too many requests, please retry later",
            model="review-model",
            llm_provider="openai",
        )
    )
    assert bare.category == "provider_protocol_error"
    assert bare.retryable is False

    classification = classify_error(
        LiteLLMRateLimitError(
            message="Too many requests, please retry later",
            model="review-model",
            llm_provider="openai",
        )
    )
    assert classification.category == "rate_limit"
    assert classification.disposition == TRANSIENT_RETRYABLE
    assert classification.retryable is True
    assert classification.error.details.get("httpStatus") == 429

    # 带关键词消息的 litellm 429 走关键词路径，同样落在 rate_limit。
    keyworded = classify_error(
        LiteLLMRateLimitError(
            message="Rate limit error: 429 Too Many Requests",
            model="review-model",
            llm_provider="openai",
        )
    )
    assert keyworded.category == "rate_limit"
    assert keyworded.disposition == TRANSIENT_RETRYABLE


def test_http_429_rules_never_touch_llm_error_passthrough():
    # provider 后端透传的 LLMError 保持 retryable/category 平价：429 收紧与
    # 类型提升都只作用于裸异常路径。
    passthrough = LLMError("rate_limit", "HTTP 1429 from gateway", retryable=True)
    classification = classify_error(passthrough)
    assert classification.category == "rate_limit"
    assert classification.error is passthrough

    cooldown = LLMError("rate_limit_cooldown", "gate cooldown rejection", retryable=True)
    classification = classify_error(cooldown)
    assert classification.category == "rate_limit_cooldown"
    assert classification.error is cooldown


def test_disposition_stays_parity_with_legacy_retryable_flag():
    # 平价不变式（408 显式规则与 429 显式规则除外）：transient_retryable ⟺
    # 旧 retryable。
    samples = [Exception(case[0]) for case in _CLASSIFICATION_TABLE]
    samples.extend(
        [
            LLMError("rate_limit_error", "429", retryable=True),
            LLMError("authentication_error", "401", retryable=False),
            LLMRouteGateTimeoutError(wait_seconds=1.0),
            LLMOutputTruncatedError(),
        ]
    )
    for sample in samples:
        classification = classify_error(sample)
        legacy = classify_exception(sample)
        if legacy.retryable:
            assert classification.is_transient_retryable, sample
        else:
            assert not classification.is_transient_retryable, sample
        assert classification.retryable is legacy.retryable


# ---------------------------------------------------------------------------
# review runners 三函数 parity（改造前后的对外行为逐一对齐）
# ---------------------------------------------------------------------------


@pytest.fixture()
def review_runners_module():
    from core.web.services.team_workflow import llm_review_runners

    return llm_review_runners


def _review_error_samples(module):
    """(名称, 异常, 期望 category, 期望 is_recoverable) 样例集。"""

    return [
        (
            "review_timeout",
            module.ReviewLLMTimeoutError(purpose="pairwise", timeout_seconds=1.0),
            "timeout",
            False,
        ),
        (
            "gate_timeout",
            module.ReviewLLMGateTimeoutError(
                purpose="pairwise", model_ref="m-1", wait_seconds=1.0
            ),
            "llm_gate_rejected",
            True,
        ),
        (
            "rate_limit_cooldown",
            module.ReviewLLMRateLimitCooldownError(
                purpose="pairwise", model_ref="m-1", cooldown_remaining_seconds=1.0
            ),
            "llm_gate_rejected",
            True,
        ),
        ("contract_validation", ContractValidationError("bad json"), "contract_validation", False),
        ("llm_retryable", LLMError("rate_limit", "429", retryable=True), "provider_error", False),
        ("llm_permanent", LLMError("auth_error", "401", retryable=False), "provider_error", False),
        ("runtime_error", RuntimeError("boom"), "runtime_error", False),
        ("runtime_value_error", ValueError("bad value"), "runtime_error", False),
        (
            "runtime_transport_like",
            Exception("connection reset by peer"),
            "runtime_error",
            False,
        ),
    ]


def test_review_llm_error_category_parity(review_runners_module):
    for name, exc, expected, _ in _review_error_samples(review_runners_module):
        assert review_runners_module._review_llm_error_category(exc) == expected, name


def test_is_recoverable_review_llm_gate_error_parity(review_runners_module):
    for name, exc, _, expected in _review_error_samples(review_runners_module):
        assert (
            review_runners_module.is_recoverable_review_llm_gate_error(exc) is expected
        ), name


def test_maybe_record_provider_rate_limit_parity(review_runners_module, monkeypatch):
    # 判定范围锁定：provider 429 传输族（Anthropic native 透传的
    # ``rate_limit_error`` 与 litellm/关键词路径归一的 ``rate_limit``）打开
    # 模型 cooldown；gate 快速失败异常与其它传输错误绝不触发记录，风暴不
    # 延长窗口；纯子串 "1429" 不是 429，同样不触发。
    recorded: list[str] = []
    monkeypatch.setattr(
        review_runners_module, "_record_model_rate_limit", lambda ref: recorded.append(ref)
    )

    cases = [
        (LLMError("rate_limit_error", "Anthropic HTTP 429", retryable=True), True),
        (LLMError("rate_limit", "429 too many requests", retryable=True), True),
        (RuntimeError("HTTP 429 too many requests"), True),
        (
            review_runners_module.ReviewLLMRateLimitCooldownError(
                purpose="p", model_ref="m", cooldown_remaining_seconds=1.0
            ),
            False,
        ),
        (
            review_runners_module.ReviewLLMGateTimeoutError(
                purpose="p", model_ref="m", wait_seconds=1.0
            ),
            False,
        ),
        (LLMError("server_error", "502", retryable=True), False),
        (RuntimeError("HTTP 1429 trace-id=1"), False),
    ]
    for exc, should_record in cases:
        recorded.clear()
        review_runners_module._maybe_record_provider_rate_limit(exc, model_ref="m-1")
        assert bool(recorded) is should_record, exc


def test_review_error_disposition_view(review_runners_module):
    # 失败事件/dump 新增 disposition 视图：429 → transient，schema 拒绝 →
    # permanent，上下文超限 → budget_or_context。
    assert (
        review_runners_module._review_llm_error_disposition(
            LLMError("rate_limit", "429", retryable=True)
        )
        == TRANSIENT_RETRYABLE
    )
    assert (
        review_runners_module._review_llm_error_disposition(
            ContractValidationError("did not return valid JSON")
        )
        == PERMANENT
    )
    assert (
        review_runners_module._review_llm_error_disposition(
            LLMError("context_length_error", "too long", retryable=False)
        )
        == BUDGET_OR_CONTEXT
    )


# ---------------------------------------------------------------------------
# client 重试事件 fields 携带 disposition
# ---------------------------------------------------------------------------


def _retry_event_fields(llm_error: LLMError, disposition=None):
    return _llm_retry_event_fields(
        role="primary",
        profile_id="profile-1",
        provider="openai",
        model="gpt-test",
        message_count=2,
        tool_count=0,
        metadata=None,
        attempt=1,
        max_attempts=3,
        llm_error=llm_error,
        disposition=disposition,
    )


def test_retry_event_fields_carry_error_disposition():
    fields = _retry_event_fields(LLMError("rate_limit", "429", retryable=True))
    assert fields["errorDisposition"] == TRANSIENT_RETRYABLE

    fields = _retry_event_fields(LLMError("auth_error", "401", retryable=False))
    assert fields["errorDisposition"] == PERMANENT

    fields = _retry_event_fields(
        LLMError("context_length_error", "too long", retryable=False)
    )
    assert fields["errorDisposition"] == BUDGET_OR_CONTEXT


def test_retry_event_fields_disposition_falls_back_to_central_classifier():
    # 调用方未显式传 disposition 时（如 cancelled 分支），fields 构造器
    # 内部走集中分类器兜底。
    fields = _retry_event_fields(LLMError("server_error", "503", retryable=True), None)
    assert fields["errorDisposition"] == TRANSIENT_RETRYABLE


# ---------------------------------------------------------------------------
# Challenge receipt 失败：新异常类型 + RuntimeError 兼容
# ---------------------------------------------------------------------------


def _receipt_capture(failure_code: str):
    return SimpleNamespace(challenge_receipt_failure_code=failure_code)


def test_challenge_receipt_failure_error_type_and_fields():
    from core.web.services.session.worker import ChallengeReceiptFailureError

    exc = ChallengeReceiptFailureError("challenge_receipt_context_invalid")
    assert isinstance(exc, RuntimeError)
    assert exc.failure_code == "challenge_receipt_context_invalid"
    assert exc.category == "challenge_receipt_failure"
    assert exc.disposition == PERMANENT
    assert str(exc) == "challenge_receipt_context_invalid"


def test_raise_for_challenge_receipt_failure_raises_typed_error():
    from core.web.services.session.worker import (
        ChallengeReceiptFailureError,
        _raise_for_challenge_receipt_failure,
    )

    with pytest.raises(ChallengeReceiptFailureError) as exc_info:
        _raise_for_challenge_receipt_failure(
            _receipt_capture("challenge_receipt_durable_enqueue_failed")
        )
    assert exc_info.value.failure_code == "challenge_receipt_durable_enqueue_failed"
    assert exc_info.value.disposition == PERMANENT


def test_raise_for_challenge_receipt_failure_stays_runtime_error_compatible():
    # 既有 catch 方（except RuntimeError / pytest.raises(RuntimeError)）兼容。
    from core.web.services.session.worker import _raise_for_challenge_receipt_failure

    with pytest.raises(RuntimeError, match="challenge_model_invocation_receipt_missing"):
        _raise_for_challenge_receipt_failure(
            _receipt_capture("challenge_model_invocation_receipt_missing")
        )


def test_raise_for_challenge_receipt_failure_noop_without_code():
    from core.web.services.session.worker import _raise_for_challenge_receipt_failure

    _raise_for_challenge_receipt_failure(SimpleNamespace(challenge_receipt_failure_code=""))
    _raise_for_challenge_receipt_failure(SimpleNamespace(challenge_receipt_failure_code=None))
