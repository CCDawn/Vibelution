"""Preregistered stationary-vs-transition discrimination for SCI-096.

This bounded experiment tests whether temporal spike features add more offline
decoding information during a movement-transition epoch than during a
stationary preparatory epoch. It does not establish a biological readout or a
universal neural code.
"""

from __future__ import annotations

import argparse
import json
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci096_dandi_probe import (
    ProbeConfig,
    _scientific_modules,
    _stable_metrics,
    binned_spike_features,
    bootstrap_paired_accuracy_delta,
    count_preserving_temporal_shuffle,
    evaluate_features,
    load_dataset,
    sha256_file,
)


STATIONARY_WINDOW = (-0.5, 0.0)
TRANSITION_WINDOW = (0.0, 0.25)


@dataclass(frozen=True)
class EpochDiscriminationConfig:
    seed: int = 20260723
    time_bins: int = 5
    pca_components: int = 20
    logistic_c: float = 1.0
    shuffle_repeats: int = 10
    bootstrap_repeats: int = 10_000
    minimum_supported_delta: float = 0.08

    def probe_config(self) -> ProbeConfig:
        return ProbeConfig(
            seed=self.seed,
            primary_time_bins=self.time_bins,
            pca_components=self.pca_components,
            logistic_c=self.logistic_c,
            shuffle_repeats=self.shuffle_repeats,
            bootstrap_repeats=self.bootstrap_repeats,
            minimum_supported_delta=self.minimum_supported_delta,
        )


def bootstrap_balanced_interaction_delta(
    validation_truth: list[int],
    transition_temporal_correct: list[int],
    transition_rate_correct: list[int],
    stationary_temporal_correct: list[int],
    stationary_rate_correct: list[int],
    *,
    seed: int,
    repeats: int,
) -> dict[str, float]:
    import numpy as np

    arrays = [
        np.asarray(values, dtype=float)
        for values in (
            validation_truth,
            transition_temporal_correct,
            transition_rate_correct,
            stationary_temporal_correct,
            stationary_rate_correct,
        )
    ]
    lengths = {len(values) for values in arrays}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        raise ValueError("interaction bootstrap requires equal non-empty correctness vectors")
    truth = arrays[0].astype(int)
    per_trial = (arrays[1] - arrays[2]) - (arrays[3] - arrays[4])
    classes = np.unique(truth)

    def balanced_mean(values) -> float:
        return float(np.mean([values[truth == label].mean() for label in classes]))

    rng = np.random.default_rng(seed)
    samples = np.empty(repeats, dtype=float)
    for index in range(repeats):
        class_means = []
        for label in classes:
            class_values = per_trial[truth == label]
            sampled_indices = rng.integers(0, len(class_values), size=len(class_values))
            class_means.append(class_values[sampled_indices].mean())
        samples[index] = np.mean(class_means)
    return {
        "delta": round(balanced_mean(per_trial), 6),
        "ci95_low": round(float(np.quantile(samples, 0.025)), 6),
        "ci95_high": round(float(np.quantile(samples, 0.975)), 6),
    }


def classify_epoch_result(
    *,
    stationary_rate_balanced: float,
    stationary_temporal_balanced: float,
    transition_rate_balanced: float,
    transition_temporal_balanced: float,
    transition_shuffle_mean_balanced: float,
    interaction: dict[str, float],
    minimum_supported_delta: float,
) -> dict[str, Any]:
    stationary_delta = stationary_temporal_balanced - stationary_rate_balanced
    transition_delta = transition_temporal_balanced - transition_rate_balanced
    transition_control_delta = transition_temporal_balanced - transition_shuffle_mean_balanced
    gates = {
        "transition_temporal_vs_rate": transition_delta >= minimum_supported_delta,
        "transition_temporal_vs_shuffle": transition_control_delta >= minimum_supported_delta,
        "transition_vs_stationary_interaction": interaction["delta"] >= minimum_supported_delta,
        "interaction_ci_excludes_zero": interaction["ci95_low"] > 0.0,
        "stationary_temporal_gain_below_threshold": stationary_delta < minimum_supported_delta,
    }
    if all(gates.values()):
        status = "supports_state_conditioned_temporal_utility"
        decision = "CONTINUE"
    elif transition_delta <= 0.0 and interaction["delta"] <= 0.0:
        status = "does_not_support_state_conditioned_temporal_utility"
        decision = "BRANCH"
    else:
        status = "inconclusive"
        decision = "BRANCH"
    return {
        "status": status,
        "decision": decision,
        "gates": gates,
        "stationary_temporal_vs_rate_balanced_accuracy_delta": round(stationary_delta, 6),
        "transition_temporal_vs_rate_balanced_accuracy_delta": round(transition_delta, 6),
        "transition_temporal_vs_shuffle_mean_balanced_accuracy_delta": round(
            transition_control_delta,
            6,
        ),
        "transition_vs_stationary_balanced_accuracy_interaction_delta": round(
            interaction["delta"],
            6,
        ),
        "claim_boundary": (
            "This single-session offline decoding experiment can discriminate the two "
            "registered SCI-096 hypotheses only for the frozen epochs and dataset. It "
            "cannot establish a universal neural code or biological readout."
        ),
    }


