"""Focused tests for turn diagnostics that agent.py currently stubs away."""

from types import SimpleNamespace
import threading

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from core.orchestration.turn_diagnostics import (
    build_llm_invocation_context,
    publish_llm_retry_status,
    record_turn_cache_diagnostics,
    report_round_state_stall_signals,
)


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def publish(self, name, payload, source=None):
        self.events.append((name, payload, source))


class _Ui:
    def __init__(self, *, snapshot=None, snapshot_error=False, note_error=False) -> None:
        self.notes: list[dict] = []
        self._snapshot = snapshot or {}
        self._snapshot_error = snapshot_error
        self._note_error = note_error

    def cache_average_snapshot(self):
        if self._snapshot_error:
            raise RuntimeError("snapshot failed")
        return self._snapshot

    def note_cache_diagnostics(self, **kwargs):
        if self._note_error:
            raise RuntimeError("persist failed")
        self.notes.append(kwargs)


def test_publish_llm_retry_status_skips_empty_and_publishes_reconnect_payload():
    bus = _Bus()
    publish_llm_retry_status(
        attempt=2,
        max_attempts=5,
        category="",
        action="",
        event_bus_getter=lambda: bus,
    )
    assert bus.events == []

    publish_llm_retry_status(
        attempt=2,
        max_attempts=5,
        category="network_error",
        action="retry_with_backoff",
        event_bus_getter=lambda: bus,
    )
    assert len(bus.events) == 1
    name, payload, source = bus.events[0]
    assert name == "llm:status"
    assert source == "AgentRuntime"
    assert payload["status"] == "retrying"
    assert payload["attempt"] == 2
    assert payload["max_attempts"] == 5
    assert payload["category"] == "network_error"
    assert payload["recovery_action"] == "retry_with_backoff"
    assert payload["source"] == "agent_outer_reconnect"


def test_publish_llm_retry_status_swallows_bus_failures():
    publish_llm_retry_status(
        attempt=1,
        max_attempts=3,
        category="timeout",
        action="retry",
        event_bus_getter=lambda: (_ for _ in ()).throw(RuntimeError("bus down")),
    )


def test_build_llm_invocation_context_falls_back_and_clamps_route_attempt():
    context = build_llm_invocation_context(
        runtime_binding={"agentId": "agent-1", "directSessionId": "session-from-binding", "llmSlot": ""},
        mode_value="chat",
        orchestrator_kind="chat",
        route_attempt=0,
        turn_runtime_fn=lambda: {},
        status_context_fn=lambda: {"turn_id": "turn-status"},
    )
    assert context.surface == "chat_turn"
    assert context.conversation_bound is True
    assert context.session_id == "session-from-binding"
    assert context.agent_id == "agent-1"
    assert context.llm_slot == "dialogue"
    assert context.metadata["routeAttempt"] == 1
    assert context.metadata["turnId"] == "turn-status"

    agent_context = build_llm_invocation_context(
        mode_value="self_evolution",
        orchestrator_kind="evolution",
        turn_runtime_fn=lambda: {"runKind": "supervised_case", "runId": "run-9"},
        status_context_fn=lambda: {},
    )
    assert agent_context.surface == "agent_turn"
    assert agent_context.run_kind == "supervised_case"
    assert agent_context.run_id == "run-9"
    assert agent_context.conversation_bound is False


