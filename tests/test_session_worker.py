"""Focused tests for session worker slice."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from core.infrastructure.event_bus import EventBus, EventNames
from core.logging.trace_context import (
    bind_trace_context,
    get_current_trace_context,
    new_trace_context,
)
from core.web.services import session_service
from core.web.services.session import stream_capture, worker


def test_facade_reexports_worker_entrypoints() -> None:
    assert session_service._run_session_turn is worker._run_session_turn
    assert session_service._run_session_continuation_loop is worker._run_session_continuation_loop
    assert (
        session_service._session_context_allows_internal_auto_continue
        is worker._session_context_allows_internal_auto_continue
    )


def test_internal_auto_continue_context_helpers() -> None:
    assert worker._session_context_allows_internal_auto_continue({}) is False
    assert worker._session_context_allows_internal_auto_continue(
        {"allow_internal_auto_continue": True}
    ) is True
    assert worker._session_context_internal_auto_continue_max_turns({}) == 3
    assert worker._session_context_internal_auto_continue_max_turns(
        {"max_internal_auto_continue_turns": 7}
    ) == 7


def test_research_project_agent_task_gets_bounded_internal_continuation() -> None:
    context = {
        "user_message_source": "agent_inbox",
        "message_metadata": {"kind": "research_project_agent_task"},
    }

    assert worker._session_context_allows_internal_auto_continue(context) is True
    assert (
        worker._session_context_internal_auto_continue_max_turns(context)
        == session_service.SOURCE_COLLECTION_STAGE_TASK_AUTO_CONTINUE_MAX_TURNS
    )


def test_ordinary_agent_inbox_does_not_gain_internal_continuation() -> None:
    context = {
        "user_message_source": "agent_inbox",
        "message_metadata": {"kind": "agent_inbox_message"},
    }

    assert worker._session_context_allows_internal_auto_continue(context) is False
    assert (
        worker._session_context_internal_auto_continue_max_turns(context)
        == session_service.INTERNAL_AUTO_CONTINUE_MAX_TURNS
    )


def test_receipt_context_accepts_binding_without_research_project_id(
    monkeypatch,
) -> None:
    task = {
        "taskId": "task-1",
        "sessionId": "session-1",
        "researchProjectId": "project-1",
        "turn": {"turnId": "turn-1"},
        "modelInvocationReceiptBinding": {
            "questionStage": "generation",
            "questionId": "SCI-096",
            "questionRunId": "run-1",
            "workflowRunId": "run-1",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "v2.1",
            "formalNodeId": "hypothesis_design",
            "formalNodeRunId": "node-run-1",
            "formalNodeAttempt": 1,
            "taskId": "task-1",
            "sessionId": "session-1",
            "turnId": "turn-1",
            "modelPolicySha256": "a" * 64,
            "outcomeKinds": ["candidate"],
        },
        "challengeTaskContract": {
            "questionId": "SCI-096",
            "workflowRunId": "run-1",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "v2.1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-run-1",
            "nodeAttempt": 1,
            "modelPolicySha256": "a" * 64,
            "effectiveRoute": {
                "modelRef": "default/qwen-alias",
                "providerId": "default",
                "modelId": "qwen-plus",
            },
        },
    }
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks._read_research_project_agent_task_record",
        lambda *_args, **_kwargs: task,
    )

    context = worker._model_invocation_receipt_context(
        {
            "message_metadata": {
                "teamId": "team-1",
                "researchProjectId": "project-1",
                "taskId": "task-1",
            }
        },
        session_id="session-1",
        turn_id="turn-1",
    )

    assert context is not None
    assert context["teamId"] == "team-1"
    assert context["questionStageBinding"]["formalNodeRunId"] == "node-run-1"
    assert context["modelPolicySha256"] == "a" * 64
    assert context["expectedModelRoute"]["modelRef"] == "default/qwen-alias"


def test_challenge_receipt_sink_enqueues_durable_registry_intent(monkeypatch) -> None:
    recorded: list[dict] = []
    runtime = SimpleNamespace(store=object())
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.runtime_factory.production_workflow_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.runtime_factory.wake_production_workflow_runtime",
        lambda: recorded.append({"woke": True}) or True,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.receipt_persistence.enqueue_question_model_invocation_receipt",
        lambda store, **kwargs: recorded.append({"store": store, **kwargs})
        or {"created": True},
    )
    capture = stream_capture.SessionTurnCapture(
        session_id="session-1",
        turn_id="turn-1",
        model_invocation_receipt_context={
            "teamId": "team-1",
            "questionStageBinding": {
                "questionId": "SCI-096",
                "workflowRunId": "run-1",
            },
        },
    )
    outcome = SimpleNamespace(model_invocation_receipt={"receiptId": "receipt-1"})

    assert stream_capture._persist_challenge_model_invocation_receipt(capture, outcome) is True
    assert recorded == [
        {
            "store": runtime.store,
            "team_id": "team-1",
            "question_id": "SCI-096",
            "workflow_run_id": "run-1",
            "receipt": {"receiptId": "receipt-1"},
        },
        {"woke": True},
    ]


def test_ordinary_session_does_not_enqueue_challenge_receipt(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.receipt_persistence.enqueue_question_model_invocation_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary chat must not enqueue challenge receipts")
        ),
    )
    capture = stream_capture.SessionTurnCapture(session_id="session-chat", turn_id="turn-chat")
    outcome = SimpleNamespace(model_invocation_receipt={"receiptId": "receipt-chat"})

    assert stream_capture._persist_challenge_model_invocation_receipt(capture, outcome) is False


def test_challenge_receipt_durable_enqueue_failure_marks_formal_turn_fail_closed(
    monkeypatch,
) -> None:
    diagnostics: list[dict] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.runtime_factory.production_workflow_runtime",
        lambda: SimpleNamespace(store=object()),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.receipt_persistence.enqueue_question_model_invocation_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("ledger unavailable")
        ),
    )
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event_quietly",
        lambda component, phase, event_code, **kwargs: diagnostics.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        ),
    )
    capture = stream_capture.SessionTurnCapture(
        session_id="session-1",
        turn_id="turn-1",
        model_invocation_receipt_context={
            "teamId": "team-1",
            "questionStageBinding": {
                "questionId": "SCI-096",
                "workflowRunId": "run-1",
            },
        },
    )
    outcome = SimpleNamespace(model_invocation_receipt={"receiptId": "receipt-1"})

    assert stream_capture._persist_challenge_model_invocation_receipt(capture, outcome) is False
    assert (
        capture.challenge_receipt_failure_code
        == "challenge_receipt_durable_enqueue_failed"
    )
    assert diagnostics[0]["eventCode"] == (
        "challenge_model_invocation_receipt_durable_enqueue_failed"
    )
    assert diagnostics[0]["fields"] == {
        "teamId": "team-1",
        "questionId": "SCI-096",
        "workflowRunId": "run-1",
        "errorType": "OSError",
    }


def test_challenge_receipt_enqueue_failure_never_commits_success_outcome(
    monkeypatch,
) -> None:
    event_bus = EventBus()
    committed: list[object] = []
    monkeypatch.setattr("core.ui.get_ui", lambda: object())
    monkeypatch.setattr(stream_capture, "_ensure_session_ui_capture_hooks", lambda _ui: None)
    monkeypatch.setattr(
        stream_capture,
        "_seed_capture_from_live_feedback_events",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        stream_capture,
        "_commit_session_capture_reasoning_segments",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        stream_capture,
        "_commit_session_capture_assistant_segment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(session_service, "get_event_bus", lambda: event_bus)
    monkeypatch.setattr(session_service, "llm_status_context", lambda **_kwargs: nullcontext())
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        session_service,
        "append_conversation_turn_outcome",
        lambda *_args, **_kwargs: committed.append(_args[-1]),
    )
    monkeypatch.setattr(
        session_service,
        "_invalidate_session_conversation_events_cache",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.runtime_factory.production_workflow_runtime",
        lambda: SimpleNamespace(store=object()),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.receipt_persistence.enqueue_question_model_invocation_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("ledger unavailable")),
    )
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event_quietly",
        lambda *_args, **_kwargs: None,
    )
    capture = stream_capture.SessionTurnCapture(
        session_id="session-1",
        turn_id="turn-1",
        model_invocation_receipt_context={
            "teamId": "team-1",
            "questionStageBinding": {
                "questionId": "SCI-096",
                "workflowRunId": "run-1",
            },
        },
    )
    outcome = SimpleNamespace(model_invocation_receipt={"receiptId": "receipt-1"})

    with stream_capture._capture_session_ui_stream("session-1", capture):
        event_bus.publish(EventNames.LLM_RESPONSE, {"turn_outcome": outcome})

    assert committed == []
    with pytest.raises(RuntimeError, match="challenge_receipt_durable_enqueue_failed"):
        worker._raise_for_challenge_receipt_failure(capture)


def test_receipt_context_rejects_mismatched_project_metadata(monkeypatch) -> None:
    task = {
        "taskId": "task-1",
        "sessionId": "session-1",
        "researchProjectId": "project-authoritative",
        "turn": {"turnId": "turn-1"},
        "modelInvocationReceiptBinding": {},
    }
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks._read_research_project_agent_task_record",
        lambda *_args, **_kwargs: task,
    )

    assert (
        worker._model_invocation_receipt_context(
            {
                "message_metadata": {
                    "teamId": "team-1",
                    "researchProjectId": "project-client",
                    "taskId": "task-1",
                }
            },
            session_id="session-1",
            turn_id="turn-1",
        )
        is None
    )


def test_run_session_turn_binds_child_trace_span_and_restores_context(monkeypatch) -> None:
    root = new_trace_context(request_id="worker-request")
    observed: list[tuple[dict, object]] = []

    def fake_impl(context: dict) -> None:
        observed.append((dict(context), get_current_trace_context()))

    monkeypatch.setattr(worker, "_run_session_turn_impl", fake_impl)

    outer = new_trace_context(request_id="outer-request")
    with bind_trace_context(outer):
        worker._run_session_turn({"trace_context_carrier": root.to_carrier()})
        assert get_current_trace_context() is outer

    assert observed
    child_context, bound = observed[0]
    assert bound is not None
    assert bound.trace_id == root.trace_id
    assert bound.parent_span_id == root.span_id
    assert bound.span_id != root.span_id
    assert child_context["trace_context_carrier"] == bound.to_carrier()
    assert get_current_trace_context() is None


def test_run_session_turn_skips_stale_turn(monkeypatch) -> None:
    """Stale turn_id must exit without running agent."""

    calls: list[str] = []

    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: False)
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda *args, **kwargs: calls.append("lifecycle"),
    )
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_result",
        lambda *args, **kwargs: calls.append("persist"),
    )

    worker._run_session_turn(
        {
            "session_id": "worker-s1",
            "turn_id": "stale-turn",
            "user_message": "hello",
        }
    )
    assert "lifecycle" in calls
    assert "persist" not in calls


def test_run_session_turn_aborts_prepare_when_stop_already_requested(monkeypatch) -> None:
    """A user stop during prepare must not wait for agent context / prompt snapshot."""

    calls: list[str] = []
    control = session_service.SessionTurnControl(session_id="worker-s1", turn_id="turn-stop")
    control.request_stop("operator requested stop")

    class _Decision:
        effective_enabled = False

    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: True)
    monkeypatch.setattr(session_service, "_normalize_optional_bool", lambda value: False)
    monkeypatch.setattr(session_service, "resolve_feature_decision", lambda *args, **kwargs: _Decision())
    monkeypatch.setattr(
        session_service,
        "_ensure_session_workspace",
        lambda *args, **kwargs: calls.append("workspace") or (_ for _ in ()).throw(AssertionError("prepare continued")),
    )
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_result",
        lambda *args, **kwargs: calls.append("persist"),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: calls.append(str(phase)),
    )
    monkeypatch.setattr(
        session_service,
        "_ensure_session_turn_terminal_fallback",
        lambda *args, **kwargs: calls.append("fallback"),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_execution_registry_event",
        lambda *args, **kwargs: calls.append("registry"),
    )
    monkeypatch.setattr(
        session_service,
        "_set_session_running",
        lambda *args, **kwargs: calls.append("running_cleared"),
    )
    monkeypatch.setattr(
        session_service,
        "_clear_session_turn_control",
        lambda *args, **kwargs: calls.append("control_cleared"),
    )
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda *args, **kwargs: calls.append("published"),
    )

    worker._run_session_turn(
        {
            "session_id": "worker-s1",
            "turn_id": "turn-stop",
            "turn_control": control,
            "user_message": "hello",
        }
    )

    assert "workspace" not in calls
    assert "persist" in calls
    assert "stop_observed" in calls
    assert "worker_finished" in calls
    assert "running_cleared" in calls


def test_run_session_turn_aborts_when_prepare_context_interrupted(monkeypatch):
    from pathlib import Path

    from core.orchestration.context_engine import AgentContextInterrupted

    calls: list[str] = []
    control = session_service.SessionTurnControl(session_id="worker-s1", turn_id="turn-stop")

    class _Decision:
        effective_enabled = False

    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: True)
    monkeypatch.setattr(session_service, "_normalize_optional_bool", lambda value: False)
    monkeypatch.setattr(session_service, "resolve_feature_decision", lambda *args, **kwargs: _Decision())
    monkeypatch.setattr(session_service, "_ensure_session_workspace", lambda *args, **kwargs: Path("."))
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "get_agent", lambda *args, **kwargs: {"agentId": "agent-1"})
    monkeypatch.setattr(session_service, "_supervised_role_for_runtime_context", lambda *args, **kwargs: "")
    monkeypatch.setattr(session_service, "_supervised_runtime_tool_grants_for_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_ensure_session_agent_prompt_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(session_service, "_render_agent_prompt_snapshot_block", lambda *args, **kwargs: "")
    monkeypatch.setattr(session_service, "_normalize_message_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        session_service,
        "_lightweight_chat_payload_decision",
        lambda *args, **kwargs: (False, "unified_conversation_chain"),
    )

    def fake_build(*args, **kwargs):
        calls.append("context")
        assert callable(kwargs.get("interrupt_checker"))
        control.request_stop("operator requested stop")
        raise AgentContextInterrupted(
            "operator requested stop",
            stage="prepare_agent_context.group_context_events",
        )

    monkeypatch.setattr(session_service, "build_agent_context", fake_build)
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_result",
        lambda *args, **kwargs: calls.append("persist"),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: calls.append(str(phase)),
    )
    monkeypatch.setattr(
        session_service,
        "_ensure_session_turn_terminal_fallback",
        lambda *args, **kwargs: calls.append("fallback"),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_execution_registry_event",
        lambda *args, **kwargs: calls.append("registry"),
    )
    monkeypatch.setattr(
        session_service,
        "_set_session_running",
        lambda *args, **kwargs: calls.append("running_cleared"),
    )
    monkeypatch.setattr(
        session_service,
        "_clear_session_turn_control",
        lambda *args, **kwargs: calls.append("control_cleared"),
    )
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda *args, **kwargs: calls.append("published"),
    )
    monkeypatch.setattr(
        session_service,
        "evaluate_agent_workspace_write",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prepare continued after interrupt")),
    )

    worker._run_session_turn(
        {
            "session_id": "worker-s1",
            "turn_id": "turn-stop",
            "turn_control": control,
            "agent_id": "agent-1",
            "user_message": "hello",
        }
    )

    assert "context" in calls
    assert "persist" in calls
    assert "stop_observed" in calls
    assert "worker_finished" in calls
    assert "running_cleared" in calls


def test_turn_llm_usage_tokens_extracts_provider_usage() -> None:
    assert worker._turn_llm_usage_tokens(
        {"llm_usage": {"input_tokens": 80, "output_tokens": 40}}
    ) == 120
    assert worker._turn_llm_usage_tokens(
        {"llm_usage": {"inputTokens": 80, "outputTokens": 40}}
    ) == 120
    assert worker._turn_llm_usage_tokens({"llm_usage": {"total_tokens": 70}}) == 70
    assert worker._turn_llm_usage_tokens({"llm_usage": {"source": "missing"}}) == 0
    assert worker._turn_llm_usage_tokens({"status": "completed"}) == 0
    assert worker._turn_llm_usage_tokens(None) == 0
    # Booleans are not token counts and must not poison the accumulator.
    assert worker._turn_llm_usage_tokens(
        {"llm_usage": {"input_tokens": True, "output_tokens": 3}}
    ) == 3


def test_session_turn_token_budget_line_prefers_task_budget_request(monkeypatch) -> None:
    class _FakeStore:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_run(self, run_id: str):
            assert run_id == "run-1"
            return {
                "nodeRuns": [
                    {
                        "nodeRunId": "node-run-1",
                        "budgetLedgerRef": "reservation-node-run-1",
                    }
                ],
                "budgetReservations": [
                    {
                        "reservationId": "reservation-node-run-1",
                        "requested": {"tokens": 123456, "toolCalls": 4},
                    },
                ],
            }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.store.WorkflowRunStore",
        _FakeStore,
    )

    assert worker._session_turn_token_budget_line(
        {
            "message_metadata": {
                "workflowRunId": "run-1",
                "nodeRunId": "node-run-1",
            }
        }
    ) == (123456, "task_budget_request")


def test_session_turn_token_budget_line_falls_back_to_session_default(monkeypatch) -> None:
    assert worker.DEFAULT_SESSION_TOKEN_BUDGET == 2_000_000
    assert worker._session_turn_token_budget_line({}) == (
        worker.DEFAULT_SESSION_TOKEN_BUDGET,
        "session_default",
    )
    assert worker._session_turn_token_budget_line(
        {"message_metadata": {"workflowRunId": "run-1"}}
    ) == (worker.DEFAULT_SESSION_TOKEN_BUDGET, "session_default")

    class _BrokenStore:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_run(self, run_id: str):
            raise OSError("missing workflow run record")

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.store.WorkflowRunStore",
        _BrokenStore,
    )
    assert worker._session_turn_token_budget_line(
        {
            "message_metadata": {
                "workflowRunId": "run-1",
                "nodeRunId": "node-run-1",
            }
        }
    ) == (worker.DEFAULT_SESSION_TOKEN_BUDGET, "session_default")


def test_continuation_loop_stops_when_token_budget_exhausted(tmp_path, monkeypatch) -> None:
    """Cumulative usage crossing the fuse line must stop the turn gracefully."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    monkeypatch.setattr(
        worker, "_session_turn_token_budget_line", lambda _context: (100, "session_default")
    )
    lifecycle_events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append((str(phase), dict(kwargs))),
    )
    calls: list[int] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        calls.append(1)
        return {
            "status": "completed",
            "summary": "仍在推进，尚未收口。",
            "raw_output": "仍在推进，尚未收口。",
            "outcome": "progress",
            "tool_call_count": 1,
            "tool_trace": [{"name": "task_update_tool", "status": "done", "summary": "progress"}],
            "llm_usage": {"input_tokens": 80, "output_tokens": 40},
        }

    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)

    turn_control = session_service._create_session_turn_control("session-token-fuse")
    try:
        result = worker._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-token-fuse",
            turn_control=turn_control,
            initial_prompt="开始长任务",
            history_messages=[],
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=5,
        )
    finally:
        session_service._clear_session_turn_control("session-token-fuse", turn_id=turn_control.turn_id)

    assert len(calls) == 1
    assert isinstance(result, dict)
    assert result["status"] == "paused_limit"
    assert result["metadata"]["continuation_pause_reason"] == "token_budget_exhausted"
    assert result["metadata"]["continuation_limit_reached"] is True
    fused_events = [
        fields
        for phase, kwargs in lifecycle_events
        if phase == "followup_prompt_blocked"
        for fields in [kwargs.get("fields") or {}]
    ]
    assert any(
        fields.get("reason") == "token_budget_exhausted"
        and fields.get("cumulativeSessionTokens") == 120
        and fields.get("tokenBudgetLine") == 100
        and fields.get("tokenBudgetSource") == "session_default"
        for fields in fused_events
    )


