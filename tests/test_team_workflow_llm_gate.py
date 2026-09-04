"""Global LLM concurrency gate (Challenge 10-way parallel review guard).

Covers the process-level ceiling added around the review LLM funnel:

* the gate caps simultaneously in-flight review LLM calls across threads
  (peak <= configured slots, every caller completes — no starvation), both
  at the gate primitive itself and through the real ``_invoke_review_llm``
  wiring with a slow fake provider call;
* an acquire timeout fails fast with a structured, recoverable gate error
  that classifies into the review failure taxonomy and requeues (meeting
  stays ``summarizing`` with a retryable summaryDraftError) instead of
  crashing or pinning the worker;
* a provider 429 opens a model-level cooldown: same-model calls fast-fail
  without sending a request, and the model recovers once the window
  expires;
* the slot is always released — exception paths never leak capacity, and
  repeated concurrent waves leave the semaphore at full availability.

No real model or network is involved.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.llm.types import LLMError
from core.web.services.team_workflow import llm_review_runners

_GATE_MAX_ENV = llm_review_runners._LLM_GATE_MAX_CONCURRENT_ENV
_GATE_WAIT_ENV = llm_review_runners._LLM_GATE_ACQUIRE_TIMEOUT_ENV
_COOLDOWN_ENV = llm_review_runners._LLM_RATE_LIMIT_COOLDOWN_ENV


@pytest.fixture(autouse=True)
def _isolate_llm_gate(monkeypatch):
    """Every test starts from a freshly sized gate and an empty cooldown."""

    monkeypatch.delenv(_GATE_MAX_ENV, raising=False)
    monkeypatch.delenv(_GATE_WAIT_ENV, raising=False)
    monkeypatch.delenv(_COOLDOWN_ENV, raising=False)
    llm_review_runners.reset_llm_gate_for_tests()
    yield
    llm_review_runners.reset_llm_gate_for_tests()


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content
        self.response_metadata = {}


def _pairwise_payload() -> str:
    return json.dumps({"outcome": "left_wins", "justification": "A 领先。"})


def _review_context() -> dict:
    return {
        "contextId": "ctx-gate",
        "teamId": "team-1",
        "question": "SCI-096",
    }


def _install_slow_pairwise_llm(monkeypatch, *, sleep_s: float = 0.05):
    """Patch ``invoke_llm`` with a slow successful pairwise response."""

    state = {"in_flight": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        with lock:
            state["calls"] += 1
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
        try:
            time.sleep(sleep_s)
            return _FakeResponse(_pairwise_payload())
        finally:
            with lock:
                state["in_flight"] -= 1

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    monkeypatch.setattr(
        llm_review_runners, "review_llm_call_timeout_seconds", lambda **_kw: 30.0
    )
    return state


def _run_pairwise_call(index: int) -> dict:
    runners = llm_review_runners.build_hypothesis_review_runners(
        {
            "client": object(),
            "profileId": "primary",
            "modelId": "fake-review-model",
            "modelRef": "fake-provider/fake-review-model",
        }
    )
    return runners["pairwise_runner"](
        {"candidateId": f"cand-{index}", "claim": f"假说 {index}"},
        {"candidateId": f"cand-{index}-b", "claim": f"对照 {index}"},
        _review_context(),
    )


# ---------------------------------------------------------------------------
# (a) the gate caps in-flight provider calls without starving anyone
# ---------------------------------------------------------------------------


def test_gate_primitive_caps_concurrent_slots_and_completes_all_callers(monkeypatch):
    monkeypatch.setenv(_GATE_MAX_ENV, "4")
    llm_review_runners.reset_llm_gate_for_tests()

    state = {"in_flight": 0, "peak": 0, "completed": 0}
    lock = threading.Lock()

    def worker():
        with llm_review_runners._llm_gate_slot(
            purpose="gate_probe", model_ref="fake-provider/fake-review-model"
        ):
            with lock:
                state["in_flight"] += 1
                state["peak"] = max(state["peak"], state["in_flight"])
            time.sleep(0.03)
            with lock:
                state["in_flight"] -= 1
                state["completed"] += 1

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(worker) for _ in range(12)]
        for future in futures:
            future.result(timeout=30)

    assert state["peak"] <= 4
    assert state["completed"] == 12


def test_review_llm_invocations_respect_the_global_gate(monkeypatch):
    """12 concurrent real-wiring calls against a 4-slot gate: peak <= 4."""

    monkeypatch.setenv(_GATE_MAX_ENV, "4")
    llm_review_runners.reset_llm_gate_for_tests()
    state = _install_slow_pairwise_llm(monkeypatch)

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(_run_pairwise_call, index) for index in range(12)]
        results = [future.result(timeout=30) for future in futures]

    assert state["calls"] == 12
    assert state["peak"] <= 4
    assert state["in_flight"] == 0
    assert all(result["outcome"] == "left_wins" for result in results)


def test_gate_env_override_is_clamped_and_defaults_to_ten(monkeypatch):
    monkeypatch.delenv(_GATE_MAX_ENV, raising=False)
    assert llm_review_runners.llm_gate_max_concurrent() == 10
    monkeypatch.setenv(_GATE_MAX_ENV, "3")
    assert llm_review_runners.llm_gate_max_concurrent() == 3
    # A malformed override falls back to the audited default ...
    monkeypatch.setenv(_GATE_MAX_ENV, "not-a-number")
    assert llm_review_runners.llm_gate_max_concurrent() == 10
    # ... while numeric out-of-range values clamp into the governed band.
    for too_small in ("0", "-4"):
        monkeypatch.setenv(_GATE_MAX_ENV, too_small)
        assert llm_review_runners.llm_gate_max_concurrent() == 1
    monkeypatch.setenv(_GATE_MAX_ENV, "100000")
    assert (
        llm_review_runners.llm_gate_max_concurrent()
        == llm_review_runners._LLM_GATE_MAX_CONCURRENT_LIMIT
    )


# ---------------------------------------------------------------------------
# (b) acquire timeout fails fast into the recoverable classification
# ---------------------------------------------------------------------------


def test_gate_acquire_timeout_fails_fast_with_recoverable_classification(monkeypatch):
    monkeypatch.setenv(_GATE_MAX_ENV, "1")
    monkeypatch.setenv(_GATE_WAIT_ENV, "0.1")
    llm_review_runners.reset_llm_gate_for_tests()

    with llm_review_runners._llm_gate_slot(
        purpose="holder", model_ref="fake-provider/fake-review-model"
    ):
        started = time.monotonic()
        with pytest.raises(llm_review_runners.ReviewLLMGateTimeoutError) as excinfo:
            with llm_review_runners._llm_gate_slot(
                purpose="hypothesis_pairwise",
                model_ref="fake-provider/fake-review-model",
            ):
                pytest.fail("a second slot must not be granted on a 1-slot gate")
        waited = time.monotonic() - started

    # Fast failure: bounded by the (tiny) acquire timeout, not the default.
    assert waited < 5.0
    error = excinfo.value
    assert isinstance(error, LLMError)
    assert error.category == "gate_timeout"
    assert error.retryable is True
    assert error.purpose == "hypothesis_pairwise"
    assert llm_review_runners._review_llm_error_category(error) == "llm_gate_rejected"
    assert llm_review_runners.is_recoverable_review_llm_gate_error(error)


def test_summary_draft_gate_rejection_requeues_instead_of_crashing(
    tmp_path, monkeypatch
):
    """A gate-starved digest draft keeps the recoverable retry path (B5)."""

    from core.web.services.team_workflow import meeting_runtime
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        server_operator_scope,
    )
    from tests.test_research_workflow_hypothesis_first_chain import (
        _ROLES,
        _hf_env,
        _open_first_meeting,
        _patch_approved_question,
    )

    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]

    def gate_starved(*_args, **_kwargs):
        raise llm_review_runners.ReviewLLMGateTimeoutError(
            purpose="meeting_digest",
            model_ref="fake-provider/fake-review-model",
            wait_seconds=120.0,
        )

    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        original_builder = meeting_runtime.build_meeting_digest_draft
        monkeypatch.setattr(meeting_runtime, "build_meeting_digest_draft", gate_starved)
        failed = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert failed["status"] == "summarizing"
        assert failed["summaryDraftError"]["code"] == "summary_draft_gate_rejected"
        meeting = meeting_runtime.meeting_rounds.get_meeting_round(team_id, meeting_id)
        assert meeting["meetingRound"]["status"] == "summarizing"
        assert (
            meeting["meetingRound"]["summaryDraftError"]["code"]
            == "summary_draft_gate_rejected"
        )

        monkeypatch.setattr(
            meeting_runtime, "build_meeting_digest_draft", original_builder
        )
        retried = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert retried["status"] == "awaiting_approval"
        assert retried.get("summaryDraftError") in (None, {})


# ---------------------------------------------------------------------------
# (c) provider 429 opens a model-level cooldown, then recovers
# ---------------------------------------------------------------------------


def test_provider_429_cooldown_fast_fails_same_model_then_recovers(monkeypatch):
    monkeypatch.setenv(_GATE_MAX_ENV, "4")
    monkeypatch.setenv(_COOLDOWN_ENV, "0.1")
    llm_review_runners.reset_llm_gate_for_tests()

    model_ref = "fake-provider/fake-review-model"
    state = {"calls": 0}
    lock = threading.Lock()

    def throttled_then_ok(client, messages, tools=None, context=None, **kwargs):
        with lock:
            state["calls"] += 1
            attempt = state["calls"]
        if attempt == 1:
            raise LLMError("rate_limit_error", "429 too many requests", retryable=True)
        return _FakeResponse(_pairwise_payload())

    monkeypatch.setattr(llm_review_runners, "invoke_llm", throttled_then_ok)
    monkeypatch.setattr(
        llm_review_runners, "review_llm_call_timeout_seconds", lambda **_kw: 30.0
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        {
            "client": object(),
            "profileId": "primary",
            "modelId": "fake-review-model",
            "modelRef": model_ref,
        }
    )
    call = lambda: runners["pairwise_runner"](  # noqa: E731
        {"candidateId": "cand-a", "claim": "假说 A"},
        {"candidateId": "cand-b", "claim": "假说 B"},
        _review_context(),
    )

    # 1) The real provider 429 propagates unchanged ...
    with pytest.raises(LLMError) as excinfo:
        call()
    assert excinfo.value.category == "rate_limit_error"
    assert state["calls"] == 1

    # ... and opens the cooldown for the model.
    with llm_review_runners._gate_state_lock:
        assert model_ref.lower() in llm_review_runners._rate_limit_cooldown_until

    # 2) Inside the window the same model fast-fails without a new request.
    with pytest.raises(llm_review_runners.ReviewLLMRateLimitCooldownError) as cooldown:
        call()
    assert state["calls"] == 1, "cooldown window must not reach the provider"
    assert cooldown.value.category == "rate_limit_cooldown"
    assert cooldown.value.retryable is True
    assert (
        llm_review_runners._review_llm_error_category(cooldown.value)
        == "llm_gate_rejected"
    )
    assert llm_review_runners.is_recoverable_review_llm_gate_error(cooldown.value)

    # 3) A different model is never affected by the cooldown.
    other_runners = llm_review_runners.build_hypothesis_review_runners(
        {
            "client": object(),
            "profileId": "primary",
            "modelId": "other-model",
            "modelRef": "fake-provider/other-model",
        }
    )
    other = other_runners["pairwise_runner"](
        {"candidateId": "cand-a", "claim": "假说 A"},
        {"candidateId": "cand-b", "claim": "假说 B"},
        _review_context(),
    )
    assert other["outcome"] == "left_wins"
    assert state["calls"] == 2

    # 4) Once the window expires the throttled model recovers.
    time.sleep(0.15)
    recovered = call()
    assert recovered["outcome"] == "left_wins"
    assert state["calls"] == 3


def test_gate_rejections_never_extend_the_cooldown_window(monkeypatch):
    """Fast-fail gate errors are not provider 429s: they must not re-arm."""

    monkeypatch.setenv(_COOLDOWN_ENV, "60")
    llm_review_runners.reset_llm_gate_for_tests()
    llm_review_runners._record_model_rate_limit(
        "fake-provider/fake-review-model", now_s=1_000.0
    )
    with llm_review_runners._gate_state_lock:
        before = llm_review_runners._rate_limit_cooldown_until[
            "fake-provider/fake-review-model"
        ]

    llm_review_runners._maybe_record_provider_rate_limit(
        llm_review_runners.ReviewLLMGateTimeoutError(
            purpose="p", model_ref="fake-provider/fake-review-model", wait_seconds=1.0
        ),
        model_ref="fake-provider/fake-review-model",
    )
    llm_review_runners._maybe_record_provider_rate_limit(
        llm_review_runners.ReviewLLMRateLimitCooldownError(
            purpose="p",
            model_ref="fake-provider/fake-review-model",
            cooldown_remaining_seconds=1.0,
        ),
        model_ref="fake-provider/fake-review-model",
    )

    with llm_review_runners._gate_state_lock:
        after = llm_review_runners._rate_limit_cooldown_until[
            "fake-provider/fake-review-model"
        ]
    assert after == before


# ---------------------------------------------------------------------------
# (d) litellm 路径 429（关键词类别 ``rate_limit``）同样打开模型冷却
# ---------------------------------------------------------------------------


def test_litellm_429_opens_cooldown_but_gate_errors_do_not():
    """生产通道走 litellm：litellm 429 样本必须进入模型冷却，gate 快速失败
    异常绝不打开/延长冷却（防拒绝风暴自我续命）。"""

    pytest.importorskip("litellm")
    from litellm import RateLimitError as LiteLLMRateLimitError

    model_ref = "fake-provider/fake-litellm-model"
    litellm_429 = LiteLLMRateLimitError(
        message="Rate limit error: 429 Too Many Requests",
        model="fake-litellm-model",
        llm_provider="openai",
    )

    llm_review_runners._maybe_record_provider_rate_limit(
        litellm_429, model_ref=model_ref
    )
    with llm_review_runners._gate_state_lock:
        assert model_ref.lower() in llm_review_runners._rate_limit_cooldown_until

    # 冷却生效：同模型下一次调用在到达 provider 前被快速失败。
    with pytest.raises(llm_review_runners.ReviewLLMRateLimitCooldownError) as cooldown:
        llm_review_runners._raise_if_model_cooling_down(
            purpose="pairwise", model_ref=model_ref
        )
    assert cooldown.value.category == "rate_limit_cooldown"
    assert cooldown.value.retryable is True

    # 不变式：gate 自身快速失败异常不是 provider 429，不打开也不延长冷却。
    llm_review_runners.reset_llm_gate_for_tests()
    with llm_review_runners._gate_state_lock:
        assert llm_review_runners._rate_limit_cooldown_until == {}
    for gate_error in (
        llm_review_runners.ReviewLLMGateTimeoutError(
            purpose="p", model_ref=model_ref, wait_seconds=1.0
        ),
        llm_review_runners.ReviewLLMRateLimitCooldownError(
            purpose="p", model_ref=model_ref, cooldown_remaining_seconds=1.0
        ),
    ):
        llm_review_runners._maybe_record_provider_rate_limit(
            gate_error, model_ref=model_ref
        )
        with llm_review_runners._gate_state_lock:
            assert llm_review_runners._rate_limit_cooldown_until == {}, gate_error


def test_litellm_429_without_keywords_still_opens_cooldown():
    """litellm.RateLimitError 消息缺 "429"/"rate limit" 关键词时靠类型证据
    补漏（classify_error 显式规则），冷却照常打开；裸 "HTTP 1429" 不是 429，
    绝不触发。"""

    pytest.importorskip("litellm")
    from litellm import RateLimitError as LiteLLMRateLimitError

    model_ref = "fake-provider/fake-litellm-quiet-model"
    llm_review_runners._maybe_record_provider_rate_limit(
        LiteLLMRateLimitError(
            message="Too many requests, please retry later",
            model="fake-litellm-quiet-model",
            llm_provider="openai",
        ),
        model_ref=model_ref,
    )
    with llm_review_runners._gate_state_lock:
        deadline_before = llm_review_runners._rate_limit_cooldown_until[
            model_ref.lower()
        ]

    llm_review_runners._maybe_record_provider_rate_limit(
        RuntimeError("HTTP 1429 trace-id=1"), model_ref=model_ref
    )
    with llm_review_runners._gate_state_lock:
        assert (
            llm_review_runners._rate_limit_cooldown_until[model_ref.lower()]
            == deadline_before
        ), "纯子串 1429 不得打开或延长冷却窗口"


# ---------------------------------------------------------------------------
# (d) exception paths always release the slot
# ---------------------------------------------------------------------------


def test_gate_slot_releases_on_exception_path(monkeypatch):
    monkeypatch.setenv(_GATE_MAX_ENV, "2")
    llm_review_runners.reset_llm_gate_for_tests()

    with pytest.raises(RuntimeError, match="boom"):
        with llm_review_runners._llm_gate_slot(
            purpose="p", model_ref="fake-provider/fake-review-model"
        ):
            raise RuntimeError("boom")

    # Both slots are available again (2 acquires succeed, the 3rd is refused).
    acquired = []
    semaphore = llm_review_runners._llm_gate()
    for index in range(2):
        assert semaphore.acquire(timeout=0.1), f"slot {index} leaked"
        acquired.append(True)
    assert semaphore.acquire(timeout=0.1) is False
    for _ in acquired:
        semaphore.release()


def test_repeated_concurrent_failure_waves_never_leak_slots(monkeypatch):
    """Mixed success/failure waves must leave the semaphore at full capacity."""

    monkeypatch.setenv(_GATE_MAX_ENV, "4")
    llm_review_runners.reset_llm_gate_for_tests()

    def flaky_invoke(client, messages, tools=None, context=None, **kwargs):
        # Fail every even-indexed call so the wave exercises exception
        # release paths while others are in flight.
        content = str(getattr(messages[-1], "content", "") or messages[-1]["content"])
        match = re.search(r'cand-(\d+)', content)
        call_index = int(match.group(1)) if match else 0
        if call_index % 2 == 0:
            raise LLMError("provider_error", "simulated provider outage")
        return _FakeResponse(_pairwise_payload())

    monkeypatch.setattr(llm_review_runners, "invoke_llm", flaky_invoke)
    monkeypatch.setattr(
        llm_review_runners, "review_llm_call_timeout_seconds", lambda **_kw: 30.0
    )

    def run_wave(wave: int) -> list[bool]:
        outcomes: list[bool] = []
        lock = threading.Lock()

        def worker(index: int) -> None:
            try:
                _run_pairwise_call((wave * 100) + index)
                with lock:
                    outcomes.append(True)
            except LLMError:
                with lock:
                    outcomes.append(False)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker, index) for index in range(8)]
            for future in futures:
                future.result(timeout=30)
        return outcomes

    for wave in range(4):
        outcomes = run_wave(wave)
        assert sorted(outcomes) == [False] * 4 + [True] * 4, (
            f"wave {wave} saw unexpected outcomes: {outcomes}"
        )

    semaphore = llm_review_runners._llm_gate()
    acquired = 0
    while semaphore.acquire(timeout=0.1):
        acquired += 1
        if acquired > 4:  # pragma: no cover - bound the loop
            break
    assert acquired == 4, "exception paths leaked gate slots"
    for _ in range(acquired):
        semaphore.release()


def test_failure_path_under_concurrency_still_releases_gate_slots(monkeypatch):
    """Provider failures inside the gate must not starve later calls."""

    monkeypatch.setenv(_GATE_MAX_ENV, "2")
    llm_review_runners.reset_llm_gate_for_tests()

    def failing_invoke(client, messages, tools=None, context=None, **kwargs):
        raise LLMError("provider_error", "simulated provider outage")

    monkeypatch.setattr(llm_review_runners, "invoke_llm", failing_invoke)
    monkeypatch.setattr(
        llm_review_runners, "review_llm_call_timeout_seconds", lambda **_kw: 30.0
    )

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(_run_pairwise_call, index) for index in range(6)
        ]
        for future in futures:
            with pytest.raises(LLMError):
                future.result(timeout=30)

    semaphore = llm_review_runners._llm_gate()
    acquired = 0
    while semaphore.acquire(timeout=0.1):
        acquired += 1
        if acquired > 2:  # pragma: no cover - bound the loop
            break
    assert acquired == 2, "provider-failure paths leaked gate slots"
    for _ in range(acquired):
        semaphore.release()
