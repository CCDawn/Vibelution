"""P1 RED: operator roles required for high-impact commands."""

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


def _cancel_request() -> CommandRequest:
    return CommandRequest(
        command_id="cmd-cancel-role",
        run_id="run-test",
        team_id="research-team",
        command=WorkflowCommandKind.CANCEL_RUN,
        node_id=None,
        expected_run_version=1,
        idempotency_key="ui:cancel-role",
        payload={"reason": "stop"},
        requested_by=ActorRef("user", "operator-1"),
        requested_at_ms=FIXED_NOW_MS,
    )


def test_operator_without_privileged_role_is_forbidden(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        with server_operator_scope("operator-1", roles=("viewer",)):
            with pytest.raises(CommandForbiddenError):
                harness.command_service.submit(_cancel_request())
    finally:
        harness.close()


def test_operator_with_privileged_role_is_allowed(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        with server_operator_scope("operator-1", roles=("operator",)):
            receipt = harness.command_service.submit(_cancel_request())
        assert receipt.status == "accepted"
    finally:
        harness.close()
