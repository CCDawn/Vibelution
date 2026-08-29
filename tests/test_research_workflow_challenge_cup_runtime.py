"""Regression coverage for LangGraph retry input protocol."""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.challenge_cup_runtime import GraphDispatch, action_id_for
from core.research.workflow.contracts import ExecutionReceipt
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def test_retry_attempt_from_terminal_checkpoint_rebuilds_interrupt(
    tmp_path: Path,
) -> None:
    """A retry on a failed END checkpoint must schedule the target node.

    ``Command(goto=...)`` is accepted by LangGraph as an input shape, but it
    does not create a task when the thread already reached END.  The runtime
    must fork/update the checkpoint at the target's predecessor and continue
    with a normal ``invoke(None, config)`` superstep.
    """

    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        pending = harness.start_thread_to("source_finding")
        assert pending is not None
        payload = json.loads(pending.payload_json)
        harness.consume_adapter(pending.action_id)
        receipt = ExecutionReceipt(
            action_id=str(payload["actionId"]),
            node_run_id=str(payload["nodeRunId"]),
            outcome="failed",
            artifact_receipt_ids=(),
            execution_anchor_id=None,
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=FIXED_NOW_MS,
        )

        failed = harness.coordinator.resume_action(
            GraphDispatch(
                action_id=receipt.action_id,
                run_id="run-test",
                node_run_id=receipt.node_run_id,
                node_id="source_finding",
                attempt=1,
                dispatch_kind="resume_action",
                team_id="research-team",
                receipt=receipt,
            )
        )
        assert failed.completed is True
        assert failed.pending_action is None

        retried = harness.coordinator.retry_attempt(
            GraphDispatch(
                action_id="act-retry-driver",
                run_id="run-test",
                node_run_id="nr-run-test-source_finding-a2",
                node_id="source_finding",
                attempt=2,
                dispatch_kind="start",
                team_id="research-team",
            )
        )

        assert retried.pending_action is not None
        assert retried.pending_action.node_id == "source_finding"
        assert retried.pending_action.attempt == 2
        assert retried.pending_action.action_id == action_id_for(
            "run-test", "source_finding", 2
        )
        assert harness.coordinator.snapshot("run-test")["nextNodeIds"] == [
            "source_finding"
        ]
    finally:
        harness.close()


def test_enter_node_from_terminal_checkpoint_rebuilds_target_interrupt(
    tmp_path: Path,
) -> None:
    """Enter must use the same checkpoint scheduling protocol as retry."""

    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        pending = harness.start_thread_to("source_finding")
        assert pending is not None
        payload = json.loads(pending.payload_json)
        harness.consume_adapter(pending.action_id)
        receipt = ExecutionReceipt(
            action_id=str(payload["actionId"]),
            node_run_id=str(payload["nodeRunId"]),
            outcome="failed",
            artifact_receipt_ids=(),
            execution_anchor_id=None,
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=FIXED_NOW_MS,
        )
        harness.coordinator.resume_action(
            GraphDispatch(
                action_id=receipt.action_id,
                run_id="run-test",
                node_run_id=receipt.node_run_id,
                node_id="source_finding",
                attempt=1,
                dispatch_kind="resume_action",
                team_id="research-team",
                receipt=receipt,
            )
        )

        entered = harness.coordinator.enter_node(
            GraphDispatch(
                action_id="act-enter-driver",
                run_id="run-test",
                node_run_id="nr-run-test-source_extraction-a2",
                node_id="source_extraction",
                attempt=2,
                dispatch_kind="start",
                team_id="research-team",
            )
        )

        assert entered.pending_action is not None
        assert entered.pending_action.node_id == "source_extraction"
        assert entered.pending_action.attempt == 2
    finally:
        harness.close()