def test_record_turn_cache_diagnostics_notes_usage_and_survives_ui_errors():
    token_usage = SimpleNamespace(
        observed=True,
        input_tokens=120,
        output_tokens=8,
        total_tokens=128,
        cached_input_tokens=40,
        cache_creation_input_tokens=0,
        uncached_input_tokens=80,
    )
    response = SimpleNamespace(response_metadata={"provider": "openai", "model": "gpt-test"})
    messages = [SystemMessage(content="system prompt"), HumanMessage(content="hello")]
    ui = _Ui()

    llm_usage, metadata = record_turn_cache_diagnostics(
        token_usage=token_usage,
        response=response,
        messages=messages,
        current_turn=7,
        context_window_limit=8000,
        get_ui_fn=lambda: ui,
        turn_runtime_fn=lambda: {
            "sessionId": "s1",
            "runId": "t7",
            "promptCachePartition": "part-secret",
        },
    )

    assert llm_usage["source"] == "provider_usage"
    assert llm_usage["inputTokens"] == 120
    assert llm_usage["cachedInputTokens"] == 40
    assert llm_usage["promptCachePartition"] == "part-secret"
    assert metadata["context_composition"]["limitTokens"] == 8000
    assert metadata["cache_composition"]["source"] == "provider_usage"
    assert ui.notes and ui.notes[0]["llm_usage"]["cachedInputTokens"] == 40

    failing_ui = _Ui(snapshot_error=True, note_error=True)
    usage, metadata = record_turn_cache_diagnostics(
        token_usage=token_usage,
        response=response,
        messages=messages,
        current_turn=7,
        context_window_limit="not-a-number",
        get_ui_fn=lambda: failing_ui,
        turn_runtime_fn=lambda: {},
    )
    assert usage["source"] == "provider_usage"
    assert metadata["context_composition"]["limitTokens"] == 0
    assert failing_ui.notes == []


def test_publish_and_invocation_context_decode_bytes_json_and_snake_runtime():
    bus = _Bus()
    publish_llm_retry_status(
        attempt=b"3",
        max_attempts="4",
        category=b"network_error",
        action=b"retry_with_backoff",
        event_bus_getter=lambda: bus,
    )
    assert bus.events[0][1]["category"] == "network_error"
    assert bus.events[0][1]["attempt"] == 3
    assert bus.events[0][1]["max_attempts"] == 4

    context = build_llm_invocation_context(
        runtime_binding='{"agentId":"agent-json","direct_session_id":"session-json"}',
        mode_value=b"chat",
        orchestrator_kind="chat",
        route_attempt="2",
        turn_runtime_fn=lambda: {"run_kind": "supervised_case", "run_id": b"run-snake"},
        status_context_fn=lambda: '{"turnId":"turn-json"}',
    )
    assert context.surface == "chat_turn"
    assert context.session_id == "session-json"
    assert context.agent_id == "agent-json"
    assert context.run_kind == "supervised_case"
    assert context.run_id == "run-snake"
    assert context.metadata["routeAttempt"] == 2
    assert context.metadata["turnId"] == "turn-json"


def test_record_cache_diagnostics_rejects_string_split_and_parses_json_metadata():
    token_usage = SimpleNamespace(
        observed=True,
        input_tokens=10,
        output_tokens=1,
        total_tokens=11,
        cached_input_tokens=0,
        cache_creation_input_tokens=0,
        uncached_input_tokens=10,
    )
    ui = _Ui()
    llm_usage, metadata = record_turn_cache_diagnostics(
        token_usage=token_usage,
        response={"responseMetadata": '{"provider":"openai","model":"gpt-test"}'},
        messages="abc",
        current_turn=b"9",
        context_window_limit=True,
        get_ui_fn=lambda: ui,
        turn_runtime_fn=lambda: {"prompt_cache_partition": "part-snake"},
    )
    assert metadata["context_composition"]["turnId"] == "9"
    assert metadata["context_composition"]["limitTokens"] == 0
    assert metadata["context_composition"]["segments"] == []
    assert llm_usage["promptCachePartition"] == "part-snake"


def test_report_stall_signals_coerces_json_telemetry_and_false_reported():
    class _State:
        def runtime_telemetry(self):
            return '{"consecutive_bookkeeping_tool_only_steps": 3}'

    warnings: list[tuple[str, str]] = []

    class _Log:
        def warning(self, msg, tag=""):
            warnings.append((str(msg), str(tag)))

    reported = report_round_state_stall_signals(
        _State(),
        '{"consecutive_bookkeeping_tool_only_steps":"false"}',
        debug_logger=_Log(),
    )
    assert reported.get("consecutive_bookkeeping_tool_only_steps") is True
    assert warnings
    assert warnings[0][1] == "STATE"


