"""Adapter lease exhaustion must not strand a formal run as active."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from core.research.workflow.contracts import PendingAction
from core.research.workflow.ledger.repository import MAX_OUTBOX_LEASE_ATTEMPTS
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import (
    ActionRegistry,
)
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_outbox_record,
)


def _seed_exhausted_adapter_dispatch(harness: CommandHarness) -> str:
    action = PendingAction(
        action_id="act-lease-exhausted",
        run_id="run-test",
        node_run_id="nr-run-test-source_finding-a1",
        node_id="source_finding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="policy-1",
    )
    outbox_id = "adapter-outbox-lease-exhausted"

    def mutate(uow):
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-lease-exhausted",
                run_id=action.run_id,
                idempotency_key="cmd:lease-exhausted",
                node_id=action.node_id,
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=action.node_run_id,
                run_id=action.run_id,
                node_id=action.node_id,
                attempt=1,
                status="dispatching",
                command_id="cmd-lease-exhausted",
                started_at_ms=FIXED_NOW_MS,
            )
        )
        uow.repository.insert_outbox(
            replace(
                build_outbox_record(
                    outbox_id,
                    run_id=action.run_id,
                    command_id="cmd-lease-exhausted",
                    action_kind="adapter_dispatch",
                    available_at_ms=FIXED_NOW_MS,
                ),
                node_run_id=action.node_run_id,
                payload_json=json.dumps(action.to_dict()),
                attempt_count=MAX_OUTBOX_LEASE_ATTEMPTS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)
    return outbox_id


def test_adapter_lease_exhaustion_terminalizes_run_once(tmp_path: Path) -> None:
    """The ledger gate and adapter repair converge in the same worker tick."""

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        outbox_id = _seed_exhausted_adapter_dispatch(harness)
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=ActionRegistry(),
            ports=FakeDomainPorts(),
            owner_id="adapter-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )

        handled = worker.run_once()

        assert handled == 1
        outbox = harness.store.read(lambda repo: repo.get_outbox(outbox_id))
        assert outbox is not None and outbox.status == "failed"
        assert json.loads(str(outbox.last_problem_json))["code"] == (
            "lease_attempt_exhausted"
        )
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "failed"
        run = harness.store.get_run("run-test")
        assert run.status == "blocked"
        run_problem = json.loads(str(run.blocked_problem_json))
        assert run_problem["code"] == "lease_attempt_exhausted"
        assert run_problem["maxLeaseAttempts"] == MAX_OUTBOX_LEASE_ATTEMPTS
        sequence = run.last_event_sequence

        assert worker.run_once() == 0
        assert harness.store.get_run("run-test").last_event_sequence == sequence
    finally:
        harness.close()


def test_stale_exhausted_adapter_cannot_fail_newer_attempt(tmp_path: Path) -> None:
    """A retry that became authoritative before the sweep fences the old row."""

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        _seed_exhausted_adapter_dispatch(harness)
        newer_action = PendingAction(
            action_id="act-new-owner",
            run_id="run-test",
            node_run_id="nr-run-test-source_finding-a2",
            node_id="source_finding",
            attempt=2,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="b" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="policy-1",
        )

        def seed_newer_attempt(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-new-owner",
                    run_id="run-test",
                    idempotency_key="cmd:new-owner",
                    node_id="source_finding",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-test-source_finding-a2",
                    run_id="run-test",
                    node_id="source_finding",
                    attempt=2,
                    status="dispatching",
                    command_id="cmd-new-owner",
                    started_at_ms=FIXED_NOW_MS + 500,
                )
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        "adapter-outbox-new-owner",
                        run_id="run-test",
                        command_id="cmd-new-owner",
                        action_kind="adapter_dispatch",
                        available_at_ms=FIXED_NOW_MS + 60_000,
                    ),
                    node_run_id=newer_action.node_run_id,
                    payload_json=json.dumps(newer_action.to_dict()),
                )
            )

        harness.store.submit(seed_newer_attempt, force_flush=True).result(timeout=10)
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=ActionRegistry(),
            ports=FakeDomainPorts(),
            owner_id="adapter-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )

        assert worker.run_once() == 0
        assert harness.store.get_run("run-test").status == "running"
        latest = harness.store.latest_attempt("run-test", "source_finding")
        assert latest is not None
        assert latest.node_run_id == "nr-run-test-source_finding-a2"
        assert latest.status == "dispatching"
        replacement = harness.store.read(
            lambda repo: repo.get_outbox("adapter-outbox-new-owner")
        )
        assert replacement is not None and replacement.status == "pending"
    finally:
        harness.close()
