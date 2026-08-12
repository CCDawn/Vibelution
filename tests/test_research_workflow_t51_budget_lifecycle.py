"""T5.1-5 RED: real budget lifecycle + settle failure reconciliation.

reserve_budget must enforce remaining limits from the frozen policy and ledger
consumption. settle failures must raise (adapter worker records a finding),
never silently succeed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
)
from tests._support.command_helpers import CommandHarness


def _action(node_id: str = "source_finding") -> PendingAction:
    return PendingAction(
        action_id="act-budget",
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _seed_attempt(harness: CommandHarness, action: PendingAction) -> None:
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
    )

    def mutate(uow):
        if uow.repository.get_command("cmd-budget") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-budget",
                    run_id=action.run_id,
                    idempotency_key="cmd-budget",
                )
            )
        if uow.repository.get_attempt(action.node_run_id) is None:
            uow.repository.insert_attempt(
                build_attempt_record(
                    action.node_run_id,
                    run_id=action.run_id,
                    node_id=action.node_id,
                    attempt=1,
                    status="dispatching",
                    command_id="cmd-budget",
                )
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_reserve_persists_budget_receipt(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
        assert reservation["status"] == "reserved"
        assert reservation["reservationId"]
        rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reservation_id, status FROM budget_receipts "
                "WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert rows is not None
        assert rows[0] == reservation["reservationId"]
        assert rows[1] == "reserved"
    finally:
        harness.close()


def test_reserve_blocks_when_token_limit_exhausted(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)

        def shrink(uow):
            import json

            run = uow.repository.get_run("run-test")
            snap = json.loads(run.input_snapshot_json or "{}")
            snap["budgetPolicy"] = {
                "tokens": 500,
                "toolCalls": 300,
                "wallClockSeconds": 21600,
                "autoRetries": 2,
                "stageBudgets": {"knowledge_collection": {"tokens": 500}},
            }
            uow.repository.execute(
                "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
                (json.dumps(snap), "run-test"),
            )

        harness.store.submit(shrink, force_flush=True).result(timeout=10)
        ports = RealDomainPorts(harness.store)
        with pytest.raises(RuntimeError, match="budget|limit|exceed"):
            ports.reserve_budget(action=action, estimate_tokens=25_000)
    finally:
        harness.close()


def test_settle_updates_receipt_and_rejects_missing(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
        ports.settle_budget(
            reservation=reservation,
            usage={"estimate_tokens": 1000, "tokens": 800},
        )
        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None and row[0] == "settled"

        with pytest.raises(RuntimeError, match="budget|settle|missing"):
            ports.settle_budget(
                reservation={"reservationId": "reservation-does-not-exist"},
                usage={"tokens": 1},
            )
    finally:
        harness.close()


def test_release_voids_unused_reservation(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        release_budget_reservation,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
        release_budget_reservation(harness.store, reservation)
        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None and row[0] == "released"
    finally:
        harness.close()