def test_diagnostics_unwrap_message_envelopes_and_json_response_without_true_attempt():
    bus = _Bus()
    publish_llm_retry_status(
        attempt=True,
        max_attempts=5,
        category="timeout",
        action="retry",
        event_bus_getter=lambda: bus,
    )
    assert bus.events[0][1]["attempt"] == 0

    token_usage = SimpleNamespace(
        observed=True,
        input_tokens=10,
        output_tokens=1,
        total_tokens=11,
        cached_input_tokens=0,
        cache_creation_input_tokens=0,
        uncached_input_tokens=10,
    )
    ui = _Ui()
    messages = [SystemMessage(content="system prompt"), HumanMessage(content="hello")]
    llm_usage, metadata = record_turn_cache_diagnostics(
        token_usage=token_usage,
        response=b'{"responseMetadata": {"provider": "openai", "model": "gpt-test"}}',
        messages={"messages": messages},
        current_turn=7,
        context_window_limit=8000,
        get_ui_fn=lambda: ui,
        turn_runtime_fn=lambda: {"promptCachePartition": "part-json"},
    )
    assert llm_usage["promptCachePartition"] == "part-json"
    assert metadata["context_composition"]["segments"]
    assert metadata["context_composition"]["turnId"] == "7"


def test_completion_snapshot_reads_only_legacy_receipt_from_journal_after_restart_style_projection(
    tmp_path,
    monkeypatch,
):
    from core.chat.turn_journal import (
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_TURN_STARTED,
        append_canonical_turn_outcome,
        append_turn_event,
        load_turn_events,
    )
    from core.llm.types import CanonicalItemIdentity, TurnOutcome
    from core.web.services.session import turn_diagnostics as session_turn_diagnostics

    receipt = {
        "receiptId": "receipt-1",
        "runId": "question-run-1",
        "responseExcerpt": "audit-only-receipt",
    }
    earlier_receipt = {
        "receiptId": "receipt-0",
        "runId": "question-run-1",
        "responseExcerpt": "audit-only-earlier-receipt",
    }
    identity = CanonicalItemIdentity("session-1", "turn-1", "inv-1", 0, "answer-1")
    append_turn_event(tmp_path, "session-1", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-1",
        "turn-1",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="completed",
        payload={
            "kind": "tool_call",
            "channel": "analysis",
            "phase": "tool_call",
            "modelInvocationReceipt": earlier_receipt,
        },
        source="canonical_turn_outcome",
    )
    append_canonical_turn_outcome(
        tmp_path,
        "session-1",
        "turn-1",
        TurnOutcome(
            kind="final_answer",
            identity=identity,
            final_text="canonical answer",
            terminal_event_seen=True,
            model_invocation_receipt=receipt,
        ),
    )

    class _RestartedSessionService:
        PROJECT_ROOT = tmp_path
        EVENT_TURN_COMPLETED = "turn_completed"
        EVENT_TURN_FAILED = "turn_failed"
        EVENT_TURN_INTERRUPTED = "turn_interrupted"
        _RUNNING_SESSIONS_LOCK = threading.Lock()
        _RUNNING_SESSION_IDS = set()
        _SESSION_ACTIVE_TURN_IDS = {}
        _CHAT_STATE_LOCK = threading.Lock()

        def reconcile_stale_chat_turn_work_runs(self):
            return None

        def load_session_chat_state(self, _project_root, _session_id):
            return {"last_turn_status": "completed"}

        def _repair_stale_running_conversation(self, _conversation):
            return False

        def _load_session_conversation_events_cached(self, session_id):
            return load_turn_events(self.PROJECT_ROOT, session_id)

        def _session_ledger_visible_messages(self, _session_id):
            # Simulate a restarted process whose model-visible projection has no
            # receipt metadata; the canonical journal remains available.
            return [
                {
                    "role": "assistant",
                    "content": "canonical answer",
                    "metadata": {"kind": "journal_assistant_message", "turnId": "turn-1"},
                }
            ]

        @staticmethod
        def _find_turn_scoped_assistant_message(messages, _turn_id):
            return messages[0] if messages else None

        @staticmethod
        def _message_turn_id(message):
            return str((message.get("metadata") or {}).get("turnId") or "")

        @staticmethod
        def _supervised_completion_marker_present(_text):
            return False

    monkeypatch.setattr(session_turn_diagnostics, "_service", lambda: _RestartedSessionService())

    snapshot = session_turn_diagnostics.get_session_turn_completion_snapshot("session-1", "turn-1")

    assert snapshot["terminal"] is True
    # New canonical outcomes persist Challenge receipts through the durable
    # registry and deliberately omit them from conversation events.  The
    # journal reader remains a compatibility path for historical receipts;
    # it must not recreate the registry-only receipt from ``TurnOutcome``.
    assert snapshot["modelInvocationReceipt"] == earlier_receipt
    assert snapshot["modelInvocationReceipts"] == [earlier_receipt]


