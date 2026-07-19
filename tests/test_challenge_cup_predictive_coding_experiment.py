from __future__ import annotations

import subprocess
import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "experiments" / "challenge_cup_predictive_coding" / "fashion_mnist_smoke.py"
EXPERIMENT_PYTHON = Path(
    r"C:\Users\17533\Documents\Vibelution\data\experiments\predictive_coding_mnist\.venv\Scripts\python.exe"
)


def _load_experiment_module():
    spec = importlib.util.spec_from_file_location("fashion_mnist_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_negligible_improvement_remains_inconclusive() -> None:
    module = _load_experiment_module()
    decision = module.classify_decision(
        {"delta": {"mse_improvement": 0.00000562, "latency_multiplier": 3.96}},
        module.ExperimentConfig(),
    )
    assert decision["status"] == "inconclusive"
    assert decision["improvementPassed"] is False
    assert decision["latencyPassed"] is True


def test_masked_prediction_error_gate_uses_masked_gain_and_global_regression_guard() -> None:
    module = _load_experiment_module()
    config = module.ExperimentConfig(
        candidate_mechanism=module.MASKED_PREDICTION_ERROR_TRAINING,
        maximum_latency_multiplier=1.25,
    )
    decision = module.classify_decision(
        {
            "delta": {
                "mse_improvement": -0.0002,
                "masked_mse_improvement": 0.002,
                "latency_multiplier": 1.05,
            }
        },
        config,
    )
    assert decision["status"] == "support"
    assert decision["primaryImprovementMetric"] == "masked_mse_improvement"
    assert decision["globalRegressionPassed"] is True

    regressed = module.classify_decision(
        {
            "delta": {
                "mse_improvement": -0.001,
                "masked_mse_improvement": 0.002,
                "latency_multiplier": 1.05,
            }
        },
        config,
    )
    assert regressed["status"] == "inconclusive"
    assert regressed["globalRegressionPassed"] is False


def test_stable_metric_payload_excludes_runtime_timing() -> None:
    module = _load_experiment_module()
    metrics = {
        "baseline": {"reconstruction_mse": 0.04, "masked_region_mse": 0.05, "seconds": 0.1},
        "variant": {"reconstruction_mse": 0.03, "masked_region_mse": 0.04, "seconds": 0.5},
        "delta": {"mse_improvement": 0.01, "masked_mse_improvement": 0.01, "latency_multiplier": 5.0},
        "test_samples": 128,
    }
    stable = module.stable_metric_payload(metrics)
    assert "seconds" not in stable["baseline"]
    assert "latency_multiplier" not in stable["delta"]


def test_evaluate_candidate_matrix_reuses_trained_models_across_mask_sizes(monkeypatch) -> None:
    module = _load_experiment_module()
    baseline_model = object()
    candidate_model = object()
    test_loader = object()
    config = module.ExperimentConfig(mask_size=8)
    calls: list[tuple[object, object, object, int]] = []

    def fake_evaluate(baseline, candidate, loader, current_config, *, evaluation_mask_size=None):
        calls.append((baseline, candidate, loader, evaluation_mask_size))
        return {
            "delta": {
                "mse_improvement": evaluation_mask_size / 10000,
                "masked_mse_improvement": evaluation_mask_size / 1000,
                "latency_multiplier": 1.0,
            }
        }

    monkeypatch.setattr(module, "_evaluate_models", fake_evaluate)

    matrix = module.evaluate_candidate_across_mask_sizes(
        baseline_model,
        candidate_model,
        test_loader,
        config,
        evaluation_mask_sizes=[4, 8, 12],
    )

    assert [entry["maskSize"] for entry in matrix] == [4, 8, 12]
    assert [entry["metrics"]["delta"]["masked_mse_improvement"] for entry in matrix] == [0.004, 0.008, 0.012]
    assert all(call[:3] == (baseline_model, candidate_model, test_loader) for call in calls)
    assert [call[3] for call in calls] == [4, 8, 12]


def test_fashion_mnist_experiment_self_check() -> None:
    if not EXPERIMENT_PYTHON.exists():
        pytest.skip("isolated Challenge Cup experiment environment is not installed")
    completed = subprocess.run(
        [str(EXPERIMENT_PYTHON), str(SCRIPT), "--self-check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"status": "ok"' in completed.stdout
    assert '"baselineShape": [2, 1, 28, 28]' in completed.stdout
    assert '"lossMaskControl": "ok"' in completed.stdout
    assert '"deterministically_permuted"' in completed.stdout
