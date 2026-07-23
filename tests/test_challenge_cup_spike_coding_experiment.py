from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PROJECT_ROOT
    / "experiments"
    / "challenge_cup_spike_coding"
    / "sci096_dandi_probe.py"
)


def _load_experiment_module():
    spec = importlib.util.spec_from_file_location("sci096_dandi_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_result_classification_requires_rate_and_shuffle_margin() -> None:
    module = _load_experiment_module()
    config = module.ProbeConfig()

    supported = module.classify_result(
        {"balanced_accuracy": 0.50},
        {"balanced_accuracy": 0.62},
        [0.48, 0.50, 0.52],
        config,
    )
    weak_control = module.classify_result(
        {"balanced_accuracy": 0.50},
        {"balanced_accuracy": 0.62},
        [0.55, 0.56, 0.57],
        config,
    )

    assert supported["status"] == "supports_context_adaptive_multiplexing"
    assert weak_control["status"] == "inconclusive_tends_minimal_statistics"


def test_rate_advantage_branches_to_minimal_statistics_competitor() -> None:
    module = _load_experiment_module()
    decision = module.classify_result(
        {"balanced_accuracy": 0.64},
        {"balanced_accuracy": 0.50},
        [0.48, 0.49, 0.51],
        module.ProbeConfig(),
    )
    assert decision["status"] == "supports_conditional_minimal_statistics_in_primary_window"
    assert decision["decision"] == "BRANCH"


def test_stable_metrics_remove_trial_level_predictions() -> None:
    module = _load_experiment_module()
    stable = module._stable_metrics(
        {
            "accuracy": 0.5,
            "validation_correct": [1, 0],
            "validation_predictions": [1, 1],
            "validation_truth": [1, 0],
        }
    )
    assert stable == {"accuracy": 0.5}