def test_completion_snapshot_reconciles_before_acquiring_chat_state_lock(monkeypatch, tmp_path):
    """Stale settlement must not request the non-reentrant chat lock recursively."""
    from core.web.services.session import turn_diagnostics as session_turn_diagnostics

    class _TrackingLock:
        held = False

        def __enter__(self):
            assert not self.held
            self.held = True
            return self

        def __exit__(self, *_args):
            self.held = False

    class _SessionService:
        PROJECT_ROOT = tmp_path
        _RUNNING_SESSIONS_LOCK = threading.Lock()
        _RUNNING_SESSION_IDS = set()
        _SESSION_ACTIVE_TURN_IDS = {}
        _CHAT_STATE_LOCK = _TrackingLock()

        def __init__(self):
            self.reconcile_lock_states: list[bool] = []

        def reconcile_stale_chat_turn_work_runs(self):
            self.reconcile_lock_states.append(self._CHAT_STATE_LOCK.held)

        @staticmethod
        def load_session_chat_state(_project_root, _session_id):
            return None

    service = _SessionService()
    monkeypatch.setattr(session_turn_diagnostics, "_service", lambda: service)

    snapshot = session_turn_diagnostics.get_session_turn_completion_snapshot("session-a", "turn-a")

    assert service.reconcile_lock_states == [False]
    assert snapshot["completionSource"] == "missing_conversation"


def test_session_turn_error_preserves_deprecated_parameter_reason_after_prefix_normalization():
    from core.web.services import session_service

    raw_error = "provider_protocol_error: invalid_request_error: `temperature` is deprecated for this model."
    turn_error = session_service._make_session_turn_error(raw_error, lang="zh")

    assert turn_error["error_type"] == "provider_error"
    assert turn_error["reason_code"] == "deprecated_sampling_parameter"
    assert "模型不接受当前采样参数，例如 temperature" in turn_error["message"]
    assert "`temperature` is deprecated for this model." in turn_error["message"]


@pytest.mark.parametrize(
    "raw_error",
    [
        "provider_error: unknown failure",
        "not_invalid_request_error: unknown failure",
        "invalid_request_error_suffix: unknown failure",
        "worker_gone: invalid_request_error: worker process exited",
    ],
)
def test_provider_text_recognition_keeps_unknown_and_lifecycle_errors_out(raw_error):
    from core.web.services import session_service

    assert session_service._looks_like_provider_error_text(raw_error) is False
    summary = session_service._user_visible_failure_summary(raw_error, lang="zh")
    assert "网页工作台这一轮执行失败" in summary


