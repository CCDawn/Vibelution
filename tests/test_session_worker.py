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
from core.web.services.session import stream_capture, submit, worker


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


def test_challenge_deadline_is_executor_ephemeral_and_continuation_safe() -> None:
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
        challenge_task_deadline_scope,
    )

    continuation_metadata = {
        "sourceSurface": "team_workflow_agent_turn_continuation",
        "workflowRunId": "run-1",
        "nodeRunId": "node-1",
    }
    with challenge_task_deadline_scope(1_000):
        expected_deadline = 1_000 + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
        assert (
            submit._challenge_deadline_at_ms_for_submit(continuation_metadata)
            == expected_deadline
        )
        assert (
            submit._challenge_deadline_at_ms_for_submit(
                {"kind": "research_project_agent_task", **continuation_metadata}
            )
            == expected_deadline
        )

    assert submit._challenge_deadline_at_ms_for_submit(continuation_metadata) is None
    assert submit._challenge_deadline_at_ms_for_submit(
        {"kind": "research_project_agent_task"}
    ) is None


def test_source_stage_deadline_uses_canonical_task_contract(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        challenge_task_deadline_scope,
    )
    from core.web.services.team_workflow.source_collection import stage_session

    monkeypatch.setattr(
        stage_session,
        "_read_source_collection_stage_session_task_record",
        lambda team_id, task_id: {
            "taskId": task_id,
            "teamId": team_id,
            "challengeTaskContract": {
                "workflowRunId": "workflow-1",
                "nodeRunId": "node-1",
            },
        },
    )
    metadata = {
        "kind": "source_collection_stage_session_task",
        "teamId": "team-1",
        "sourceCollectionStageTaskId": "stage-task-1",
        # The initial stage message intentionally has no generic node fields.
    }
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
    )

    with challenge_task_deadline_scope(1_000):
        assert (
            submit._challenge_deadline_at_ms_for_submit(metadata)
            == 1_000 + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
        )


def test_source_stage_deadline_does_not_trust_message_contract(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        challenge_task_deadline_scope,
    )
    from core.web.services.team_workflow.source_collection import stage_session

    monkeypatch.setattr(
        stage_session,
        "_read_source_collection_stage_session_task_record",
        lambda *_args: None,
    )
    metadata = {
        "kind": "source_collection_stage_session_task",
        "teamId": "team-1",
        "sourceCollectionStageTaskId": "stage-task-1",
        "challengeTaskContract": {
            "workflowRunId": "forged-workflow",
            "nodeRunId": "forged-node",
        },
    }
    with challenge_task_deadline_scope(1_000):
        assert submit._challenge_deadline_at_ms_for_submit(metadata) is None


def test_challenge_deadline_checker_isolated_from_ordinary_chat() -> None:
    assert worker._challenge_deadline_stop_reason(
        300_000,
        turn_id="turn-1",
        now_ms=299_999,
    ) == ""
    assert worker._challenge_deadline_stop_reason(
        300_000,
        turn_id="turn-1",
        now_ms=300_001,
    ) == "challenge_logical_task_deadline_exhausted"
    assert worker._challenge_deadline_stop_reason(
        None,
        turn_id="ordinary-chat",
        now_ms=999_999,
    ) == ""


def test_challenge_deadline_cancel_is_not_provider_retry_failure() -> None:
    class CancelledError(Exception):
        category = "cancelled"

    class ProviderError(Exception):
        category = "provider_error"

    cancelled = CancelledError("cancelled")
    assert worker._is_challenge_deadline_cancelled(
        {"_challenge_task_deadline_at_ms": 1},
        cancelled,
        turn_id="turn-expired",
    ) is True
    assert worker._is_challenge_deadline_cancelled(
        {"_challenge_task_deadline_at_ms": 9_999_999_999_999},
        cancelled,
        turn_id="turn-live",
    ) is False
    provider_error = ProviderError("provider failed")
    assert worker._is_challenge_deadline_cancelled(
        {"_challenge_task_deadline_at_ms": 1},
        provider_error,
        turn_id="turn-expired",
    ) is False


