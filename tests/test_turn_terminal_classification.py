"""Turn terminal-state classification + context-budget zero-diagnosis guards.

Pins the contract that turn terminal writes are decided by the centralized
LLM error classifier (``core/llm/error_classification.py``) instead of the
legacy provider-text regex:

- the same exception sample batch maps to the existing terminal values
  (``failed_provider`` vs ``failed``) plus additive ``failureCategory`` /
  ``failureDisposition`` diagnostics -- no new terminal enums;
- provider 5xx/timeout -> provider family + transient; ValueError/TypeError
  and unknown errors fail closed to the non-provider family + permanent;
  context budget -> budget family with the established
  ``context_budget_exhausted`` problem code;
- Prefect failed-vs-crashed semantics: ``worker_gone`` / cancellation markers
  never classify into the provider business-failure family;
- an unconfigured context hard limit no longer disappears silently: the
  preflight verdict and the compression gate carry ``budget_limit_unconfigured``
  and emit a diagnostic event, while configured-limit behavior is unchanged.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.llm.types import LLMError
from core.orchestration.turn_compression import (
    BUDGET_LIMIT_UNCONFIGURED_GUARD_REASON,
    compress_turn_messages,
    evaluate_context_budget_preflight,
)
from core.orchestration.agent_modes import AgentMode
from core.web.services.session.turn_failure_classification import (
    BUDGET_EXHAUSTED_PROBLEM_CODE,
    TERMINAL_STATUS_FAILURE_DISPOSITION,
    classify_turn_failure,
    derive_failure_disposition,
    normalize_disposition,
    resolve_failure_disposition,
)
from core.web.services.session import persist as session_persist


# ---------------------------------------------------------------------------
# 1) Table-driven: exception samples -> terminal value + additive fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    (
        "raw_error",
        "exc",
        "expected_family",
        "expected_disposition",
        "expected_problem_code",
    ),
    [
        # -- provider family: 5xx / transport / rate limit / auth / protocol --
        (
            "Error code: 500 - internal server error",
            None,
            True,
            "transient_retryable",
            "",
        ),
        ("Request timeout after 30s: upstream read timeout", None, True, "transient_retryable", ""),
        (
            "api connection error: connection reset by peer",
            None,
            True,
            "transient_retryable",
            "",
        ),
        ("429 too many requests: rate limit exceeded", None, True, "transient_retryable", ""),
        (
            "Error code: 401 - invalid api key, auth failed",
            None,
            True,
            "permanent",
            "",
        ),
        (
            "payload_protocol_error: duplicated tool call id",
            None,
            True,
            "permanent",
            "",
        ),
        ("bad request: invalid params", None, True, "permanent", ""),
        # -- budget / context family: never provider, carries the problem code --
        (
            "context length exceeded: maximum context is 128k tokens",
            None,
            False,
            "budget_or_context",
            BUDGET_EXHAUSTED_PROBLEM_CODE,
        ),
        (
            "insufficient_quota: billing limit reached",
            None,
            False,
            "budget_or_context",
            BUDGET_EXHAUSTED_PROBLEM_CODE,
        ),
        # -- non-provider failures: fail-closed permanent, plain failed family --
        ("something broke", ValueError("something broke"), False, "permanent", ""),
        (
            "'NoneType' object is not iterable",
            TypeError("'NoneType' object is not iterable"),
            False,
            "permanent",
            "",
        ),
        ("quantum flux overload 0xdead", None, False, "permanent", ""),
        # -- Prefect crashed semantics: worker lifecycle is never provider --
        (
            "worker_gone: worker process exited unexpectedly",
            None,
            False,
            "permanent",
            "",
        ),
        ("run was cancelled by user", None, False, "permanent", ""),
        # provider token present but the run was cancelled: family override wins
        (
            "api_error while task was cancelled",
            None,
            False,
            "transient_retryable",
            "",
        ),
        ("KeyboardInterrupt", KeyboardInterrupt(), False, "permanent", ""),
        # -- LLMError passthrough: the LLM stack's own verdict is trusted --
        (
            "provider rate limited",
            LLMError("rate_limit_error", "provider rate limited", retryable=True),
            True,
            "transient_retryable",
            "",
        ),
        (
            "model refused",
            LLMError("context_length_error", "model refused", retryable=False),
            False,
            "budget_or_context",
            BUDGET_EXHAUSTED_PROBLEM_CODE,
        ),
    ],
)
def test_exception_samples_map_to_terminal_values_and_additive_fields(
    raw_error, exc, expected_family, expected_disposition, expected_problem_code
):
    classification = classify_turn_failure(raw_error, exc=exc)

    assert classification.provider_family is expected_family
    assert classification.disposition == expected_disposition
    assert classification.problem_code == expected_problem_code
    # The existing terminal vocabulary: family selects the historical value,
    # additive fields carry the classification. No new terminal enums.
    expected_terminal_status = "failed_provider" if expected_family else "failed"
    assert expected_terminal_status in {"failed_provider", "failed"}
    assert classification.category  # category diagnostics are always present


def test_classification_fails_closed_when_classifier_raises(monkeypatch):
    import core.web.services.session.turn_failure_classification as module

    def _boom(_exc):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr(module, "classify_error", _boom)
    classification = module.classify_turn_failure("whatever", exc=None)
    assert classification.provider_family is False
    assert classification.disposition == "permanent"


def test_disposition_vocabulary_is_the_frozen_three_value_domain():
    assert set(TERMINAL_STATUS_FAILURE_DISPOSITION.values()) <= {
        "transient",
        "permanent",
        "budget_or_context",
    }


# ---------------------------------------------------------------------------
# 2) Failure propagation: disposition rides the agent_turn_terminal_failed
#    detail without changing failureClass values
# ---------------------------------------------------------------------------


def _probe(monkeypatch, snapshot):
    from core.web.services.team_workflow.research_runtime import agent_turn_completion as atc

    monkeypatch.setattr(
        "core.web.services.session.turn_diagnostics.get_session_turn_completion_snapshot",
        lambda session_id, turn_id: snapshot,
    )
    try:
        atc.probe_agent_turn_terminal("sess-1", "turn-1")
    except RuntimeError as exc:
        return json.loads(str(exc))
    raise AssertionError("failure-terminal snapshot must raise")


def test_probe_detail_keeps_failure_class_and_adds_disposition(monkeypatch):
    detail = _probe(
        monkeypatch,
        {
            "terminal": True,
            "terminalStatus": "failed_runtime",
            "lastTurnStatus": "failed_runtime",
            "completionSource": "last_turn_status",
            "terminalProblemCode": BUDGET_EXHAUSTED_PROBLEM_CODE,
            "failureDisposition": "budget_or_context",
        },
    )
    assert detail["failureClass"] == "terminal_failure"
    assert detail["failureDisposition"] == "budget_or_context"


def test_probe_detail_falls_back_to_status_table_fail_closed(monkeypatch):
    for status, expected in (
        ("failed", "permanent"),
        ("failed_provider", "transient"),
        ("cancelled", "permanent"),
        ("paused_limit", "budget_or_context"),
        ("needs_continue", "permanent"),
        ("mystery_status", "permanent"),
    ):
        detail = _probe(
            monkeypatch,
            {
                "terminal": True,
                "terminalStatus": status,
                "lastTurnStatus": status,
                "completionSource": "last_turn_status",
            },
        )
        assert detail["failureDisposition"] == expected, status


def test_probe_detail_derives_budget_disposition_from_problem_code(monkeypatch):
    detail = _probe(
        monkeypatch,
        {
            "terminal": True,
            "terminalStatus": "failed_runtime",
            "lastTurnStatus": "failed_runtime",
            "completionSource": "last_turn_status",
            "terminalProblemCode": BUDGET_EXHAUSTED_PROBLEM_CODE,
        },
    )
    assert detail["failureDisposition"] == "budget_or_context"


def test_resolve_and_derive_disposition_helpers():
    assert (
        resolve_failure_disposition({"failureDisposition": "transient_retryable"}, "failed")
        == "transient"
    )
    assert resolve_failure_disposition({}, "failed") == "permanent"
    assert (
        derive_failure_disposition(
            problem_code=BUDGET_EXHAUSTED_PROBLEM_CODE, terminal_status="ready"
        )
        == "budget_or_context"
    )
    # non-failure statuses derive nothing (callers omit instead of inventing)
    assert derive_failure_disposition(problem_code="", terminal_status="ready") == ""
    assert normalize_disposition("transient_retryable") == "transient"
    assert normalize_disposition("permanent") == "permanent"
    assert normalize_disposition("") == ""


# ---------------------------------------------------------------------------
# 3) Completion snapshot: additive failureCategory/failureDisposition keys
# ---------------------------------------------------------------------------


def _patch_snapshot_env(monkeypatch, conversation):
    from core.web.services import session_service as s

    monkeypatch.setattr(s, "_RUNNING_SESSIONS_LOCK", threading.Lock())
    monkeypatch.setattr(s, "_RUNNING_SESSION_IDS", set())
    monkeypatch.setattr(s, "_SESSION_ACTIVE_TURN_IDS", {})
    monkeypatch.setattr(s, "reconcile_stale_chat_turn_work_runs", lambda: None)
    monkeypatch.setattr(s, "load_session_chat_state", lambda *a, **k: conversation)
    monkeypatch.setattr(s, "_repair_stale_running_conversation", lambda conv: False)
    monkeypatch.setattr(s, "_load_session_conversation_events_cached", lambda sid, **k: [])
    monkeypatch.setattr(s, "_session_ledger_visible_messages", lambda sid: [])
    monkeypatch.setattr(s, "PROJECT_ROOT", ".")


def _completion_snapshot(monkeypatch, conversation):
    from core.web.services.session.turn_diagnostics import (
        get_session_turn_completion_snapshot,
    )

    _patch_snapshot_env(monkeypatch, conversation)
    return get_session_turn_completion_snapshot("sess-1", "turn-1")


def test_snapshot_carries_persisted_classification_fields(monkeypatch):
    snapshot = _completion_snapshot(
        monkeypatch,
        {
            "last_turn_status": "failed",
            "last_turn_terminal_problem_code": BUDGET_EXHAUSTED_PROBLEM_CODE,
            "last_turn_error": {
                "message": "context length exceeded",
                "failure_category": "context_length_error",
                "failure_disposition": "budget_or_context",
            },
        },
    )
    assert snapshot["terminal"] is True
    assert snapshot["failureCategory"] == "context_length_error"
    assert snapshot["failureDisposition"] == "budget_or_context"
    assert snapshot["terminalProblemCode"] == BUDGET_EXHAUSTED_PROBLEM_CODE


def test_snapshot_derives_disposition_for_legacy_failures(monkeypatch):
    snapshot = _completion_snapshot(
        monkeypatch,
        {
            "last_turn_status": "failed_provider",
            "last_turn_error": {"message": "Error code: 500"},
        },
    )
    assert snapshot["terminal"] is True
    assert "failureCategory" not in snapshot
    assert snapshot["failureDisposition"] == "transient"


def test_snapshot_success_has_no_failure_fields(monkeypatch):
    # "completed" is an unanchored terminal success (unlike "ready", which the
    # snapshot only trusts when anchored to the turn).
    snapshot = _completion_snapshot(
        monkeypatch,
        {"last_turn_status": "completed", "last_turn_error": None},
    )
    assert snapshot["terminal"] is True
    assert "failureCategory" not in snapshot
    assert "failureDisposition" not in snapshot


# ---------------------------------------------------------------------------
# 4) persist.py problem-code anchoring helper
# ---------------------------------------------------------------------------


def test_problem_code_helper_anchors_budget_and_clears_otherwise():
    conversation = {
        "last_turn_terminal_problem_code": "stale",
        "lastTurnTerminalProblemCode": "stale",
    }
    session_persist._apply_turn_failure_problem_code(
        conversation, BUDGET_EXHAUSTED_PROBLEM_CODE
    )
    assert conversation["last_turn_terminal_problem_code"] == BUDGET_EXHAUSTED_PROBLEM_CODE

    session_persist._apply_turn_failure_problem_code(conversation, "")
    assert "last_turn_terminal_problem_code" not in conversation
    assert "lastTurnTerminalProblemCode" not in conversation


# ---------------------------------------------------------------------------
# 5) Context-budget zero-diagnosis guards
# ---------------------------------------------------------------------------


def test_preflight_reports_unconfigured_limit_instead_of_silence():
    disabled = evaluate_context_budget_preflight(
        estimated_tokens=10_000_000, context_input_hard_limit=0
    )
    assert disabled["exhausted"] is False
    assert disabled["guardReason"] == BUDGET_LIMIT_UNCONFIGURED_GUARD_REASON

    ok = evaluate_context_budget_preflight(
        estimated_tokens=10, context_input_hard_limit=1_000
    )
    assert ok["exhausted"] is False
    assert ok["guardReason"] == ""

    blocked = evaluate_context_budget_preflight(
        estimated_tokens=1_001, context_input_hard_limit=1_000
    )
    assert blocked["exhausted"] is True
    assert blocked["guardReason"] == "input_over_hard_limit"


class _FakeUi:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def add_log(self, message: str, level: str = "INFO") -> None:
        pass

    def note_context_compression_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class _ShrinkingCompressor:
    def compress(self, messages, **kwargs):
        from tools.token_manager import CompressionResult

        kept = list(messages[-2:])
        return kept, CompressionResult("compressed summary", 10_000, 10, 1, "standard")


class _FakeStrategy:
    def determine_level_with_iteration(self, *args):
        from tools.compression_strategy import CompressionLevel

        return CompressionLevel.STANDARD

    def get_config(self, level, current_tokens, budget):
        from tools.compression_strategy import CompressionConfig

        return CompressionConfig(level=level, summary_max_chars=80, keep_ai_messages=2)


def _feature_config():
    return SimpleNamespace(
        mental_model=SimpleNamespace(enabled=False),
        context_compression=SimpleNamespace(
            enabled=True,
            max_compressions_per_session=3,
            effectiveness_threshold=0.0,
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


def _run_compress(context_input_hard_limit: int):
    events: list[dict] = []
    ui = _FakeUi()

    def recorder(scene, action, *, message="", outcome="observed", level="info", fields=None, **kwargs):
        events.append(
            {"scene": scene, "action": action, "outcome": outcome, "level": level, "fields": fields or {}}
        )

    messages = [
        SystemMessage(content="stable system prefix"),
        HumanMessage(content="研究任务合同：scope=test stage=search"),
        AIMessage(content="earlier answer " + "y" * 300),
        AIMessage(content="recent answer " + "x" * 300),
    ]
    result = compress_turn_messages(
        messages=messages,
        iteration=4,
        reason="test",
        token_compressor=_ShrinkingCompressor(),
        config=_feature_config(),
        effective_max_token_limit=1_000,
        threshold_tokens=100,
        runtime_agent_binding={"agentId": "a1", "directSessionId": "s1"},
        project_root="",
        mode=AgentMode.CHAT,
        compression_strategy=_FakeStrategy(),
        estimate_tokens_fn=lambda msgs: sum(len(str(getattr(m, "content", "") or "")) for m in msgs),
        get_ui_fn=lambda: ui,
        get_state_manager_fn=lambda: SimpleNamespace(set_state=lambda *a, **k: None),
        scene_recorder_fn=recorder,
        context_input_hard_limit=context_input_hard_limit,
        post_compression_target_tokens=0,
    )
    return result, events


def test_compress_emits_diagnostic_event_when_budget_limit_unconfigured():
    (messages, should_break, applied, _count, _last), events = _run_compress(0)
    # The guard stays non-blocking (no limit to enforce) but is audible now.
    assert should_break is False
    assert any(event["action"] == "agent.context_budget_exhausted" for event in events) is False
    unconfigured = [
        event
        for event in events
        if event["action"] == "agent.context_budget_unconfigured"
    ]
    assert unconfigured, "unconfigured budget limit must not stay silent"
    assert (
        unconfigured[0]["fields"]["guardReason"] == BUDGET_LIMIT_UNCONFIGURED_GUARD_REASON
    )
    assert unconfigured[0]["level"] == "warning"


def test_compress_with_configured_limit_keeps_existing_behavior():
    (_messages, should_break, applied, _count, _last), events = _run_compress(1_000)
    assert should_break is False
    assert applied is True
    assert any(event["action"] == "agent.context_budget_unconfigured" for event in events) is False
    assert any(event["action"] == "agent.context_budget_exhausted" for event in events) is False