def _evaluate_epoch(
    dataset: dict[str, Any],
    *,
    window: tuple[float, float],
    config: EpochDiscriminationConfig,
) -> dict[str, Any]:
    probe_config = config.probe_config()
    features = binned_spike_features(
        dataset,
        window_start=window[0],
        window_stop=window[1],
        bins=config.time_bins,
    )
    labels = dataset["labels"]
    split = dataset["split"]
    rate = evaluate_features(features.sum(axis=2), labels, split, probe_config)
    temporal = evaluate_features(features.reshape(len(labels), -1), labels, split, probe_config)
    shuffled = []
    for repeat in range(config.shuffle_repeats):
        shuffled_features = count_preserving_temporal_shuffle(
            features,
            seed=config.seed + repeat,
        )
        shuffled.append(
            evaluate_features(
                shuffled_features.reshape(len(labels), -1),
                labels,
                split,
                probe_config,
            )
        )
    shuffled_balanced = [entry["balanced_accuracy"] for entry in shuffled]
    modules = _scientific_modules()
    np = modules["np"]
    return {
        "window_start_s": window[0],
        "window_stop_s": window[1],
        "rate": rate,
        "temporal": temporal,
        "temporal_vs_rate_paired_bootstrap": bootstrap_paired_accuracy_delta(
            temporal["validation_correct"],
            rate["validation_correct"],
            seed=config.seed,
            repeats=config.bootstrap_repeats,
        ),
        "count_preserving_shuffle": {
            "repeats": config.shuffle_repeats,
            "balanced_accuracy_mean": round(float(np.mean(shuffled_balanced)), 6),
            "balanced_accuracy_min": round(float(np.min(shuffled_balanced)), 6),
            "balanced_accuracy_max": round(float(np.max(shuffled_balanced)), 6),
        },
    }


def run_discrimination(
    input_nwb: Path,
    config: EpochDiscriminationConfig,
) -> dict[str, Any]:
    dataset = load_dataset(input_nwb)
    stationary = _evaluate_epoch(dataset, window=STATIONARY_WINDOW, config=config)
    transition = _evaluate_epoch(dataset, window=TRANSITION_WINDOW, config=config)
    if (
        transition["temporal"]["validation_truth"]
        != stationary["temporal"]["validation_truth"]
    ):
        raise ValueError("frozen epochs must share the same validation trial order")
    interaction = bootstrap_balanced_interaction_delta(
        transition["temporal"]["validation_truth"],
        transition["temporal"]["validation_correct"],
        transition["rate"]["validation_correct"],
        stationary["temporal"]["validation_correct"],
        stationary["rate"]["validation_correct"],
        seed=config.seed,
        repeats=config.bootstrap_repeats,
    )
    decision = classify_epoch_result(
        stationary_rate_balanced=stationary["rate"]["balanced_accuracy"],
        stationary_temporal_balanced=stationary["temporal"]["balanced_accuracy"],
        transition_rate_balanced=transition["rate"]["balanced_accuracy"],
        transition_temporal_balanced=transition["temporal"]["balanced_accuracy"],
        transition_shuffle_mean_balanced=transition["count_preserving_shuffle"][
            "balanced_accuracy_mean"
        ],
        interaction=interaction,
        minimum_supported_delta=config.minimum_supported_delta,
    )
    modules = _scientific_modules()
    np = modules["np"]
    return {
        "schema_version": 1,
        "experiment_id": "sci096-dandi000140-epoch-discrimination-v3",
        "supersedes_experiment_id": "sci096-dandi000140-epoch-discrimination-v2",
        "correction_reason": (
            "v2 mixed balanced-accuracy epoch gates with an ordinary-accuracy "
            "interaction bootstrap; v3 uses a class-stratified balanced-accuracy "
            "interaction bootstrap throughout the primary decision."
        ),
        "question_id": "SCI-096",
        "parent_question_run_id": "stage1-sci-096-v2",
        "status": "exploratory_complete",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "source": "DANDI",
            "dandiset_id": "000140",
            "version": "0.220113.0408",
            "asset_id": "7821971e-c6a4-4568-8773-1bfa205c13f8",
            "asset_path": input_nwb.name,
            "sha256": sha256_file(input_nwb),
            "trial_count": int(len(dataset["labels"])),
            "train_trial_count": int(np.sum(dataset["split"] == "train")),
            "validation_trial_count": int(np.sum(dataset["split"] == "val")),
            "retained_unit_count": dataset["retained_unit_count"],
            "excluded_heldout_unit_count": dataset["excluded_heldout_unit_count"],
        },
        "preregistration": {
            **asdict(config),
            "anchor": "move_onset_time",
            "stationary_epoch": {
                "label": "preparatory_stationary",
                "window_s": list(STATIONARY_WINDOW),
            },
            "transition_epoch": {
                "label": "movement_onset_transition",
                "window_s": list(TRANSITION_WINDOW),
            },
            "target": "active target movement-direction octant",
            "split": "dataset-provided train/val",
            "capacity_control": "identical scaling, PCA components, logistic C, and seed",
            "temporal_control": "within-trial and within-unit count-preserving multinomial shuffle",
            "primary_test": (
                "balanced-accuracy transition temporal-vs-rate gain minus stationary "
                "temporal-vs-rate gain"
            ),
            "success_rule": "all five decision gates must pass",
        },
        "metrics": {
            "stationary": {
                **stationary,
                "rate": _stable_metrics(stationary["rate"]),
                "temporal": _stable_metrics(stationary["temporal"]),
            },
            "transition": {
                **transition,
                "rate": _stable_metrics(transition["rate"]),
                "temporal": _stable_metrics(transition["temporal"]),
            },
            "transition_vs_stationary_balanced_interaction_bootstrap": interaction,
        },
        "decision": decision,
        "environment": {
            "python": platform.python_version(),
            "numpy": modules["np"].__version__,
            "h5py": modules["h5py"].__version__,
            "scikit_learn": modules["sklearn"].__version__,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-nwb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite append-only artifact: {args.output}")
    result = run_discrimination(args.input_nwb.resolve(), EpochDiscriminationConfig())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "decision": result["decision"]["decision"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