def test_continuation_loop_unaffected_below_token_budget(tmp_path, monkeypatch) -> None:
    """Usage below the default line must not alter the loop's normal flow."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    calls: list[int] = []

    def fake_run_existing_agent_single_turn(agent, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {
                "status": "completed",
                "summary": "仍在推进，尚未收口。",
                "raw_output": "仍在推进，尚未收口。",
                "outcome": "progress",
                "tool_call_count": 1,
                "tool_trace": [{"name": "task_update_tool", "status": "done", "summary": "progress"}],
                "llm_usage": {"input_tokens": 30, "output_tokens": 20},
            }
        return {
            "status": "completed",
            "summary": "结论：任务已完成。",
            "raw_output": "结论：任务已完成。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
            "llm_usage": {"input_tokens": 40, "output_tokens": 10},
        }

    monkeypatch.setattr(session_service, "run_existing_agent_single_turn", fake_run_existing_agent_single_turn)

    turn_control = session_service._create_session_turn_control("session-token-under")
    try:
        # No budgetRequest metadata in the context: the conservative default
        # line must apply and stay far above this loop's small usage.
        result = worker._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-token-under",
            turn_control=turn_control,
            initial_prompt="开始任务",
            history_messages=[],
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=5,
        )
    finally:
        session_service._clear_session_turn_control("session-token-under", turn_id=turn_control.turn_id)

    assert len(calls) == 2
    assert isinstance(result, dict)
    assert result["status"] == "completed"
    assert result["metadata"].get("continuation_pause_reason") is None
    assert result["metadata"].get("continuation_limit_reached") is None


_UNIFIED_HISTORY = [
    {"role": "user", "content": "任务背景：搜集量子纠错方向的近期文献"},
    {"role": "assistant", "content": "已记录任务背景，等待执行。"},
]


class _TerminalLifecycleWipeAgent:
    """Mimic the real chat agent protocol, including the terminal wipe.

    A real chat agent that ends an iteration through its terminal lifecycle
    (``turn_complete`` carryover) clears ``_active_turn_messages`` before the
    session worker dispatches the next internal continuation iteration.
    """

    def __init__(self, *, wipe_after_first_run: bool = True) -> None:
        self.wipe_after_first_run = wipe_after_first_run
        self.seed_calls: list[list[dict]] = []
        self.fingerprints: list[str] = []
        self.static_seeds: list[str] = []
        self.volatile_seeds: list[str] = []
        self.context_present_at_run: list[bool] = []
        self.run_calls = 0
        self._active_messages: list[dict] = []
        self._wiped = False

    def set_turn_identity(self, turn_identity: str) -> None:
        return None

    def seed_chat_history(self, messages) -> None:
        self.seed_calls.append(list(messages or []))
        self._active_messages = list(messages or [])
        self._wiped = False

    def seed_chat_history_ledger_fingerprint(self, fingerprint: str) -> None:
        self.fingerprints.append(str(fingerprint or ""))

    def seed_static_runtime_context(self, block: str) -> None:
        self.static_seeds.append(str(block or ""))

    def seed_volatile_runtime_context(self, block: str) -> None:
        self.volatile_seeds.append(str(block or ""))

    def export_turn_carryover(self) -> dict:
        if self._wiped:
            return {
                "messages": [],
                "goal": "",
                "turnIdentity": "turn-wiped",
                "terminal": True,
            }
        if not self._active_messages:
            return {}
        return {
            "messages": list(self._active_messages),
            "goal": "任务背景",
            "turnIdentity": "turn-live",
            "terminal": False,
        }

    def run_single_turn(self, initial_prompt=None, **_kwargs):
        self.run_calls += 1
        self.context_present_at_run.append(bool(self._active_messages))
        if self.run_calls == 1:
            if self.wipe_after_first_run:
                # Terminal lifecycle: the conversation context is dropped.
                self._wiped = True
                self._active_messages = []
            return {
                "status": "completed",
                "summary": "仍在推进，尚未收口。",
                "raw_output": "仍在推进，尚未收口。",
                "outcome": "progress",
                "tool_call_count": 1,
                "tool_trace": [{"name": "task_update_tool", "status": "done", "summary": "progress"}],
            }
        return {
            "status": "completed",
            "summary": "结论：任务已完成。",
            "raw_output": "结论：任务已完成。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        }


def _run_two_iteration_continuation_loop(agent, tmp_path, monkeypatch, **loop_kwargs):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    monkeypatch.setattr(
        worker, "_session_turn_token_budget_line", lambda _context: (10_000_000, "session_default")
    )
    turn_control = session_service._create_session_turn_control("session-terminal-carryover")
    try:
        return worker._run_session_continuation_loop(
            agent,
            context={},
            session_id="session-terminal-carryover",
            turn_control=turn_control,
            initial_prompt="开始资料搜集阶段任务",
            history_messages=list(_UNIFIED_HISTORY),
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=3,
            **loop_kwargs,
        )
    finally:
        session_service._clear_session_turn_control(
            "session-terminal-carryover", turn_id=turn_control.turn_id
        )


def test_continuation_loop_reseeds_unified_history_after_terminal_context_wipe(
    tmp_path, monkeypatch
) -> None:
    """A follow-up carryover after a terminal context wipe must not go out bare.

    The real chat agent clears its in-memory conversation when an iteration
    ends through the terminal lifecycle. The next internal continuation
    iteration must then be re-seeded through the same unified ledger assembly
    (history + provenance stamp) instead of dispatching an isolated prompt.
    """

    agent = _TerminalLifecycleWipeAgent(wipe_after_first_run=True)
    result = _run_two_iteration_continuation_loop(agent, tmp_path, monkeypatch)

    assert agent.run_calls == 2
    assert agent.context_present_at_run == [True, True]
    assert len(agent.seed_calls) == 2
    assert agent.seed_calls[0] == _UNIFIED_HISTORY
    assert agent.seed_calls[1] == _UNIFIED_HISTORY
    assert len(agent.fingerprints) == 2
    assert agent.fingerprints[0]
    assert agent.fingerprints[0] == agent.fingerprints[1]
    assert isinstance(result, dict)
    assert result["status"] == "completed"


def test_continuation_loop_keeps_in_memory_context_without_reseed(tmp_path, monkeypatch) -> None:
    """When the agent still holds same-turn context, the loop must not re-seed.

    Re-seeding a live in-memory continuation would replace it with the pre-turn
    ledger view and drop the in-flight run, so the loop must keep passing no
    chat history while the agent context stays present.
    """

    agent = _TerminalLifecycleWipeAgent(wipe_after_first_run=False)
    result = _run_two_iteration_continuation_loop(agent, tmp_path, monkeypatch)

    assert agent.run_calls == 2
    assert agent.context_present_at_run == [True, True]
    assert len(agent.seed_calls) == 1
    assert len(agent.fingerprints) == 1
    assert isinstance(result, dict)
    assert result["status"] == "completed"


def test_continuation_loop_reseeds_runtime_context_blocks_with_history(tmp_path, monkeypatch) -> None:
    """The re-seed must restore the host runtime context lost with the wipe."""

    agent = _TerminalLifecycleWipeAgent(wipe_after_first_run=True)
    _run_two_iteration_continuation_loop(
        agent,
        tmp_path,
        monkeypatch,
        static_runtime_context_block="## 静态运行上下文",
        volatile_runtime_context_block="## 本轮易变上下文",
    )

    assert agent.static_seeds == ["## 静态运行上下文"]
    assert agent.volatile_seeds == ["## 本轮易变上下文"]
