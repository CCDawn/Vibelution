"""Focused contract checks for the operator knowledge wait cursor."""

from types import SimpleNamespace

from core.web.services.team_workflow.operator_optimization.knowledge_wait import (
    KnowledgeChildPending,
    _terminal_ready,
)


def test_pending_exception_preserves_exact_child_cursor() -> None:
    error = KnowledgeChildPending("inv-1", "run-child-1")
    assert error.invocation_id == "inv-1"
    assert error.child_run_id == "run-child-1"
    assert "run-child-1" in str(error)


def test_terminal_ready_requires_accepted_handoff_for_success() -> None:
    assert _terminal_ready(SimpleNamespace(status="failed", handoff_state="pending"))
    assert _terminal_ready(SimpleNamespace(status="cancelled", handoff_state="pending"))
    assert _terminal_ready(SimpleNamespace(status="completed", handoff_state="accepted"))
    assert not _terminal_ready(SimpleNamespace(status="completed", handoff_state="pending"))
    assert not _terminal_ready(SimpleNamespace(status="running", handoff_state="accepted"))
