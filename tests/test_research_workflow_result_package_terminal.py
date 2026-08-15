"""Close the Challenge Cup run after result_package already succeeded."""

from __future__ import annotations

from pathlib import Path

from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
)


def test_repair_closes_run_after_result_package_succeeded(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        run_id = "run-pkg-terminal"
        harness.seed(run_id=run_id, status="running")

        def mutate(uow):
            uow.repository.execute(
                "UPDATE workflow_runs SET active_node_id = ? WHERE run_id = ?",
                ("result_package", run_id),
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-pkg",
                    run_id=run_id,
                    node_id="result_package",
                    command_kind="retry_node",
                    idempotency_key="retry:result_package:2",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id=f"nr-{run_id}-result_package-a2",
                    run_id=run_id,
                    node_id="result_package",
                    attempt=2,
                    actor_kind="system",
                    status="succeeded",
                    command_id="cmd-pkg",
                    started_at_ms=FIXED_NOW_MS,
                )
            )

        harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)
        repaired = harness.worker.run_once()
        assert repaired >= 1
        run = harness.commands.store.get_run(run_id)
        assert run is not None
        assert run.status == "succeeded"
        assert run.completion_kind == "stopped"
        assert run.terminal_reason == "formal_runner_unavailable"
        assert not str(run.active_node_id or "").strip()
        assert run.completed_at_ms is not None
        assert harness.worker.run_once() >= 0
        again = harness.commands.store.get_run(run_id)
        assert again is not None
        assert again.status == "succeeded"
    finally:
        harness.close()