def test_session_turn_error_uses_nested_provider_balance_reason_over_wrapper_protocol_marker():
    from core.web.services import session_service

    raw_error = (
        "provider_protocol_error: litellm.BadRequestError: BadRequestError: OpenAIException - "
        "b'{\"error\":{\"message\":\"Insufficient account balance\","
        "\"type\":\"insufficient_balance\"},\"type\":\"error\"}'"
    )

    turn_error = session_service._make_session_turn_error(raw_error, lang="zh")

    assert turn_error["error_type"] == "provider_error"
    assert turn_error["reason_code"] == "quota_exhausted"
    assert turn_error["provider_error_type"] == "insufficient_balance"
    assert turn_error["provider_error_message"] == "Insufficient account balance"
    assert turn_error["reason_detail"] == "Insufficient account balance"
    assert "账户余额不足" in turn_error["reason_summary"]
    assert "账户余额不足" in turn_error["message"]
    assert "重复的工具调用 id" not in turn_error["message"]


@pytest.mark.parametrize(
    ("provider_error_type", "provider_message", "expected_reason_code"),
    [
        ("authentication_error", "Invalid API key", "auth_failed"),
        ("insufficient_quota", "You exceeded your quota", "quota_exhausted"),
        ("rate_limit_error", "Too many requests", "rate_limited"),
        ("context_length_exceeded", "maximum context length exceeded", "context_limit"),
    ],
)
def test_session_turn_error_prefers_specific_nested_provider_category(
    provider_error_type,
    provider_message,
    expected_reason_code,
):
    from core.web.services import session_service

    raw_error = (
        "provider_protocol_error: litellm.BadRequestError: BadRequestError: OpenAIException - "
        f"b'{{\"error\":{{\"message\":\"{provider_message}\","
        f"\"type\":\"{provider_error_type}\"}},\"type\":\"error\"}}'"
    )
    turn_error = session_service._make_session_turn_error(raw_error, lang="zh")

    assert turn_error["error_type"] == "provider_error"
    assert turn_error["reason_code"] == expected_reason_code
    assert turn_error["reason_detail"] == provider_message


@pytest.mark.parametrize(
    "raw_error",
    [
        "payload_protocol_error: duplicate tool call id",
        "provider_protocol_error: duplicate tool call id",
    ],
)
def test_session_turn_error_keeps_actual_payload_protocol_error(raw_error):
    from core.web.services import session_service

    turn_error = session_service._make_session_turn_error(raw_error, lang="zh")

    assert turn_error["error_type"] == "provider_protocol_error"
    assert turn_error["reason_code"] == "provider_protocol_error"
    assert "违反协议" in turn_error["reason_summary"]


@pytest.mark.parametrize(
    "raw_error",
    [
        "provider_protocol_error: HTTP 400 - account balance check failed",
        "provider_protocol_error: account balance unavailable",
    ],
)
def test_session_turn_error_does_not_infer_quota_from_generic_400_or_vague_balance(raw_error):
    from core.web.services import session_service

    reason = session_service._provider_error_user_reason(raw_error, lang="zh")

    assert reason["code"] != "quota_exhausted"


