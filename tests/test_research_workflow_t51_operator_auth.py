"""T5.1-6 RED: server operator authorization, not client self-declaration."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    CommandForbiddenError,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _cancel_request(*, actor: ActorRef) -> CommandRequest:
    return CommandRequest(
        command_id="cmd-cancel-auth",
        run_id="run-test",
        team_id="research-team",
        command=WorkflowCommandKind.CANCEL_RUN,
        node_id=None,
        expected_run_version=1,
        idempotency_key="ui:cancel-auth",
        payload={"reason": "stop"},
        requested_by=actor,
        requested_at_ms=FIXED_NOW_MS,
    )


def test_client_body_operator_without_server_context_is_forbidden(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        # Body claims operator, but no server context is bound.
        forged = _cancel_request(actor=ActorRef("operator", "client-forged"))
        with pytest.raises(CommandForbiddenError):
            harness.command_service.submit(forged)
    finally:
        harness.close()


def test_anonymous_operator_is_forbidden(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        with server_operator_scope(""):
            with pytest.raises(CommandForbiddenError):
                harness.command_service.submit(
                    _cancel_request(actor=ActorRef("operator", "x"))
                )
    finally:
        harness.close()


def test_server_context_authorizes_high_impact_command(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        # Body may still carry a placeholder; authority is the server context.
        request = _cancel_request(actor=ActorRef("user", "operator-server-1"))
        with server_operator_scope("operator-server-1"):
            receipt = harness.command_service.submit(request)
        assert receipt.status == "accepted"
        run = harness.store.get_run("run-test")
        assert run is not None and run.status == "cancelled"
    finally:
        harness.close()
