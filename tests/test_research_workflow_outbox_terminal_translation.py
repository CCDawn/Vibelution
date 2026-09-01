"""Terminal-failed graph_dispatch must translate into run-level reconciliation.

A graph_dispatch that exhausts its transient budget (or the lease-attempt
gate) used to only fail the outbox row: when the node attempt was already
terminal — the explicit-rerun short-circuit produced ``succeeded`` attempts
before b83056dbb removed that path — ``_mark_blocked`` returned without any
run translation, stranding the run as ``running`` forever (no advancing
mechanism, no reconcile_run offer, UI had no recovery entry). These tests pin
the translation chain and the self-healing sweep for already-stuck rows.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.ledger.outbox import lease_ready_actions
from core.research.workflow.transitions import RunStatus, require_run_transition
from core.web.services.team_workflow.research_runtime.command_offers.reconcile_run import (
    build_reconcile_run_offer,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_outbox_record,
    build_run_record,
)

_MISMATCH_DETAIL = (
    "execution receipt identity mismatch: "
    "expected (act-10f84a92b0d1e6c7a, nr-run-test-evidence_relations-a2), "
    "got (act-5cd0046334264954, nr-run-test-evidence_relations-a2)"
)


def _seed_stuck_production_shape(
    commands: CommandHarness,
    *,
    run_id: str = "run-test",
    run_status: str = "running",
) -> None:
    """Ledger shape observed in run-d02722658d8b: a succeeded attempt plus a
    terminal-failed resume dispatch and no live graph_dispatch left."""
    identity = register_or_resolve(build_challenge_cup_workflow_definition())
    record = replace(
        build_run_record(
            run_id=run_id,
            status=run_status,
            workflow_version_id=identity.workflowVersionId,
        ),
        structure_hash=identity.structureHash,
    )
    store = commands.store

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-a2",
                run_id=run_id,
                idempotency_key="key:a2",
                node_id="evidence_relations",
            )
        )
        uow.repository.execute(
            "UPDATE workflow_runs SET active_node_id = 'evidence_relations',"
            " updated_at_ms = updated_at_ms + 1 WHERE run_id = ?",
            (run_id,),
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=f"nr-{run_id}-evidence_relations-a2",
                run_id=run_id,
                node_id="evidence_relations",
                attempt=2,
                status="succeeded",
                command_id="cmd-a2",
            )
        )
        uow.repository.insert_outbox(
            replace(
                build_outbox_record(
                    "act-a244894b8c1044d59f31701696b967ff",
                    run_id=run_id,
                    command_id="cmd-a2",
                    idempotency_key="graph:resume:act-5cd0046334264954",
                    status="failed",
                ),
                node_run_id=f"nr-{run_id}-evidence_relations-a2",
                attempt_count=5,
                last_problem_json=json.dumps(
                    {
                        "code": "graph_dispatch_invalid",
                        "detail": f"transient_exhausted: {_MISMATCH_DETAIL}",
                    }
                ),
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)


def _make_worker(commands: CommandHarness, *, coordinator=None) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=commands.store,
        coordinator=coordinator or object(),
        owner_id="graph-worker-test",
        now_provider=lambda: FIXED_NOW_MS + 2000,
    )


def test_terminal_failed_dispatch_reconciles_stranded_running_run(tmp_path: Path) -> None:
    """The exact stuck production ledger state heals on the next worker tick."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands)
        worker = _make_worker(commands)

        repaired = worker.run_once()

        assert repaired >= 1
        run = commands.store.get_run("run-test")
        assert run.status == "reconciliation_required"
        problem = json.loads(str(run.blocked_problem_json))
        assert problem["code"] == "graph_dispatch_invalid"
        assert "execution receipt identity mismatch" in problem["detail"]
        # 转译后 reconcile_run offer 必须可用，操作员有恢复入口。
        offer = build_reconcile_run_offer(run=run)
        assert offer.available is True

        # 幂等：第二次 tick 不产生新的转译副作用。
        worker.run_once()
        again = commands.store.get_run("run-test")
        assert again.status == "reconciliation_required"
        assert again.blocked_problem_json == run.blocked_problem_json
        assert again.last_event_sequence == run.last_event_sequence
    finally:
        commands.close()


