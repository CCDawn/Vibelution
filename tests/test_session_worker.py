"""Focused tests for session worker slice."""

from __future__ import annotations

from core.logging.trace_context import (
    bind_trace_context,
    get_current_trace_context,
    new_trace_context,
)
from core.web.services import session_service
from core.web.services.session import worker


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
    assert context["questionStageBinding"]["formalNodeRunId"] == "node-run-1"
    assert context["modelPolicySha256"] == "a" * 64
    assert context["expectedModelRoute"]["modelRef"] == "default/qwen-plus"


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
