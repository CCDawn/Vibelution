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