@pytest.mark.parametrize("camel_case", [False, True])
@pytest.mark.parametrize(
    ("lang", "expected_message"),
    [
        ("zh", "本轮已达执行上限，上下文已压缩，发送“继续”可接着处理。"),
        (
            "en",
            'This turn reached its execution limit. Context has been compressed; send "continue" to keep going.',
        ),
    ],
)
def test_session_turn_iteration_limit_is_a_localized_stop_with_diagnostics(
    camel_case, lang, expected_message,
):
    from core.web.services import session_service

    detail = "Iteration 57 reached the continuation limit after compaction 223016 -> 156052."
    failure = {
        "reason_code": "iteration_limit_reached",
        "reason_summary": "Internal iteration guard stopped the turn",
        "reason_detail": detail,
        "chain_stage": "llm_preflight",
        "event_code": "agent.iteration_limit_reached",
        "trace_id": "trace-limit",
        "protocol": "responses",
        "http_status": 503,
        "provider_error_type": "RuntimeError",
        "provider_error_message": detail,
        "provider": "openai",
        "api_base": "https://route.example/v1",
        "model": "gpt-test",
        "retryable": True,
    }
    if camel_case:
        failure = {
            key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:]): value
            for key, value in failure.items()
        }
        failure["baseUrl"] = failure.pop("apiBase")

    turn_error = session_service._make_session_turn_error(
        detail, lang=lang, turn_id="turn-limit", llm_failure=failure,
    )

    assert turn_error["message"] == expected_message
    assert turn_error["reason_summary"] == expected_message
    assert turn_error["reason_code"] == "iteration_limit_reached"
    assert turn_error["reason_detail"] == detail
    assert turn_error["error_type"] == "runtime_error"
    assert turn_error["recoverable"] is True
    assert turn_error["turn_id"] == "turn-limit"
    assert turn_error["chain_stage"] == "llm_preflight"
    assert turn_error["event_code"] == "agent.iteration_limit_reached"
    assert turn_error["trace_id"] == "trace-limit"
    assert turn_error["protocol"] == "responses"
    assert turn_error["provider"] == "openai"
    assert turn_error["provider_host"] == "route.example"
    assert turn_error["model"] == "gpt-test"
    assert turn_error["provider_error_type"] == ""
    assert turn_error["provider_error_message"] == ""
    assert turn_error["http_status"] == 0

    message = session_service._make_turn_error_chat_message(
        turn_error, error_type="runtime_error", turn_id="turn-limit", provider_failure=False,
    )
    assert message["content"] == expected_message
    assert message["metadata"]["reasonDetail"] == detail
    assert message["metadata"]["providerFailure"] is False


def test_iteration_limit_chat_message_keeps_legacy_reason_only_in_diagnostics():
    from core.web.services import session_service

    visible_message = "本轮已达执行上限，上下文已压缩，发送“继续”可接着处理。"
    message = session_service._make_turn_error_chat_message(
        {
            "message": visible_message,
            "reasonCode": "iteration_limit_reached",
            "reasonSummary": "已达到内部迭代保护上限",
            "reasonDetail": "iteration=57",
        },
        error_type="runtime_error",
        turn_id="turn-limit",
        provider_failure=False,
    )

    assert message["content"] == visible_message
    assert message["metadata"]["reasonSummary"] == "已达到内部迭代保护上限"
    assert message["metadata"]["reasonDetail"] == "iteration=57"


@pytest.mark.parametrize("failure", [None, {"reason_code": "context_budget_exhausted"}])
def test_raw_iteration_limit_mention_does_not_override_runtime_or_budget_failure(failure):
    from core.web.services import session_service

    raw_error = "context_budget_exhausted: diagnostic mentions iteration_limit_reached"
    turn_error = session_service._make_session_turn_error(raw_error, lang="zh", llm_failure=failure)

    assert "网页工作台这一轮执行失败" in turn_error["message"]
    assert turn_error["reason_code"] != "iteration_limit_reached"
    if failure:
        assert turn_error["reason_code"] == "context_budget_exhausted"
    assert turn_error["provider_error_message"]


def test_provider_error_mentioning_iteration_limit_keeps_provider_diagnostics():
    from core.web.services import session_service

    raw_error = "provider_protocol_error: litellm.RateLimitError: HTTP 429 mentions iteration_limit_reached"
    turn_error = session_service._make_session_turn_error(
        raw_error,
        lang="zh",
        llm_failure={"reason_code": "rate_limited", "http_status": 429, "provider_error_type": "rate_limit_error"},
    )

    assert turn_error["error_type"] == "provider_error"
    assert turn_error["reason_code"] == "rate_limited"
    assert turn_error["http_status"] == 429
    assert turn_error["provider_error_type"] == "rate_limit_error"
    assert "iteration_limit_reached" in turn_error["provider_error_message"]
    assert "模型服务上游暂时失败" in turn_error["message"]
