"""C7: formal runs join the active-work system with exclusive outputRoots.

Covers:
* work-run snapshot publication while a formal full run executes and cleanup
  once it reaches a terminal state (daemon restart guard sees it);
* fail-closed outputRoot exclusivity (same / nested / unreadable store);
* path normalization for Windows case-insensitive, mixed-separator roots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research import formal_runner
from core.runtime_manager import daemon, formal_run_registry, work_run_store
from core.web.services import team_service, team_workflow_orchestration_service
from tests._support.team_workflow.helpers import (
    _seed_formal_full_run_plan,
    _use_tmp_project_root,
)


def _use_tmp_work_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work-runs")


def _seed_team_with_formal_plan(tmp_path, monkeypatch) -> tuple[str, str]:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_work_runs(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    plan_id = _seed_formal_full_run_plan(team["teamId"])
    return team["teamId"], plan_id


def _execution_config(output_root: Path) -> dict[str, str]:
    return {
        "pythonExecutable": "C:/runner/python.exe",
        "dataRoot": "C:/data/fashionmnist",
        "outputRoot": str(output_root),
    }


def _completed_runner_result(output_root: Path, adapter_id: str) -> dict:
    return {
        "adapterId": adapter_id,
        "status": "completed",
        "seedCount": 3,
        "resultPath": str(output_root / "formal-run-result.json"),
        "logRef": str(output_root / "formal-run-log.json"),
        "requiresResultReview": True,
        "automaticPromotion": False,
    }


def _formal_work_run_store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def test_execute_full_run_publishes_and_clears_active_work_snapshot(tmp_path, monkeypatch):
    team_id, plan_id = _seed_team_with_formal_plan(tmp_path, monkeypatch)
    output_root = tmp_path / "formal-runs"
    observed: dict = {}

    def fake_run_full_run(adapter_id, **kwargs):
        observed["activeSnapshots"] = formal_run_registry.active_formal_run_snapshots()
        observed["daemonActiveWork"] = daemon._runtime_manager_active_work_runs()
        return _completed_runner_result(output_root, adapter_id)

    monkeypatch.setattr(
        team_workflow_orchestration_service.formal_runner,
        "run_full_run",
        fake_run_full_run,
    )

    response = team_workflow_orchestration_service.execute_experiment_full_run(
        team_id,
        plan_id,
        {"executionConfig": _execution_config(output_root)},
    )

    assert response["execution"]["status"] == "completed"
    execution_id = response["execution"]["executionId"]

    during = observed["activeSnapshots"]
    assert len(during) == 1
    snapshot = during[0]
    assert snapshot["runKind"] == formal_run_registry.FORMAL_RUN_WORK_KIND
    assert snapshot["status"] == "running"
    assert snapshot["runId"] == execution_id
    assert Path(snapshot["outputRoot"]) == output_root.resolve()
    assert snapshot["startedAt"]
    assert snapshot["planId"] == plan_id
    assert snapshot["teamId"] == team_id

    assert {
        "kind": formal_run_registry.FORMAL_RUN_WORK_KIND,
        "runId": execution_id,
        "status": "running",
        "sessionId": "",
    } in observed["daemonActiveWork"]

    # Terminal state clears the snapshot and the active index entry.
    assert formal_run_registry.active_formal_run_snapshots() == []
    store = _formal_work_run_store()
    assert store.load_snapshot(formal_run_registry.FORMAL_RUN_WORK_KIND, execution_id) is None
    index = store.load_run_index(formal_run_registry.FORMAL_RUN_WORK_KIND)
    assert index["activeRunId"] == ""


def test_execute_full_run_clears_snapshot_when_runner_fails(tmp_path, monkeypatch):
    team_id, plan_id = _seed_team_with_formal_plan(tmp_path, monkeypatch)
    output_root = tmp_path / "formal-runs"

    def failing_run(adapter_id, **kwargs):
        raise formal_runner.FormalRunnerError("seed 17 training exploded")

    monkeypatch.setattr(
        team_workflow_orchestration_service.formal_runner,
        "run_full_run",
        failing_run,
    )

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.execute_experiment_full_run(
            team_id,
            plan_id,
            {"executionConfig": _execution_config(output_root)},
        )

    assert formal_run_registry.active_formal_run_snapshots() == []
    assert _formal_work_run_store().list_snapshots(formal_run_registry.FORMAL_RUN_WORK_KIND) == []


def test_execute_full_run_rejects_overlapping_output_roots(tmp_path, monkeypatch):
    team_id, plan_id = _seed_team_with_formal_plan(tmp_path, monkeypatch)
    active_root = tmp_path / "formal-runs-active"
    formal_run_registry.register_active_formal_run(
        run_id="full-run-execution-existing",
        output_root=str(active_root),
        team_id="team-other",
        plan_id="plan-other",
    )

    runner_calls: list[str] = []

    def unexpected_run(adapter_id, **kwargs):
        runner_calls.append(str(adapter_id))
        return _completed_runner_result(active_root, adapter_id)

    monkeypatch.setattr(
        team_workflow_orchestration_service.formal_runner,
        "run_full_run",
        unexpected_run,
    )

    def _expect_conflict(config: dict, *, relationship: str) -> None:
        with pytest.raises(
            team_workflow_orchestration_service.TeamWorkflowOrchestrationError
        ) as error:
            team_workflow_orchestration_service.execute_experiment_full_run(
                team_id, plan_id, {"executionConfig": config}
            )
        message = str(error.value)
        assert "full-run-execution-existing" in message
        assert relationship in message
        assert "Formal run outputRoot conflict" in message

    # Same outputRoot.
    _expect_conflict(_execution_config(active_root), relationship="same")
    # Nested child of the active root.
    _expect_conflict(_execution_config(active_root / "seed-parent"), relationship="nested")
    # Requested root containing the active root.
    _expect_conflict(_execution_config(tmp_path), relationship="nested")
    # Windows case-insensitive / mixed-separator normalization.
    variant = str(active_root).replace("formal-runs-active", "FORMAL-RUNS-ACTIVE")
    _expect_conflict(_execution_config(Path(variant.replace("\\", "/"))), relationship="same")

    assert runner_calls == []
    plan_store = team_workflow_orchestration_service._load_experiment_plan_store(team_id)
    plan = next(item for item in plan_store["plans"] if item["planId"] == plan_id)
    assert plan["status"] != "full_run_running"
    assert [
        item["runId"] for item in formal_run_registry.active_formal_run_snapshots()
    ] == ["full-run-execution-existing"]


def test_execute_full_run_allows_distinct_output_roots(tmp_path, monkeypatch):
    team_id, plan_id = _seed_team_with_formal_plan(tmp_path, monkeypatch)
    active_root = tmp_path / "formal-runs-active"
    formal_run_registry.register_active_formal_run(
        run_id="full-run-execution-existing",
        output_root=str(active_root),
    )
    other_root = tmp_path / "formal-runs-other"
    observed: dict = {}

    def fake_run_full_run(adapter_id, **kwargs):
        observed["activeDuringRun"] = [
            item["runId"] for item in formal_run_registry.active_formal_run_snapshots()
        ]
        return _completed_runner_result(other_root, adapter_id)

    monkeypatch.setattr(
        team_workflow_orchestration_service.formal_runner,
        "run_full_run",
        fake_run_full_run,
    )

    response = team_workflow_orchestration_service.execute_experiment_full_run(
        team_id,
        plan_id,
        {"executionConfig": _execution_config(other_root)},
    )

    assert response["execution"]["status"] == "completed"
    # Both runs were visible while the second one executed.
    assert set(observed["activeDuringRun"]) == {
        "full-run-execution-existing",
        response["execution"]["executionId"],
    }
    # The unrelated active run is untouched by the second run's lifecycle.
    assert [
        item["runId"] for item in formal_run_registry.active_formal_run_snapshots()
    ] == ["full-run-execution-existing"]


def test_execute_full_run_fails_closed_when_active_runs_unreadable(tmp_path, monkeypatch):
    team_id, plan_id = _seed_team_with_formal_plan(tmp_path, monkeypatch)

    def broken_store():
        raise OSError("snapshot store unavailable")

    monkeypatch.setattr(formal_run_registry, "_store", broken_store)

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError
    ) as error:
        team_workflow_orchestration_service.execute_experiment_full_run(
            team_id,
            plan_id,
            {"executionConfig": _execution_config(tmp_path / "formal-runs")},
        )

    assert "Unable to inspect active formal runs" in str(error.value)


def test_output_root_relationship_normalizes_windows_paths():
    assert formal_run_registry.output_root_relationship("C:/A\\B", "c:/a/b") == "same"
    assert formal_run_registry.output_root_relationship("C:/A", "c:/a/b") == "nested"
    assert formal_run_registry.output_root_relationship("c:/a/b", "C:/A") == "nested"
    assert formal_run_registry.output_root_relationship("c:/a/bb", "c:/a/b") == ""
    assert formal_run_registry.output_root_relationship("c:/x", "c:/y") == ""
    assert formal_run_registry.output_root_relationship("", "c:/y") == ""


def test_active_work_probe_tolerates_absent_formal_run_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work-runs")

    assert daemon._runtime_manager_active_work_runs() == []
