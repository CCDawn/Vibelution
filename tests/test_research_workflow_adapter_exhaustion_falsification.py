"""T5 falsification: lease-attempt exhaustion must converge, never revive.

The plan's VERIFY-FIRST item asked for time-advance + event-growth evidence
before touching any business code: starting from a *pending* adapter dispatch
row, repeatedly lease it and crash (never ack), advancing the clock past each
lease expiry.  These tests pin the observed contract:

- the lease-attempt gate terminalizes the row exactly once at the attempt
  cap (one failure marker, not one per competing sweep);
- the adapter repair sweep converts that dead letter into a ``failed``
  attempt and a ``blocked`` run carrying the same problem code;
- further ticks (with time still advancing) are no-ops: bounded events, no
  resurrection, no tight loop;
- ``reconcile_run`` on the blocked run re-lands the run on the same blocked
  verdict, never revives the exhausted adapter row, and never wakes a
  worker — so repair + reconcile + repair cannot form a revival cycle.

No tight loop was reproduced, so no business-code change is authorized by
this task (the plan keeps T5 test-only until one is).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from core.research.workflow.contracts import PendingAction, WorkflowCommandKind
from core.research.workflow.ledger import outbox as outbox_api
from core.research.workflow.ledger.repository import MAX_OUTBOX_LEASE_ATTEMPTS
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import (
    ActionRegistry,
)
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    DEFAULT_ADAPTER_DISPATCH_LEASE_MS,
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

_OUTBOX_ID = "adapter-outbox-time-exhaust"
_LEASE_MS = DEFAULT_ADAPTER_DISPATCH_LEASE_MS


def _seed_pending_adapter_dispatch(harness: CommandHarness) -> str:
    """A fresh, un-exhausted adapter dispatch row next to a live attempt."""

    action = PendingAction(
        action_id="act-time-exhaust",
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

    def mutate(uow):
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-time-exhaust",
                run_id=action.run_id,
                idempotency_key="cmd:time-exhaust",
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
                command_id="cmd-time-exhaust",
                started_at_ms=FIXED_NOW_MS,
            )
        )
        uow.repository.insert_outbox(
            replace(
                build_outbox_record(
                    _OUTBOX_ID,
                    run_id=action.run_id,
                    command_id="cmd-time-exhaust",
                    action_kind="adapter_dispatch",
                    available_at_ms=FIXED_NOW_MS,
                ),
                node_run_id=action.node_run_id,
                payload_json=json.dumps(action.to_dict()),
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)
    return _OUTBOX_ID


def test_time_advance_lease_exhaustion_converges_without_revival(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        _seed_pending_adapter_dispatch(harness)
        now = {"ms": FIXED_NOW_MS}

        def lease_tick() -> list:
            # Mirrors the worker's first step, then "crashes": the leased row
            # is never acked, so only lease expiry can ever free it again.
            return outbox_api.lease_ready_actions(
                harness.store,
                owner="adapter-worker-crash",
                now_ms=now["ms"],
                limit=4,
                lease_ms=_LEASE_MS,
                action_kinds=("adapter_dispatch",),
            )

        for tick in range(MAX_OUTBOX_LEASE_ATTEMPTS):
            leased = lease_tick()
            assert [action.action_id for action in leased] == [_OUTBOX_ID], (
                f"tick {tick}: the crash-only row must stay the sole lease target"
            )
            row = harness.store.read(lambda repo: repo.get_outbox(_OUTBOX_ID))
            assert row is not None
            assert row.status == "leased"
            assert row.attempt_count == tick + 1
            assert harness.store.get_run("run-test").status == "running"
            # The next lease only happens after this lease expires.
            now["ms"] += _LEASE_MS + 1_000

        # One more lease pass after the final expiry: the attempt gate must
        # terminalize the row instead of leasing it again.
        assert lease_tick() == []
        gated = harness.store.read(lambda repo: repo.get_outbox(_OUTBOX_ID))
        assert gated is not None
        assert gated.status == "failed"
        assert gated.attempt_count == MAX_OUTBOX_LEASE_ATTEMPTS
        gated_problem = json.loads(str(gated.last_problem_json))
        assert gated_problem["code"] == "lease_attempt_exhausted"
        assert gated_problem["maxLeaseAttempts"] == MAX_OUTBOX_LEASE_ATTEMPTS

        # The repair sweep lands the dead letter exactly once.
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=ActionRegistry(),
            ports=FakeDomainPorts(),
            owner_id="adapter-worker-test",
            now_provider=lambda: now["ms"],
        )
        assert worker.run_once() == 1
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "failed"
        run = harness.store.get_run("run-test")
        assert run.status == "blocked"
        run_problem = json.loads(str(run.blocked_problem_json))
        assert run_problem["code"] == "lease_attempt_exhausted"

        # Bounded growth: with the clock still advancing, N extra ticks add
        # zero work, zero repairs, zero new leases, zero events.
        sequence_after_landing = run.last_event_sequence
        attempt_count_after_landing = harness.store.read(
            lambda repo: repo.get_outbox(_OUTBOX_ID)
        ).attempt_count
        for _ in range(3):
            now["ms"] += _LEASE_MS + 1_000
            assert worker.run_once() == 0
            assert lease_tick() == []
        settled = harness.store.get_run("run-test")
        assert settled.status == "blocked"
        assert settled.last_event_sequence == sequence_after_landing
        assert (
            json.loads(str(settled.blocked_problem_json))["code"]
            == "lease_attempt_exhausted"
        )
        assert harness.store.latest_attempt(
            "run-test", "source_finding"
        ).status == "failed"
        final_row = harness.store.read(lambda repo: repo.get_outbox(_OUTBOX_ID))
        assert final_row.status == "failed"
        assert final_row.attempt_count == attempt_count_after_landing
    finally:
        harness.close()


def test_reconcile_keeps_exhausted_run_blocked_without_revival(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        _seed_pending_adapter_dispatch(harness)
        harness.store.submit(
            lambda uow: uow.repository.execute(
                """
                UPDATE outbox_actions
                SET status = 'failed',
                    attempt_count = ?,
                    last_problem_json = ?,
                    updated_at_ms = updated_at_ms + 1
                WHERE action_id = ?
                """,
                (
                    MAX_OUTBOX_LEASE_ATTEMPTS,
                    json.dumps(
                        {
                            "code": "lease_attempt_exhausted",
                            "maxLeaseAttempts": MAX_OUTBOX_LEASE_ATTEMPTS,
                        }
                    ),
                    _OUTBOX_ID,
                ),
            ),
            force_flush=True,
        ).result(timeout=10)
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=ActionRegistry(),
            ports=FakeDomainPorts(),
            owner_id="adapter-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )
        assert worker.run_once() == 1
        blocked = harness.store.get_run("run-test")
        assert blocked.status == "blocked"
        wake_before = harness.wake_count

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=blocked.run_version,
                idempotency_key="ui:reconcile-exhausted",
            )
        )
        assert receipt.accepted_run_version is not None

        # Reconcile re-lands the ledger verdict verbatim: the run stays
        # blocked on the same problem, the exhausted adapter row stays dead,
        # and nothing wakes a worker.
        reconciled = harness.store.get_run("run-test")
        assert reconciled.status == "blocked"
        problem = json.loads(str(reconciled.blocked_problem_json))
        assert problem["code"] == "lease_attempt_exhausted"
        row = harness.store.read(lambda repo: repo.get_outbox(_OUTBOX_ID))
        assert row is not None and row.status == "failed"
        assert row.attempt_count == MAX_OUTBOX_LEASE_ATTEMPTS
        assert harness.wake_count == wake_before

        # repair -> reconcile -> repair is a no-op cycle, not a revival loop.
        assert worker.run_once() == 0
        assert harness.store.get_run("run-test").status == "blocked"
        assert (
            harness.store.latest_attempt("run-test", "source_finding").status
            == "failed"
        )
    finally:
        harness.close()
