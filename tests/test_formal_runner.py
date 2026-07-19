from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.research import formal_runner


def _execution_config(tmp_path: Path, project_root: Path) -> dict[str, object]:
    python_executable = tmp_path / "python.exe"
    python_executable.write_text("placeholder", encoding="utf-8")
    data_root = tmp_path / "fashion-data"
    data_root.mkdir()
    return {
        "pythonExecutable": str(python_executable),
        "dataRoot": str(data_root),
        "outputRoot": str(tmp_path / "formal-runs"),
        "epochs": 2,
        "trainSamples": 512,
        "testSamples": 128,
        "timeoutSeconds": 120,
    }


def _method_config() -> dict[str, object]:
    return {
        "seeds": [17, 42, 101],
        "candidateMechanism": "masked_prediction_error_training",
        "candidateMaskedLossWeight": 4.0,
        "candidateLossMaskMode": "deterministically_permuted",
        "maximumLatencyMultiplier": 1.25,
    }


def test_prepare_full_run_requires_explicit_external_environment_and_builds_fixed_commands(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    script_path = project_root / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# trusted runner placeholder", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.setattr(formal_runner.subprocess, "run", fake_run)

    prepared = formal_runner.prepare_full_run(
        formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER,
        method_config=_method_config(),
        execution_config=_execution_config(tmp_path, project_root),
        project_root=project_root,
    )

    assert prepared["status"] == "prepared"
    assert prepared["adapterId"] == formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER
    assert prepared["executionMode"] == "local_process"
    assert prepared["seedCount"] == 3
    assert [item["seed"] for item in prepared["commands"]] == [17, 42, 101]
    assert all("--seed" in item["args"] for item in prepared["commands"])
    assert all("masked_prediction_error_training" in item["args"] for item in prepared["commands"])
    assert all("--candidate-loss-mask-mode" in item["args"] for item in prepared["commands"])
    assert all("deterministically_permuted" in item["args"] for item in prepared["commands"])
    assert prepared["runOptions"]["candidateLossMaskMode"] == "deterministically_permuted"
    assert prepared["runOptions"]["maximumLatencyMultiplier"] == 1.25
    assert calls == [[str(tmp_path / "python.exe"), str(script_path), "--self-check"]]
    assert "user_triggered_only" in prepared["boundaries"]
    assert "manual_result_review_required" in prepared["boundaries"]


def test_prepare_full_run_rejects_unknown_candidate_loss_mask_mode(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    script_path = project_root / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# trusted runner placeholder", encoding="utf-8")
    method_config = _method_config()
    method_config["candidateLossMaskMode"] = "random"

    with pytest.raises(formal_runner.FormalRunnerError, match="candidateLossMaskMode"):
        formal_runner.prepare_full_run(
            formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER,
            method_config=method_config,
            execution_config=_execution_config(tmp_path, project_root),
            project_root=project_root,
        )


def test_prepare_full_run_rejects_repository_local_artifacts_before_spawning_a_process(tmp_path):
    project_root = tmp_path / "project"
    script_path = project_root / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# trusted runner placeholder", encoding="utf-8")
    execution_config = _execution_config(tmp_path, project_root)
    execution_config["outputRoot"] = str(project_root / "artifacts")

    with pytest.raises(formal_runner.FormalRunnerError, match="outside the repository"):
        formal_runner.prepare_full_run(
            formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER,
            method_config=_method_config(),
            execution_config=execution_config,
            project_root=project_root,
        )


def test_prepare_full_run_reports_a_bounded_self_check_timeout(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    script_path = project_root / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# trusted runner placeholder", encoding="utf-8")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(formal_runner.subprocess, "run", fake_run)

    with pytest.raises(formal_runner.FormalRunnerError, match="timed out"):
        formal_runner.prepare_full_run(
            formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER,
            method_config=_method_config(),
            execution_config=_execution_config(tmp_path, project_root),
            project_root=project_root,
        )


def test_run_full_run_aggregates_fixed_seed_artifacts_without_promoting_a_research_conclusion(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    script_path = project_root / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# trusted runner placeholder", encoding="utf-8")
    executions: list[list[str]] = []

    def fake_run(args, **kwargs):
        command = list(args)
        executions.append(command)
        if "--self-check" in command:
            return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")
        output_dir = Path(command[command.index("--output-dir") + 1])
        seed = int(command[command.index("--seed") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "artifactHash": f"sha256:seed-{seed}",
            "metrics": {
                "delta": {"mse_improvement": seed / 10000, "masked_mse_improvement": seed / 20000},
                "variant": {"reconstruction_mse": 0.2},
            },
            "decision": {"status": "support"},
        }
        (output_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(result), stderr="")

    monkeypatch.setattr(formal_runner.subprocess, "run", fake_run)

    result = formal_runner.run_full_run(
        formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER,
        method_config=_method_config(),
        execution_config=_execution_config(tmp_path, project_root),
        project_root=project_root,
    )

    assert result["status"] == "completed"
    assert result["seedCount"] == 3
    assert result["aggregate"]["mseImprovement"]["mean"] == pytest.approx((0.0017 + 0.0042 + 0.0101) / 3)
    assert Path(result["resultPath"]).is_file()
    assert Path(result["logRef"]).is_file()
    assert result["requiresResultReview"] is True
    assert result["automaticPromotion"] is False
    assert len(executions) == 4


def test_prepare_full_run_builds_one_shared_baseline_matrix_command_per_seed(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    script_path = project_root / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# trusted runner placeholder", encoding="utf-8")

    monkeypatch.setattr(
        formal_runner.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout='{"status":"ok"}', stderr=""),
    )
    method_config = _method_config()
    method_config["seeds"] = [211, 487, 809, 1201, 1879]
    execution_config = _execution_config(tmp_path, project_root)
    execution_config.update(
        {
            "trainingMaskSize": 8,
            "evaluationMaskSizes": [4, 8, 12],
            "candidateLossMaskModes": ["aligned", "deterministically_permuted"],
        }
    )

    prepared = formal_runner.prepare_full_run(
        formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER,
        method_config=method_config,
        execution_config=execution_config,
        project_root=project_root,
    )

    assert prepared["seedCount"] == 5
    assert len(prepared["commands"]) == 5
    assert prepared["runOptions"]["trainingMaskSize"] == 8
    assert prepared["runOptions"]["evaluationMaskSizes"] == [4, 8, 12]
    assert prepared["runOptions"]["candidateLossMaskModes"] == ["aligned", "deterministically_permuted"]
    for command in prepared["commands"]:
        assert command["args"].count("--candidate-loss-mask-modes") == 1
        modes_index = command["args"].index("--candidate-loss-mask-modes")
        assert command["args"][modes_index + 1 : modes_index + 3] == ["aligned", "deterministically_permuted"]
        sizes_index = command["args"].index("--evaluation-mask-sizes")
        assert command["args"][sizes_index + 1 : sizes_index + 4] == ["4", "8", "12"]


def test_run_full_run_aggregates_severity_and_control_matrix(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    script_path = project_root / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("# trusted runner placeholder", encoding="utf-8")
    executions: list[list[str]] = []

    def fake_run(args, **kwargs):
        command = list(args)
        executions.append(command)
        if "--self-check" in command:
            return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")
        output_dir = Path(command[command.index("--output-dir") + 1])
        seed = int(command[command.index("--seed") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        matrix = []
        for mode, offset in (("aligned", 0.002), ("deterministically_permuted", 0.001)):
            for mask_size in (4, 8, 12):
                masked_gain = offset + seed / 1_000_000 + mask_size / 100_000
                matrix.append(
                    {
                        "candidateLossMaskMode": mode,
                        "maskSize": mask_size,
                        "metrics": {
                            "delta": {
                                "mse_improvement": 0.0001,
                                "masked_mse_improvement": masked_gain,
                                "latency_multiplier": 0.9,
                            }
                        },
                        "decision": {"status": "support"},
                    }
                )
        result = {
            "artifactHash": f"sha256:seed-{seed}",
            "metrics": matrix[1]["metrics"],
            "decision": matrix[1]["decision"],
            "comparisonMatrix": matrix,
            "sharedBaseline": True,
        }
        (output_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(result), stderr="")

    monkeypatch.setattr(formal_runner.subprocess, "run", fake_run)
    method_config = _method_config()
    method_config["seeds"] = [211, 487, 809]
    execution_config = _execution_config(tmp_path, project_root)
    execution_config.update(
        {
            "trainingMaskSize": 8,
            "evaluationMaskSizes": [4, 8, 12],
            "candidateLossMaskModes": ["aligned", "deterministically_permuted"],
        }
    )

    result = formal_runner.run_full_run(
        formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER,
        method_config=method_config,
        execution_config=execution_config,
        project_root=project_root,
    )

    assert len(executions) == 4
    assert result["sharedBaseline"] is True
    cells = {
        (cell["candidateLossMaskMode"], cell["maskSize"]): cell
        for cell in result["benchmarkMatrix"]["cells"]
    }
    assert set(cells) == {
        ("aligned", 4),
        ("aligned", 8),
        ("aligned", 12),
        ("deterministically_permuted", 4),
        ("deterministically_permuted", 8),
        ("deterministically_permuted", 12),
    }
    assert cells[("aligned", 8)]["maskedMseImprovement"]["count"] == 3
    assert cells[("aligned", 8)]["maskedMseImprovement"]["confidenceInterval95"]["method"] == "normal_approximation"
    contrasts = {item["maskSize"]: item for item in result["benchmarkMatrix"]["alignedMinusPermuted"]}
    assert contrasts[8]["maskedMseImprovement"]["mean"] == pytest.approx(0.001)
