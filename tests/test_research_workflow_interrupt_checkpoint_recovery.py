"""Regression coverage for persisted interrupts whose task queue is empty."""

from __future__ import annotations

import json
from pathlib import Path

from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def test_retry_uses_persisted_interrupt_when_checkpoint_next_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        harness.worker.run_once()
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

        def persisted_interrupt_snapshot(run_id: str):
            snapshot = dict(original_snapshot(run_id))
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
