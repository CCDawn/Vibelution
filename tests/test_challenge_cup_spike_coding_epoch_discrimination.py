from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = PROJECT_ROOT / "experiments" / "challenge_cup_spike_coding"
SCRIPT = EXPERIMENT_DIR / "sci096_epoch_discrimination.py"


def _load_experiment_module():
    sys.path.insert(0, str(EXPERIMENT_DIR))
    spec = importlib.util.spec_from_file_location("sci096_epoch_discrimination", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_decision_requires_all_preregistered_gates() -> None:
    module = _load_experiment_module()
    supported = module.classify_epoch_result(
        stationary_rate_balanced=0.50,
        stationary_temporal_balanced=0.52,
        transition_rate_balanced=0.50,
        transition_temporal_balanced=0.65,
        transition_shuffle_mean_balanced=0.54,
        interaction={"delta": 0.13, "ci95_low": 0.02, "ci95_high": 0.24},
        minimum_supported_delta=0.08,
    )
    weak_interaction_ci = module.classify_epoch_result(
        stationary_rate_balanced=0.50,
        stationary_temporal_balanced=0.52,
        transition_rate_balanced=0.50,
        transition_temporal_balanced=0.65,
        transition_shuffle_mean_balanced=0.54,
        interaction={"delta": 0.13, "ci95_low": 0.0, "ci95_high": 0.24},
        minimum_supported_delta=0.08,
    )

    assert supported["status"] == "supports_state_conditioned_temporal_utility"
    assert supported["decision"] == "CONTINUE"
    assert weak_interaction_ci["status"] == "inconclusive"
    assert weak_interaction_ci["decision"] == "BRANCH"


def test_nonpositive_transition_and_interaction_do_not_support_hypothesis() -> None:
    module = _load_experiment_module()
    result = module.classify_epoch_result(
        stationary_rate_balanced=0.50,
        stationary_temporal_balanced=0.54,
        transition_rate_balanced=0.60,
        transition_temporal_balanced=0.58,
        transition_shuffle_mean_balanced=0.55,
        interaction={"delta": -0.06, "ci95_low": -0.20, "ci95_high": 0.08},
        minimum_supported_delta=0.08,
    )

    assert result["status"] == "does_not_support_state_conditioned_temporal_utility"
    assert result["decision"] == "BRANCH"


def test_interaction_bootstrap_uses_class_stratified_balanced_differences() -> None:
    module = _load_experiment_module()
    result = module.bootstrap_balanced_interaction_delta(
        validation_truth=[0, 0, 1, 1],
        transition_temporal_correct=[1, 1, 1, 1],
        transition_rate_correct=[0, 0, 0, 0],
        stationary_temporal_correct=[1, 0, 1, 0],
        stationary_rate_correct=[1, 0, 1, 0],
        seed=7,
        repeats=500,
    )

    assert result["delta"] == 1.0
    assert result["ci95_low"] == 1.0
    assert result["ci95_high"] == 1.0


def test_protocol_freezes_stationary_and_transition_windows() -> None:
    module = _load_experiment_module()

    assert module.STATIONARY_WINDOW == (-0.5, 0.0)
    assert module.TRANSITION_WINDOW == (0.0, 0.25)
    assert module.EpochDiscriminationConfig().minimum_supported_delta == 0.08
