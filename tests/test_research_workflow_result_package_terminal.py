"""Close the Challenge Cup run after result_package already succeeded."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.block_projection import (
    terminal_facts_for_run,
)
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    put_workflow_artifact,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
)


def _use_artifact_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)


def _seed_succeeded_package(harness: GraphHarness, run_id: str) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET active_node_id = ? WHERE run_id = ?",
            ("result_package", run_id),
        )
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{run_id}",
                run_id=run_id,
                node_id="result_package",
                command_kind="retry_node",
                idempotency_key=f"retry:result_package:{run_id}",
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
                command_id=f"cmd-{run_id}",
                started_at_ms=FIXED_NOW_MS,
            )
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def test_repair_closes_run_after_result_package_succeeded(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        run_id = "run-pkg-terminal"
        harness.seed(run_id=run_id, status="running")
        _seed_succeeded_package(harness, run_id)
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


def test_terminal_facts_promote_is_not_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    put_workflow_artifact(
        "research-team",
        kind="version_governance_record",
        workflow_run_id="run-promote-facts",
        source_collection_run_id="run-promote-facts",
        artifact_identity="gov-promote",
        payload={"operation": "promote_candidate", "status": "proposed"},
    )
    run = SimpleNamespace(
        run_id="run-promote-facts",
        team_id="research-team",
        input_snapshot_json=json.dumps(
            {"teamId": "research-team", "sourceCollectionRunId": "run-promote-facts"}
        ),
    )
    kind, reason = terminal_facts_for_run(run)
    assert kind == "promoted"
    assert reason != "formal_runner_unavailable"


def test_repair_closes_promote_package_as_promoted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    run_id = "run-pkg-promote"
    put_workflow_artifact(
        "research-team",
        kind="version_governance_record",
        workflow_run_id=run_id,
        source_collection_run_id=run_id,
        artifact_identity="gov-promote-close",
        payload={"operation": "promote_candidate", "status": "proposed"},
    )
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id=run_id, status="running")
        _seed_succeeded_package(harness, run_id)
        repaired = harness.worker.run_once()
        assert repaired >= 1
        run = harness.commands.store.get_run(run_id)
        assert run is not None
        assert run.status == "succeeded"
        assert run.completion_kind == "promoted"
        assert run.terminal_reason != "formal_runner_unavailable"
    finally:
        harness.close()
