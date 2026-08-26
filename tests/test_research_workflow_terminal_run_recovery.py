"""Terminal formal-run recovery through the governed archive command."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.ledger import RunVersionConflictError
from core.research.workflow.transitions import RunStatus
from core.web.services.team_workflow.research_runtime.command_offers.archive_run import (
    build_archive_run_offer,
)
from core.web.services.team_workflow.research_runtime.command_offers.reconcile_run import (
    build_reconcile_run_offer,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    CommandForbiddenError,
    WorkflowCommandError,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_outbox_record,
    build_run_record,
)


_TERMINAL_STATUSES = (
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
    RunStatus.SUCCEEDED.value,
    RunStatus.RECONCILIATION_REQUIRED.value,
)


def _seed_terminal_run(
    harness: CommandHarness,
    *,
    run_id: str,
    status: str,
    with_pending_outbox: bool = False,
) -> None:
    run = replace(
        build_run_record(
            run_id=run_id,
            status=status,
            run_version=3,
            last_event_sequence=1,
        ),
        completion_kind=("cancelled" if status == RunStatus.CANCELLED.value else "worker"),
        terminal_reason=f"{status} terminal reason",
        completed_at_ms=FIXED_NOW_MS,
    )

    def mutate(uow):
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id=run_id,
                run_version=1,
                event_type="run_created",
                event_id=f"evt-created-{run_id}",
            )
        )
        if with_pending_outbox:
            command_id = f"cmd-seed-{run_id}"
            uow.repository.insert_command(
                build_command_record(
                    command_id=command_id,
                    run_id=run_id,
                    expected_run_version=1,
                    accepted_run_version=1,
                    idempotency_key=f"seed:{run_id}",
                )
            )
            node_run_id = f"nr-{run_id}-source-finding-a1"
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id=node_run_id,
                    run_id=run_id,
                    command_id=command_id,
                    status="failed",
                )
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        action_id=f"act-{run_id}",
                        run_id=run_id,
                        command_id=command_id,
                        action_kind="graph_dispatch",
                    ),
                    node_run_id=node_run_id,
                )
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


@pytest.mark.parametrize("status", _TERMINAL_STATUSES)
def test_archive_offer_is_available_and_confirmation_gated(status: str) -> None:
    run = build_run_record(run_id=f"run-{status}", status=status, run_version=3)

    offer = build_archive_run_offer(run=run)

    assert offer.command is WorkflowCommandKind.ARCHIVE_RUN
    assert offer.available is True
    assert offer.destructive is True
    assert offer.confirmation is not None
    assert offer.confirmation.confirm_label
    assert "归档" in offer.confirmation.body


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.CREATED.value,
        RunStatus.RUNNING.value,
        RunStatus.WAITING_HUMAN.value,
        RunStatus.BLOCKED.value,
        RunStatus.ARCHIVED.value,
    ],
)
def test_archive_offer_does_not_hide_non_terminal_recovery(status: str) -> None:
    run = build_run_record(run_id=f"run-{status}", status=status, run_version=3)

    offer = build_archive_run_offer(run=run)

    assert offer.available is False
    assert offer.blocker_ids == ("archive_not_allowed",)


def test_failed_run_archive_preserves_terminal_facts_cancels_outbox_and_records_event(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_terminal_run(
            harness,
            run_id="run-failed",
            status=RunStatus.FAILED.value,
            with_pending_outbox=True,
        )
        request = harness.request(
            run_id="run-failed",
            command=WorkflowCommandKind.ARCHIVE_RUN,
            node_id=None,
            expected_run_version=3,
            idempotency_key="ui:archive-failed",
            payload={"reason": "清理启动超时"},
        )

        receipt = harness.service.submit(request)

        assert receipt.status == "accepted"
        assert receipt.accepted_run_version == 4
        assert receipt.latest_event_sequence == 2
        run = harness.store.get_run("run-failed")
        assert run is not None
        assert run.status == RunStatus.ARCHIVED.value
        assert run.run_version == 4
        assert run.completion_kind == "worker"
        assert run.terminal_reason == "failed terminal reason"
        assert run.completed_at_ms == FIXED_NOW_MS + 1000
        outbox = harness.store.read(
            lambda repository: repository.get_outbox("act-run-failed")
        )
        assert outbox is not None and outbox.status == "cancelled"

        events = harness.store.list_events("run-failed")
        assert [event.event_type for event in events] == [
            "run_created",
            "run_archived",
        ]
        event = events[-1]
        assert event.sequence == 2
        assert event.run_version == 4
        payload = json.loads(event.payload_json)
        assert payload["archivedFromStatus"] == RunStatus.FAILED.value
        assert payload["terminalReason"] == "failed terminal reason"
        assert payload["archiveReason"] == "清理启动超时"
    finally:
        harness.close()


def test_cancelled_run_archive_is_not_reconcile_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_terminal_run(
            harness,
            run_id="run-cancelled",
            status=RunStatus.CANCELLED.value,
        )
        request = harness.request(
            run_id="run-cancelled",
            command=WorkflowCommandKind.ARCHIVE_RUN,
            node_id=None,
            expected_run_version=3,
            idempotency_key="ui:archive-cancelled",
        )

        first = harness.service.submit(request)
        second = harness.service.submit(request)

        assert first == second
        assert build_reconcile_run_offer(
            run=harness.store.get_run("run-cancelled")
        ).available is False
        run = harness.store.get_run("run-cancelled")
        assert run is not None and run.status == RunStatus.ARCHIVED.value
        assert run.run_version == 4
        assert len(harness.store.list_events("run-cancelled")) == 2
    finally:
        harness.close()


def test_archive_rechecks_team_version_and_server_operator(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_terminal_run(
            harness,
            run_id="run-guards",
            status=RunStatus.FAILED.value,
        )

        with pytest.raises(CommandForbiddenError):
            harness.command_service.submit(
                harness.request(
                    run_id="run-guards",
                    command=WorkflowCommandKind.ARCHIVE_RUN,
                    node_id=None,
                    expected_run_version=3,
                    idempotency_key="ui:archive-forbidden",
                )
            )

        with pytest.raises(RunVersionConflictError):
            harness.service.submit(
                harness.request(
                    run_id="run-guards",
                    command=WorkflowCommandKind.ARCHIVE_RUN,
                    node_id=None,
                    expected_run_version=2,
                    idempotency_key="ui:archive-stale-version",
                )
            )

        with pytest.raises(WorkflowCommandError):
            harness.service.submit(
                harness.request(
                    run_id="run-guards",
                    team_id="other-team",
                    command=WorkflowCommandKind.ARCHIVE_RUN,
                    node_id=None,
                    expected_run_version=3,
                    idempotency_key="ui:archive-wrong-team",
                )
            )

        run = harness.store.get_run("run-guards")
        assert run is not None and run.status == RunStatus.FAILED.value
        assert run.run_version == 3
        assert len(harness.store.list_events("run-guards")) == 1
    finally:
        harness.close()