def test_terminal_failed_translation_enables_reconcile_command(tmp_path: Path) -> None:
    """After the sweep translated the stranded run, reconcile_run is accepted."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands)
        worker = _make_worker(commands)
        worker.run_once()
        translated = commands.store.get_run("run-test")
        require_run_transition(RunStatus(translated.status), RunStatus.RUNNING)

        receipt = commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=translated.run_version,
                idempotency_key="ui:reconcile-after-translation",
            )
        )
        assert receipt.accepted_run_version is not None

        recovered = commands.store.get_run("run-test")
        assert recovered.status == "running"
    finally:
        commands.close()


def test_live_graph_dispatch_rows_block_the_sweep(tmp_path: Path) -> None:
    """A run still being worked on (pending/leased dispatch) is never touched."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands)
        live_row = replace(
            build_outbox_record(
                "act-live-followup",
                idempotency_key="graph:start:live",
                status="pending",
            ),
            command_id="cmd-a2",
        )
        commands.store.submit(
            lambda uow: uow.repository.insert_outbox(live_row), force_flush=True
        ).result(timeout=10)
        worker = _make_worker(commands)

        worker._repair_terminal_failed_dispatch()

        assert commands.store.get_run("run-test").status == "running"
    finally:
        commands.close()


def test_blocked_runs_keep_their_own_recovery_entry(tmp_path: Path) -> None:
    """Ordinary BLOCKED runs keep their blocked reason; the sweep skips them."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands, run_status="blocked")
        worker = _make_worker(commands)

        worker._repair_terminal_failed_dispatch()

        assert commands.store.get_run("run-test").status == "blocked"
    finally:
        commands.close()


class _ActionStub:
    action_id = "act-still-leased"


class _DispatchStub:
    team_id = "research-team"
    run_id = "run-test"
    node_id = "evidence_relations"
    node_run_id = "nr-run-test-evidence_relations-a2"


def test_mark_blocked_with_terminal_attempt_translates_run(tmp_path: Path) -> None:
    """First-scene fix: `_mark_blocked` may not strand a terminal attempt.

    With the node attempt already ``succeeded``, rewinding to ``blocked`` is
    illegal, but the terminal-failed dispatch still needs a run-level
    translation so the operator keeps a recovery entry.
    """
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands)
        leased_row = replace(
            build_outbox_record(
                "act-still-leased",
                idempotency_key="graph:resume:inflight",
            ),
            command_id="cmd-a2",
            node_run_id="nr-run-test-evidence_relations-a2",
            status="leased",
            lease_owner="graph-worker-test",
            lease_expires_at_ms=FIXED_NOW_MS + 30_000,
        )
        commands.store.submit(
            lambda uow: uow.repository.insert_outbox(leased_row), force_flush=True
        ).result(timeout=10)
        worker = _make_worker(commands)

        worker._mark_blocked(
            _ActionStub(), _DispatchStub(), _MISMATCH_DETAIL
        )

        row = commands.store.read(
            lambda repo: repo.get_outbox("act-still-leased")
        )
        assert row is not None and row.status == "failed"
        run = commands.store.get_run("run-test")
        assert run.status == "reconciliation_required"
        assert build_reconcile_run_offer(run=run).available is True
    finally:
        commands.close()


class _IdentityMismatchCoordinator:
    def __init__(self) -> None:
        self.resume_calls = 0

    def resume_action(self, dispatch):
        self.resume_calls += 1
        raise ValueError(f"execution receipt identity mismatch: {_MISMATCH_DETAIL}")


def test_identity_mismatch_fails_fast_without_transient_loop(tmp_path: Path) -> None:
    """Deterministic receipt/checkpoint drift must not burn five retries.

    A pending resume dispatch whose receipt cannot ever match the checkpoint
    interrupt terminates on the first pass instead of requeueing five times,
    and the resulting failure translates into reconciliation because the
    seeded attempt is already terminal.
    """
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands)
        worker = _make_worker(
            commands, coordinator=_IdentityMismatchCoordinator()
        )
        pending = replace(
            build_outbox_record(
                "act-resume-live",
                idempotency_key="graph:resume:act-5cd0046334264954-pending",
            ),
            command_id="cmd-a2",
            node_run_id="nr-run-test-evidence_relations-a2",
        )
        payload = {
            "commandId": "cmd-driver",
            "runId": "run-test",
            "nodeRunId": "nr-run-test-evidence_relations-a2",
            "nodeId": "evidence_relations",
            "attempt": 2,
            "dispatchKind": "resume_action",
            "teamId": "research-team",
            "workflowVersionId": "challenge-cup-research-v2.1.0",
            "inputSnapshotHash": "a" * 64,
            "budgetPolicyHash": "",
            "receipt": {
                "actionId": "act-5cd0046334264954",
                "nodeRunId": "nr-run-test-evidence_relations-a2",
                "outcome": "succeeded",
                "artifactReceiptIds": [],
                "completedAtMs": FIXED_NOW_MS,
            },
        }
        pending_row = replace(
            pending, payload_json=json.dumps(payload)
        )
        commands.store.submit(
            lambda uow: uow.repository.insert_outbox(pending_row), force_flush=True
        ).result(timeout=10)

        worker.run_once()

        row = commands.store.read(lambda repo: repo.get_outbox("act-resume-live"))
        assert row is not None and row.status == "failed"
        # 只领取一次即终态：不再以 transient 反复 requeue 烧预算。
        assert row.attempt_count == 1
        assert worker._coordinator.resume_calls == 1
        run = commands.store.get_run("run-test")
        assert run.status == "reconciliation_required"
    finally:
        commands.close()


def test_reconcile_command_accepts_blocked_run_and_revives_failed_dispatch(
    tmp_path: Path,
) -> None:
    """SCI-003: a blocked run with a terminal-failed dispatch is the exact
    shape reconcile_run exists for.  The command must be accepted (V2 keeps
    no other recovery entry) and must re-arm the failed graph_dispatch so
    the worker actually re-derives routing instead of stranding a running
    run nothing will ever advance."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands, run_status="blocked")
        run_before = commands.store.get_run("run-test")
        require_run_transition(RunStatus(run_before.status), RunStatus.RUNNING)
        assert build_reconcile_run_offer(run=run_before).available is True

        receipt = commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=run_before.run_version,
                idempotency_key="ui:reconcile-blocked",
            )
        )
        assert receipt.accepted_run_version is not None

        recovered = commands.store.get_run("run-test")
        assert recovered.status == "running"
        revived = commands.store.read(
            lambda repo: repo.get_outbox(
                "act-a244894b8c1044d59f31701696b967ff"
            )
        )
        assert revived is not None and revived.status == "pending"
        assert revived.attempt_count == 0
        # 复活了可推进的 dispatch，必须叫醒 worker 立即重算路由。
        assert commands.wake_count >= 1

        # 下一 tick 能真正领到复活后的 dispatch（不是永远停在 pending）。
        leased = lease_ready_actions(
            commands.store,
            owner="graph-worker-test",
            now_ms=FIXED_NOW_MS + 5000,
        )
        assert [action.action_id for action in leased] == [
            "act-a244894b8c1044d59f31701696b967ff"
        ]
    finally:
        commands.close()


def test_reconcile_command_without_active_work_stays_fail_closed(
    tmp_path: Path,
) -> None:
    """No dispatch to revive: keep the run diagnosable and do not wake."""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_stuck_production_shape(commands, run_status="blocked")
        commands.store.submit(
            lambda uow: uow.repository.execute(
                "DELETE FROM outbox_actions WHERE run_id = 'run-test'"
            ),
            force_flush=True,
        ).result(timeout=10)
        wake_before = commands.wake_count

        receipt = commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=1,
                idempotency_key="ui:reconcile-no-dispatch",
            )
        )
        assert receipt.accepted_run_version is not None
        recovered = commands.store.get_run("run-test")
        assert recovered.status == "reconciliation_required"
        assert json.loads(str(recovered.blocked_problem_json))["code"] == (
            "reconcile_no_active_work"
        )
        assert commands.wake_count == wake_before
    finally:
        commands.close()
