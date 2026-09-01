"""Regression coverage for persisted interrupts whose task queue is empty."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow import challenge_cup_runtime
from core.research.workflow.challenge_cup_runtime import (
    GraphDispatch,
    action_id_for,
    build_pending_action,
    merge_node_attempts,
)
from core.research.workflow.contracts import ExecutionReceipt
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    DEFAULT_ADAPTER_DISPATCH_LEASE_MS,
)
from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
    DEFAULT_AGENT_TURN_TIMEOUT_MS,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def test_node_attempt_reducer_keeps_each_nodes_highest_durable_attempt() -> None:
    assert merge_node_attempts(
        {"source_finding": 1, "source_extraction": 4},
        {"source_extraction": 1, "evidence_relations": 2},
    ) == {
        "source_finding": 1,
        "source_extraction": 4,
        "evidence_relations": 2,
    }


def test_adapter_lease_outlives_bounded_agent_turn_wait() -> None:
    assert DEFAULT_ADAPTER_DISPATCH_LEASE_MS > DEFAULT_AGENT_TURN_TIMEOUT_MS


def test_restart_persisted_interrupt_with_new_attempt_is_single_graph_update(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        start = GraphDispatch(
            action_id="act-driver",
            run_id="run-restart",
            node_run_id="nr-run-restart-problem_understanding-a1",
            node_id="problem_understanding",
            attempt=1,
            dispatch_kind="start",
            input_snapshot_hash="a" * 64,
            workflow_version_id="challenge-cup-research-v2.1.0",
            team_id="research-team",
        )
        entered = harness.coordinator.start_attempt(start)
        assert entered.pending_action is not None
        assert entered.pending_action.node_id == "problem_understanding"

        # 图入口是 problem_understanding：先走通入口节点，线程才中断在
        # source_finding，与生产首发 dispatch 路径一致。
        entry_receipt = ExecutionReceipt(
            action_id=action_id_for("run-restart", "problem_understanding", 1),
            node_run_id="nr-run-restart-problem_understanding-a1",
            outcome="succeeded",
            artifact_receipt_ids=(),
            execution_anchor_id=None,
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=FIXED_NOW_MS,
        )
        finding = harness.coordinator.resume_action(
            GraphDispatch(
                action_id=entry_receipt.action_id,
                run_id="run-restart",
                node_run_id=entry_receipt.node_run_id,
                node_id="problem_understanding",
                attempt=1,
                dispatch_kind="resume_action",
                receipt=entry_receipt,
            )
        )
        assert finding.pending_action is not None
        assert finding.pending_action.node_id == "source_finding"

        finding_receipt = ExecutionReceipt(
            action_id=action_id_for("run-restart", "source_finding", 1),
            node_run_id="nr-run-restart-source_finding-a1",
            outcome="succeeded",
            artifact_receipt_ids=(),
            execution_anchor_id=None,
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=FIXED_NOW_MS,
        )
        extraction = harness.coordinator.resume_action(
            GraphDispatch(
                action_id=finding_receipt.action_id,
                run_id="run-restart",
                node_run_id=finding_receipt.node_run_id,
                node_id="source_finding",
                attempt=1,
                dispatch_kind="resume_action",
                receipt=finding_receipt,
            )
        )
        assert extraction.pending_action is not None
        assert extraction.pending_action.node_id == "source_extraction"
        assert extraction.pending_action.attempt == 1

        # Reproduce the stale task-specific resume left by a failed replay.
        # The durable checkpoint must remain recoverable even though the bad
        # receipt was persisted as a pending write before the task failed.
        stale_receipt = ExecutionReceipt(
            action_id=finding_receipt.action_id,
            node_run_id=finding_receipt.node_run_id,
            outcome="succeeded",
            artifact_receipt_ids=(),
            execution_anchor_id=None,
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=FIXED_NOW_MS,
        )
        with pytest.raises(ValueError, match="execution receipt identity mismatch"):
            harness.coordinator.resume_action(
                GraphDispatch(
                    action_id=stale_receipt.action_id,
                    run_id="run-restart",
                    node_run_id=stale_receipt.node_run_id,
                    node_id="source_extraction",
                    attempt=1,
                    dispatch_kind="resume_action",
                    team_id="research-team",
                    receipt=stale_receipt,
                )
            )

        restarted = harness.coordinator.restart_attempt(
            GraphDispatch(
                action_id="act-driver-retry",
                run_id="run-restart",
                node_run_id="nr-run-restart-source_extraction-a4",
                node_id="source_extraction",
                attempt=4,
                dispatch_kind="start",
                team_id="research-team",
            )
        )

        assert restarted.pending_action is not None
        assert restarted.pending_action.node_id == "source_extraction"
        assert restarted.pending_action.attempt == 4
        assert restarted.pending_action.action_id == action_id_for(
            "run-restart", "source_extraction", 4
        )

        # A worker crash/requeue can persist another mismatched resume against
        # the freshly restarted task.  The next user retry must create a new
        # task instead of replaying that cached task error again.
        with pytest.raises(ValueError, match="execution receipt identity mismatch"):
            harness.coordinator.resume_action(
                GraphDispatch(
                    action_id=stale_receipt.action_id,
                    run_id="run-restart",
                    node_run_id=stale_receipt.node_run_id,
                    node_id="source_extraction",
                    attempt=4,
                    dispatch_kind="resume_action",
                    team_id="research-team",
                    receipt=stale_receipt,
                )
            )

        restarted_again = harness.coordinator.restart_attempt(
            GraphDispatch(
                action_id="act-driver-retry-again",
                run_id="run-restart",
                node_run_id="nr-run-restart-source_extraction-a5",
                node_id="source_extraction",
                attempt=5,
                dispatch_kind="start",
                team_id="research-team",
            )
        )
        assert restarted_again.pending_action is not None
        assert restarted_again.pending_action.attempt == 5
        assert restarted_again.pending_action.action_id == action_id_for(
            "run-restart", "source_extraction", 5
        )
    finally:
        harness.close()


def test_retry_uses_persisted_interrupt_when_checkpoint_next_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        harness.consume_adapter(first_pending.action_id)

        finding = harness.commands.store.latest_attempt("run-test", "source_finding")
        assert finding is not None

        def seed_completed_finding(uow):
            uow.repository.update_attempt_status(
                finding.node_run_id,
                "succeeded",
                FIXED_NOW_MS + 10,
                finished_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.insert_handoff(
                handoff_id="ho-interrupt-recovery",
                run_id="run-test",
                edge_id="source_finding->source_extraction",
                from_node_run_id=finding.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.update_handoff_status(
                "ho-interrupt-recovery", "ready", FIXED_NOW_MS + 11
            )
            uow.repository.update_handoff_status(
                "ho-interrupt-recovery", "accepted", FIXED_NOW_MS + 12
            )
            uow.repository.insert_artifact_receipt(
                receipt_id="ar-interrupt-candidates",
                run_id="run-test",
                node_run_id=finding.node_run_id,
                team_id="research-team",
                artifact_kind="source_candidate_batch",
                canonical_ref_json=json.dumps(
                    {
                        "canonicalRef": (
                            "source_candidate_batch://research-team/run-test/interrupt"
                        )
                    }
                ),
                artifact_version="1.0.0",
                sha256="b" * 64,
                domain_revision="rev-interrupt",
                materialized=1,
                verified_at_ms=FIXED_NOW_MS + 10,
            )
            uow.repository.insert_handoff_receipt(
                "ho-interrupt-recovery", "ar-interrupt-candidates", 0
            )

        harness.commands.store.submit(
            seed_completed_finding, force_flush=True
        ).result(timeout=10)

        original_snapshot = harness.coordinator.snapshot

        def persisted_interrupt_snapshot(run_id: str, workflow_version_id: str = ""):
            snapshot = dict(original_snapshot(run_id, workflow_version_id))
            values = dict(snapshot.get("values") or {})
            attempts = dict(values.get("node_attempts") or {})
            if attempts.get("source_extraction"):
                # Real persisted SQLite checkpoints can expose the interrupt
                # while ``state.next`` is empty after recompilation.
                snapshot["nextNodeIds"] = []
            return snapshot

        monkeypatch.setattr(
            harness.coordinator, "snapshot", persisted_interrupt_snapshot
        )

        harness.enqueue_graph_dispatch("run-test", "source_extraction", 2)
        harness.worker.run_once()

        extraction = harness.commands.store.latest_attempt(
            "run-test", "source_extraction"
        )
        assert extraction is not None
        assert extraction.attempt == 2
        assert extraction.status == "dispatching"
        assert "checkpoint_node_mismatch" not in (extraction.problem_json or "")
        pending = harness.latest_adapter_pending()
        assert pending is not None
        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "source_extraction"
        assert int(payload["attempt"]) == 2
    finally:
        harness.close()


def test_start_attempt_persists_binding_and_budget_authorities(
    tmp_path: Path,
) -> None:
    """binding_snapshot_id/budget_policy_hash are declared channels.

    Before declaration, langgraph dropped these invoke-input keys, so the
    persisted checkpoint never contained them and ``build_pending_action``
    read empty values back (dead read).
    """

    harness = GraphHarness(tmp_path)
    try:
        entered = harness.coordinator.start_attempt(
            GraphDispatch(
                action_id="act-binding",
                run_id="run-binding",
                node_run_id="nr-run-binding-problem_understanding-a1",
                node_id="problem_understanding",
                attempt=1,
                dispatch_kind="start",
                input_snapshot_hash="a" * 64,
                workflow_version_id="challenge-cup-research-v2.1.0",
                team_id="research-team",
                binding_snapshot_id="binding-snapshot-1",
                budget_policy_hash="d" * 64,
            )
        )

        # The interrupt payload carries the binding/budget identity.
        assert entered.pending_action is not None
        assert entered.pending_action.binding_snapshot_id == "binding-snapshot-1"
        assert entered.pending_action.budget_policy_hash == "d" * 64

        snapshot = harness.coordinator.snapshot("run-binding")
        values = dict(snapshot.get("values") or {})
        assert values["binding_snapshot_id"] == "binding-snapshot-1"
        assert values["budget_policy_hash"] == "d" * 64
        persisted_pending = snapshot.get("pendingAction") or {}
        assert persisted_pending.get("bindingSnapshotId") == "binding-snapshot-1"
        assert persisted_pending.get("budgetPolicyHash") == "d" * 64

        # The declared channels survive reopen: a fresh coordinator reads the
        # same persisted state and build_pending_action reads non-empty.
        reopened = GraphHarness(tmp_path)
        try:
            reopened_values = dict(
                reopened.coordinator.snapshot("run-binding").get("values") or {}
            )
            assert reopened_values["binding_snapshot_id"] == "binding-snapshot-1"
            rebuilt = build_pending_action(reopened_values, "problem_understanding")
            assert rebuilt.binding_snapshot_id == "binding-snapshot-1"
            assert rebuilt.budget_policy_hash == "d" * 64
        finally:
            reopened.close()
    finally:
        harness.close()


def test_old_version_checkpoint_is_discarded_and_rebuilt_from_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A checkpoint written by an older schema version is never resumed.

    The stale thread is reported as absent to decision callers, and the next
    graph dispatch rebuilds the checkpoint from the Ledger dispatch identity
    (start_attempt path) instead of raising to the user.
    """

    harness = GraphHarness(tmp_path)
    try:
        # Produce a legacy fixture: checkpoint written by the old version 1.
        monkeypatch.setattr(challenge_cup_runtime, "CHALLENGE_CUP_CHECKPOINT_VERSION", 1)
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "problem_understanding", 1)
        harness.worker.run_once()
        stale = harness.coordinator.snapshot("run-test")
        stale_values = dict(stale.get("values") or {})
        assert stale_values.get("checkpoint_version") == 1
        stale_checkpoint_id = stale.get("checkpointId")
        assert stale_checkpoint_id
        assert harness.latest_adapter_pending() is not None

        monkeypatch.undo()

        # Decision callers no longer see the stale thread.
        discarded = harness.coordinator.snapshot("run-test")
        assert discarded.get("values") == {}
        assert discarded.get("nextNodeIds") == []
        assert discarded.get("pendingAction") is None
        assert discarded.get("checkpointDiscarded") is True

        # The worker rebuilds from Ledger authority instead of trusting the
        # stale checkpoint: the next start dispatch re-seeds the thread on a
        # fresh checkpoint with the current schema version.
        harness.enqueue_graph_dispatch(
            "run-test",
            "problem_understanding",
            1,
            command_id="cmd-rebuild",
            idempotency_key="rebuild-entry-1",
        )
        harness.worker.run_once()

        rebuilt = harness.coordinator.snapshot("run-test")
        rebuilt_values = dict(rebuilt.get("values") or {})
        assert (
            rebuilt_values.get("checkpoint_version")
            == challenge_cup_runtime.CHALLENGE_CUP_CHECKPOINT_VERSION
        )
        assert rebuilt.get("checkpointId")
        assert rebuilt.get("checkpointId") != stale_checkpoint_id
        rebuilt_pending = rebuilt.get("pendingAction") or {}
        assert rebuilt_pending.get("nodeId") == "problem_understanding"
        assert rebuilt_pending.get("actionId") == action_id_for(
            "run-test", "problem_understanding", 1
        )
    finally:
        monkeypatch.undo()
        harness.close()
