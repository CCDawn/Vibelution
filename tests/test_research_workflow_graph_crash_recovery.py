"""T4 RED: crash recovery — checkpoint restart yields the same actionId,
re-dispatch never duplicates adapter work, retry re-enters with a new
attempt."""

from __future__ import annotations

import json
from pathlib import Path

from tests._support.graph_helpers import GraphHarness


def test_crash_after_interrupt_redispatch_reuses_same_action_id(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        harness.worker.run_once()
        first_pending = harness.latest_adapter_pending()
        assert first_pending is not None
        first_action_id = json.loads(first_pending.payload_json)["actionId"]

        # 模拟崩溃：adapter outbox 尚未消费，graph_dispatch 重新领取。
        harness.enqueue_graph_dispatch(
            "run-test", "source_finding", 1, idempotency_key="graph-redispatch"
        )
        handled = harness.worker.run_once()
        assert handled == 1
        pending_rows = harness.commands.store.list_pending_outbox("run-test")
        adapter_rows = [row for row in pending_rows if row.action_kind == "adapter_dispatch"]
        assert len(adapter_rows) == 1
        assert json.loads(adapter_rows[0].payload_json)["actionId"] == first_action_id
        # 不产生第二个 adapter 任务（幂等键抑制）。
        attempts = harness.commands.store.list_attempts("run-test")
        assert len(attempts) == 1
    finally:
        harness.close()


def test_retry_creates_new_action_id_and_new_attempt(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        harness.worker.run_once()
        first_pending = harness.latest_adapter_pending()
        first_action_id = json.loads(first_pending.payload_json)["actionId"]

        # 第一次尝试失败（failed receipt）。
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
            outcome="failed",
        )
        harness.worker.run_once()
        attempts = harness.commands.store.list_attempts("run-test")
        assert attempts[0].status == "failed"

        # retry: attempt 2 的 start dispatch 重入节点并产生新 actionId。
        harness.enqueue_graph_dispatch("run-test", "source_finding", 2)
        harness.worker.run_once()
        pending = harness.latest_adapter_pending()
        assert pending is not None
        payload = json.loads(pending.payload_json)
        assert int(payload["attempt"]) == 2
        assert payload["actionId"] != first_action_id
        attempts = harness.commands.store.list_attempts("run-test")
        assert {attempt.attempt for attempt in attempts} == {1, 2}
        retry = next(attempt for attempt in attempts if attempt.attempt == 2)
        assert retry.status == "dispatching"
    finally:
        harness.close()


def test_restart_after_worker_crash_resumes_same_thread(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        harness.worker.run_once()
        first_pending = harness.latest_adapter_pending()
        first_action_id = json.loads(first_pending.payload_json)["actionId"]

        # 新 worker（新进程语义）在同一 checkpoint 上继续。
        from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
        from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
            GraphDispatchWorker,
        )

        worker2 = GraphDispatchWorker(
            store=harness.commands.store,
            coordinator=ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite"),
            owner_id="graph-worker-2",
        )
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=first_action_id,
        )
        harness.consume_adapter(first_pending.action_id)
        handled = worker2.run_once()
        assert handled == 1
        pending = harness.latest_adapter_pending()
        assert pending is not None
        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "source_extraction"
    finally:
        harness.close()