@pytest.mark.parametrize(
    ("error_category", "expected_persistence"),
    [("cancelled", "stopped"), ("provider_error", "failure")],
)
def test_run_session_turn_impl_routes_provider_error_by_category(
    monkeypatch,
    tmp_path,
    error_category: str,
    expected_persistence: str,
) -> None:
    """Only deadline-triggered provider cancellation uses stopped persistence."""

    from pathlib import Path

    from core.llm.types import LLMError

    calls: list[str] = []
    lifecycle: list[tuple[str, dict]] = []
    control = session_service.SessionTurnControl(session_id="session-1", turn_id="turn-1")
    context = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_control": control,
        "user_message": "run challenge task",
        "_challenge_task_deadline_at_ms": 1,
    }

    class _Decision:
        effective_enabled = False

    class _Assembly:
        def __init__(self) -> None:
            self.history_messages: list[dict] = []
            self.events: list = []
            self.included_event_ids: list[str] = []
            self.omitted_event_count = 0
            self.checkpoint_event_id = ""

        @staticmethod
        def to_composition_patch() -> dict:
            return {}

    runtime_agent = SimpleNamespace()

    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *_args: True)
    monkeypatch.setattr(session_service, "_normalize_optional_bool", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "resolve_feature_decision", lambda *_args, **_kwargs: _Decision())
    monkeypatch.setattr(session_service, "_ensure_session_workspace", lambda *_args: tmp_path)
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(session_service, "_supervised_role_for_runtime_context", lambda *_args: "")
    monkeypatch.setattr(session_service, "_supervised_runtime_tool_grants_for_context", lambda *_args: None)
    monkeypatch.setattr(session_service, "_supervised_workspace_override_path", lambda *_args: None)
    monkeypatch.setattr(session_service, "_normalize_message_attachments", lambda *_args: [])
    monkeypatch.setattr(
        session_service,
        "_lightweight_chat_payload_decision",
        lambda *_args, **_kwargs: (False, "unified_conversation_chain"),
    )
    monkeypatch.setattr(session_service, "sync_llm_key_env_from_persisted_user_env", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(session_service, "_source_collection_stage_task_context_metadata", lambda *_args: {})
    monkeypatch.setattr(session_service, "_source_collection_stage_task_required_tool_names", lambda *_args: [])
    monkeypatch.setattr(session_service, "_session_task_workspace_for_turn", lambda *_args, **_kwargs: Path(tmp_path))
    monkeypatch.setattr(session_service, "_session_tool_workspace_override", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(session_service, "active_agent_runtime", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(session_service, "mental_model_enabled_override", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        session_service,
        "_acquire_chat_agent_for_session",
        lambda *_args, **_kwargs: (runtime_agent, {}),
    )
    monkeypatch.setattr(session_service, "_capture_session_ui_stream", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(session_service, "_history_messages_for_agent_seed", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda *_args: [])
    monkeypatch.setattr(session_service, "assemble_conversation_context", lambda *_args, **_kwargs: _Assembly())
    monkeypatch.setattr(session_service, "_session_context_segments_without_prompt_template", lambda *_args: [])
    monkeypatch.setattr(session_service, "_prompt_snapshot_context_segment", lambda *_args: None)
    monkeypatch.setattr(session_service, "_session_context_segments_block", lambda *_args: "")
    monkeypatch.setattr(session_service, "_recent_session_guidance_context_block", lambda *_args: "")
    monkeypatch.setattr(session_service, "_skill_runtime_context_from_invocation", lambda *_args: "")
    monkeypatch.setattr(session_service, "refresh_active_skill_contract_status", lambda value: value)
    monkeypatch.setattr(session_service, "_active_skill_runtime_context_from_contract", lambda *_args: "")
    monkeypatch.setattr(session_service, "_build_last_context_composition", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(session_service, "_append_session_conversation_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_set_session_live_context_composition", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_session_workspace_relative_path", lambda *_args: "session-1")
    monkeypatch.setattr(session_service, "_session_prompt_cache_partition", lambda *_args, **_kwargs: "partition")
    monkeypatch.setattr(session_service, "_session_prompt_cache_scope", lambda *_args, **_kwargs: "chat_session")
    monkeypatch.setattr(session_service, "_session_prompt_cache_log_fields", lambda **_kwargs: {})
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda _sid, phase, **kwargs: lifecycle.append((phase, kwargs)))
    monkeypatch.setattr(session_service, "_record_session_execution_registry_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_turn_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_set_session_turn_progress_live_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_set_session_model_thinking_live_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_get_turn_control_stop_reason", lambda *_args: "")
    monkeypatch.setattr(session_service, "_get_session_stop_reason", lambda *_args: "")
    monkeypatch.setattr(worker, "build_research_thinking_budget_segment", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        worker,
        "_run_session_continuation_loop",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LLMError(error_category, "provider outcome", retryable=False)
        ),
    )
    monkeypatch.setattr(worker, "_wait_for_tool_execution_quiescence", lambda *_args: None)
    monkeypatch.setattr(worker, "_finish_session_turn_worker", lambda *_args: None)
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_result",
        lambda *_args, **_kwargs: calls.append("stopped"),
    )
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_failure",
        lambda *_args, **_kwargs: calls.append("failure"),
    )

    worker._run_session_turn_impl(context)

    assert calls == [expected_persistence]
    assert not [phase for phase, _kwargs in lifecycle if phase == "user_visible_finished"]
    exception_events = [kwargs for phase, kwargs in lifecycle if phase == "exception"]
    assert exception_events
    if error_category == "cancelled":
        assert exception_events[-1]["outcome"] == "stopped"
        assert exception_events[-1]["fields"]["reasonCode"] == "challenge_logical_task_deadline_exhausted"
    else:
        assert exception_events[-1]["outcome"] == "failed"
        assert exception_events[-1]["fields"]["reasonCode"] == ""


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


def test_formal_session_turn_uses_emergency_line_not_reservation_remaining(
    monkeypatch,
) -> None:
    receipt_context = {"questionStageBinding": {"workflowRunId": "run-1"}}
    monkeypatch.setattr(
        worker,
        "_challenge_budget_window",
        lambda _context: pytest.fail("soft reservation must not own turn termination"),
    )

    assert worker._session_turn_token_budget_line(receipt_context) == (
        worker.DEFAULT_SESSION_TOKEN_BUDGET,
        "challenge_emergency_default",
    )


def test_session_turn_token_budget_line_keeps_ordinary_chat_default() -> None:
    assert worker.DEFAULT_SESSION_TOKEN_BUDGET == 2_000_000
    assert worker._session_turn_token_budget_line(None) == (
        worker.DEFAULT_SESSION_TOKEN_BUDGET,
        "session_default",
    )


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


def _run_scripted_continuation_results(
    tmp_path,
    monkeypatch,
    results: list[dict],
    *,
    no_progress_limit: int,
):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda _session_id: None,
    )
    monkeypatch.setattr(
        worker,
        "_session_turn_token_budget_line",
        lambda _context: (10_000_000, "session_default"),
    )
    calls: list[int] = []

    def fake_run_existing_agent_single_turn(_agent, **_kwargs):
        calls.append(1)
        return dict(results[len(calls) - 1])

    monkeypatch.setattr(
        session_service,
        "run_existing_agent_single_turn",
        fake_run_existing_agent_single_turn,
    )
    turn_control = session_service._create_session_turn_control(
        "session-no-progress-guard"
    )
    try:
        result = worker._run_session_continuation_loop(
            object(),
            context={},
            session_id="session-no-progress-guard",
            turn_control=turn_control,
            initial_prompt="继续推进正式任务",
            history_messages=[],
            allow_internal_auto_continue=True,
            max_internal_auto_continue_turns=no_progress_limit,
        )
    finally:
        session_service._clear_session_turn_control(
            "session-no-progress-guard",
            turn_id=turn_control.turn_id,
        )
    return calls, result


def test_continuation_no_progress_limit_resets_after_new_successful_tool(
    tmp_path,
    monkeypatch,
) -> None:
    def progressing(tool_call: dict) -> dict:
        return {
            "status": "completed",
            "summary": "仍在推进。",
            "raw_output": "仍在推进。",
            "outcome": "progress",
            "tool_call_count": 1,
            "tool_trace": [tool_call],
        }

    calls, result = _run_scripted_continuation_results(
        tmp_path,
        monkeypatch,
        [
            progressing(
                {
                    "name": "source_writeback_tool",
                    "status": "done",
                    "args": {"result_json": {"batch": 1}},
                    "result": {"recorded": 1},
                }
            ),
            progressing(
                {
                    "name": "source_writeback_tool",
                    "status": "failed",
                    "args": {"payload_json": {"batch": 2}},
                    "errorCode": "unexpected_argument",
                    "error": "unexpected argument: payload_json",
                }
            ),
            progressing(
                {
                    "name": "source_writeback_tool",
                    "status": "done",
                    "args": {"result_json": {"batch": 2}},
                    "result": {"recorded": 2},
                }
            ),
            {
                "status": "completed",
                "summary": "结论：任务已完成。",
                "raw_output": "结论：任务已完成。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            },
        ],
        no_progress_limit=2,
    )

    assert len(calls) == 4
    assert result["status"] == "completed"
    assert result["metadata"]["continuation_turn_count"] == 4
    assert "continuation_limit_reached" not in result["metadata"]


def test_continuation_pauses_only_after_consecutive_repeated_tool_error(
    tmp_path,
    monkeypatch,
) -> None:
    repeated_error = {
        "status": "completed",
        "summary": "参数错误，准备重试。",
        "raw_output": "参数错误，准备重试。",
        "outcome": "progress",
        "tool_call_count": 1,
        "tool_trace": [
            {
                "name": "source_writeback_tool",
                "status": "failed",
                "args": {"payload_json": {"batch": 2}},
                "errorCode": "unexpected_argument",
                "error": "unexpected argument: payload_json",
            }
        ],
    }
    calls, result = _run_scripted_continuation_results(
        tmp_path,
        monkeypatch,
        [repeated_error, repeated_error, repeated_error],
        no_progress_limit=3,
    )

    assert len(calls) == 3
    assert result["status"] == "paused_limit"
    assert result["metadata"]["continuation_pause_reason"] == "runaway_no_progress"
    assert result["metadata"]["continuation_no_progress_count"] == 3
    assert result["metadata"]["continuation_progress_advanced"] is False


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
