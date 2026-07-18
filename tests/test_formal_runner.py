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
