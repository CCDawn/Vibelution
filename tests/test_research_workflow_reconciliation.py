"""T5 RED: reconciliation — read-only scans surface stuck attempts without
mutating anything."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.ledger.reconciliation import (
    run_ledger_reconciliation,
    run_readonly_reconciliation,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def test_terminal_run_with_pending_outbox_found(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        def cancel(uow):
            from core.research.workflow.ledger import CommandRecord

            uow.repository.update_run_status(
                "run-test", "research-team", "cancelled", FIXED_NOW_MS
            )

        harness.store.submit(cancel, force_flush=True).result(timeout=10)
        findings = run_readonly_reconciliation(harness.store)
        assert any(f.kind == "terminal_run_pending_outbox" for f in findings)
    finally:
        harness.close()


def _seed_attempt(harness: CommandHarness, node_run_id: str, status: str) -> None:
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
    )

    def mutate(uow):
        if uow.repository.get_command("cmd-driver") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver", run_id="run-test", idempotency_key="cmd-driver"
                )
            )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=node_run_id,
                run_id="run-test",
                node_id="source_finding",
                attempt=1,
                status=status,
                command_id="cmd-driver",
                started_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_stuck_starting_attempt_found(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        # 无 outbox 的 starting attempt（崩溃残留）。
        _seed_attempt(harness, "nr-stuck", "starting")
        findings = run_ledger_reconciliation(harness.store, run_ids=["run-test"])
        assert any(f.kind == "starting_without_outbox" for f in findings)
    finally:
        harness.close()


def test_stuck_dispatching_attempt_found(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_attempt(harness, "nr-dispatching", "dispatching")
        findings = run_ledger_reconciliation(harness.store, run_ids=["run-test"])
        assert any(f.kind == "dispatching_without_adapter" for f in findings)
    finally:
        harness.close()


def test_reconciliation_is_readonly(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_attempt(harness, "nr-stuck", "starting")
        run_ledger_reconciliation(harness.store, run_ids=["run-test"])
        run = harness.store.get_run("run-test")
        assert run is not None and run.run_version == 1
        assert harness.store.latest_event_sequence("run-test") == 1
    finally:
        harness.close()
