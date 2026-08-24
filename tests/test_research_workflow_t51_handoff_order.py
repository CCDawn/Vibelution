"""T5.1-4 RED: handoff accepted before successor readiness + own binding snapshot.

Auto-advance must commit upstream Handoff to accepted before evaluating the
successor NodeReadiness. Successor PendingAction/Attempt must use that node's
own bindingSnapshotId, never the parent node's.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.research.workflow.contracts import NodeReadiness, ReadinessBlocker
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


class RecordingReadiness:
    """Captures handoff statuses observed during evaluate()."""

    def __init__(self, store, *, ready: bool = True) -> None:
        self.store = store
        self.ready = ready
        self.observed_handoff_statuses: list[str] = []
        self.evaluated_nodes: list[str] = []

    def evaluate(self, *, team_id, run_id, node_id, context, use_cache=True):
        self.evaluated_nodes.append(node_id)
        rows = self.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM handoffs WHERE run_id = ?",
                (run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        self.observed_handoff_statuses = [str(r[0]) for r in rows]
        blockers = ()
        if not self.ready:
            blockers = (
                ReadinessBlocker(
                    code="forced_block",
                    title="forced",
                    detail="forced",
                ),
            )
        # Also fail if handoff not yet accepted — mirrors production common check.
        if any(status != "accepted" for status in self.observed_handoff_statuses):
            blockers = blockers + (
                ReadinessBlocker(
                    code="handoff_not_accepted",
                    title="handoff",
                    detail="handoff still not accepted during readiness",
                ),
            )
            ready = False
        else:
            ready = self.ready and not blockers
        return NodeReadiness(
            run_id=run_id,
            team_id=team_id,
            node_id=node_id,
            run_version=1,
            ready=ready,
            evaluated_at_ms=FIXED_NOW_MS,
            domain_revision_vector={},
            accepted_handoff_ids=(),
            input_artifact_refs=(),
            actor=None,
            budget=None,
            blockers=blockers,
        )


def _consume_adapter(harness: GraphHarness, action_id: str) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE outbox_actions SET status = 'succeeded' WHERE action_id = ?",
            (action_id,),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _seed_bindings(harness: GraphHarness) -> None:
    """Ensure run input snapshot has distinct bindings per node."""

    def mutate(uow):
        run = uow.repository.get_run("run-test")
        snapshot = json.loads(run.input_snapshot_json or "{}")
        snapshot["agentBindingSnapshot"] = [
            {
                "snapshotId": "snap:run-test:source_finding",
                "nodeId": "source_finding",
                "agentId": "agent-finding",
                "roleKey": "source_finder",
            },
            {
                "snapshotId": "snap:run-test:source_extraction",
                "nodeId": "source_extraction",
                "agentId": "agent-extraction",
                "roleKey": "source_extractor",
            },
        ]
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (json.dumps(snapshot, ensure_ascii=False), "run-test"),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def test_handoff_accepted_before_successor_readiness(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        _seed_bindings(harness)
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        first_action_id = json.loads(first_pending.payload_json)["actionId"]
        _consume_adapter(harness, first_pending.action_id)

        # Ensure a handoff row exists from source_finding (ready, not accepted).
        finding = harness.commands.store.latest_attempt("run-test", "source_finding")
        assert finding is not None

        def ensure_handoff(uow):
            existing = uow.repository.get_handoff_by_from_node(
                "run-test", finding.node_run_id
            )
            if existing is not None:
                if str(existing[8]) == "pending":
                    uow.repository.update_handoff_status(
                        existing[0], "ready", FIXED_NOW_MS
                    )
                return
            uow.repository.insert_handoff(
                handoff_id="ho-finding-extract",
                run_id="run-test",
                edge_id="e_find_extract",
                from_node_run_id=finding.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_handoff_status(
                "ho-finding-extract", "ready", FIXED_NOW_MS
            )

        harness.commands.store.submit(ensure_handoff, force_flush=True).result(timeout=10)

        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
            outcome="succeeded",
        )
        readiness = RecordingReadiness(harness.commands.store, ready=True)
        worker = GraphDispatchWorker(
            store=harness.commands.store,
            coordinator=ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite"),
            owner_id="graph-worker-t514",
            now_provider=lambda: FIXED_NOW_MS + 1000,
            readiness_service=readiness,
            readiness_context=lambda: None,
        )
        handled = worker.run_once()
        assert handled == 1
        assert "source_extraction" in readiness.evaluated_nodes
        assert readiness.observed_handoff_statuses, "readiness must observe handoffs"
        assert all(
            status == "accepted" for status in readiness.observed_handoff_statuses
        ), f"handoff must be accepted before readiness, saw {readiness.observed_handoff_statuses}"

        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
        assert extraction.status == "dispatching"
        assert extraction.binding_snapshot_id == "snap:run-test:source_extraction"
        assert extraction.binding_snapshot_id != "snap:run-test:source_finding"
    finally:
        harness.close()


def test_crash_between_handoff_accept_and_successor_is_recoverable(tmp_path: Path) -> None:
    """If successor commit fails after handoff accept, a retry must not leave
    permanent dispatching/leased orphans and must still see accepted handoff."""
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        _seed_bindings(harness)
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        first_action_id = json.loads(first_pending.payload_json)["actionId"]
        _consume_adapter(harness, first_pending.action_id)

        finding = harness.commands.store.latest_attempt("run-test", "source_finding")

        def ensure_handoff(uow):
            existing = uow.repository.get_handoff_by_from_node(
                "run-test", finding.node_run_id
            )
            if existing is not None:
                if str(existing[8]) == "pending":
                    uow.repository.update_handoff_status(
                        existing[0], "ready", FIXED_NOW_MS
                    )
                return
            uow.repository.insert_handoff(
                handoff_id="ho-crash",
                run_id="run-test",
                edge_id="e_find_extract",
                from_node_run_id=finding.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_handoff_status("ho-crash", "ready", FIXED_NOW_MS)

        harness.commands.store.submit(ensure_handoff, force_flush=True).result(timeout=10)
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
            outcome="succeeded",
        )

        class BoomAfterAccept(GraphDispatchWorker):
            def _commit_successor_dispatch(self, *args, **kwargs):
                raise RuntimeError("injected crash after handoff accept")

        boom = BoomAfterAccept(
            store=harness.commands.store,
            coordinator=ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite"),
            owner_id="graph-worker-crash",
            now_provider=lambda: FIXED_NOW_MS + 2000,
            readiness_service=RecordingReadiness(harness.commands.store, ready=True),
            readiness_context=lambda: None,
        )
        try:
            boom.run_once()
        except RuntimeError:
            pass

        # Handoff should already be accepted; outbox not permanently leased.
        handoff = harness.commands.store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node(
                "run-test", finding.node_run_id
            ),
            force_flush=True,
        ).result(timeout=10)
        assert handoff is not None
        assert handoff[8] == "accepted"

        # Recover with a healthy worker (requeue only the failed resume action).
        def requeue(uow):
            uow.repository.execute(
                "UPDATE outbox_actions SET status='pending', lease_owner=NULL, "
                "lease_expires_at_ms=NULL, available_at_ms=? "
                "WHERE action_kind='graph_dispatch' "
                "AND last_problem_json LIKE '%successor_commit_failed%'",
                (FIXED_NOW_MS + 2500,),
            )

        harness.commands.store.submit(requeue, force_flush=True).result(timeout=10)
        healthy = GraphDispatchWorker(
            store=harness.commands.store,
            coordinator=ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite"),
            owner_id="graph-worker-recover",
            now_provider=lambda: FIXED_NOW_MS + 4000,
            readiness_service=RecordingReadiness(harness.commands.store, ready=True),
            readiness_context=lambda: None,
        )
        healthy.run_once()
        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
        assert extraction.status == "dispatching"
        assert extraction.binding_snapshot_id == "snap:run-test:source_extraction"
    finally:
        harness.close()
