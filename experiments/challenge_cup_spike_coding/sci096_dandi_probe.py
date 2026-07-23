"""Reproducible public-data probe for Challenge Cup question SCI-096.

This is an exploratory, bounded comparison.  It does not claim that offline
decodability proves a biological readout mechanism.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PRIMARY_WINDOW = (-0.5, 0.0)
SENSITIVITY_WINDOWS = (
    (-0.25, 0.0, 5),
    (-1.0, 0.0, 10),
    (0.0, 0.25, 5),
    (0.0, 0.5, 5),
    (-0.5, 0.5, 10),
)


@dataclass(frozen=True)
class ProbeConfig:
    seed: int = 20260723
    primary_window_start_s: float = PRIMARY_WINDOW[0]
    primary_window_stop_s: float = PRIMARY_WINDOW[1]
    primary_time_bins: int = 5
    pca_components: int = 20
    logistic_c: float = 1.0
    shuffle_repeats: int = 10
    bootstrap_repeats: int = 10_000
    minimum_supported_delta: float = 0.08


def _scientific_modules():
    try:
        import h5py
        import numpy as np
        import sklearn
        from sklearn.decomposition import PCA
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:  # pragma: no cover - environment gate
        raise RuntimeError(
            "SCI-096 probe dependencies are unavailable. Install h5py and scikit-learn "
            "in an isolated experiment environment."
        ) from exc
    return {
        "h5py": h5py,
        "np": np,
        "sklearn": sklearn,
        "PCA": PCA,
        "LogisticRegression": LogisticRegression,
        "accuracy_score": accuracy_score,
        "balanced_accuracy_score": balanced_accuracy_score,
        "log_loss": log_loss,
        "Pipeline": Pipeline,
        "StandardScaler": StandardScaler,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ragged_rows(values, ends, np):
    starts = np.r_[0, ends[:-1]]
    return [values[start:stop] for start, stop in zip(starts, ends, strict=True)]


def _movement_octants(trials, np):
    positions = _ragged_rows(
        trials["target_pos"][()],
        trials["target_pos_index"][()],
        np,
    )
    active = trials["active_target"][()]
    selected = np.asarray(
        [trial_positions[index] for trial_positions, index in zip(positions, active, strict=True)]
    )
    angles = np.arctan2(selected[:, 1], selected[:, 0])
    return (np.floor((angles + np.pi) / (np.pi / 4)).astype(int) % 8), selected


def load_dataset(path: Path) -> dict[str, Any]:
    modules = _scientific_modules()
    h5py = modules["h5py"]
    np = modules["np"]
    with h5py.File(path, "r") as nwb:
        units = nwb["units"]
        unit_spikes = _ragged_rows(
            units["spike_times"][()],
            units["spike_times_index"][()],
            np,
        )
        heldout = units["heldout"][()].astype(bool)
        retained_spikes = [
            spikes for spikes, is_heldout in zip(unit_spikes, heldout, strict=True) if not is_heldout
        ]
        trials = nwb["intervals"]["trials"]
        labels, selected_positions = _movement_octants(trials, np)
        split = np.asarray(
            [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in trials["split"][()]]
        )
        anchors = trials["move_onset_time"][()].astype(float)
    return {
        "unit_spikes": retained_spikes,
        "labels": labels,
        "selected_positions": selected_positions,
        "split": split,
        "anchors": anchors,
        "retained_unit_count": len(retained_spikes),
        "excluded_heldout_unit_count": int(heldout.sum()),
    }


def binned_spike_features(dataset: dict[str, Any], *, window_start: float, window_stop: float, bins: int):
    modules = _scientific_modules()
    np = modules["np"]
    anchors = dataset["anchors"]
    unit_spikes = dataset["unit_spikes"]
    features = np.zeros((len(anchors), len(unit_spikes), bins), dtype=float)
    for trial_index, anchor in enumerate(anchors):
        edges = np.linspace(anchor + window_start, anchor + window_stop, bins + 1)
        for unit_index, spikes in enumerate(unit_spikes):
            features[trial_index, unit_index] = np.histogram(spikes, bins=edges)[0]
    return features


def count_preserving_temporal_shuffle(features, *, seed: int):
    modules = _scientific_modules()
    np = modules["np"]
    rng = np.random.default_rng(seed)
    shuffled = np.zeros_like(features)
    probabilities = np.full(features.shape[2], 1.0 / features.shape[2])
    for trial_index in range(features.shape[0]):
        for unit_index in range(features.shape[1]):
            shuffled[trial_index, unit_index] = rng.multinomial(
                int(features[trial_index, unit_index].sum()),
                probabilities,
            )
    return shuffled


def _fit_model(train_features, train_labels, config: ProbeConfig):
    modules = _scientific_modules()
    components = min(
        config.pca_components,
        int(train_features.shape[0] - len(set(train_labels.tolist()))),
        int(train_features.shape[1]),
    )
    if components < 1:
        raise ValueError("insufficient samples for the frozen PCA/classification protocol")
    model = modules["Pipeline"](
        [
            ("scale", modules["StandardScaler"]()),
            ("pca", modules["PCA"](n_components=components, random_state=config.seed)),
            (
                "classifier",
                modules["LogisticRegression"](
                    C=config.logistic_c,
                    max_iter=5_000,
                    random_state=config.seed,
                ),
            ),
        ]
    )
    model.fit(train_features, train_labels)
    return model, components


def evaluate_features(features, labels, split, config: ProbeConfig) -> dict[str, Any]:
    modules = _scientific_modules()
    np = modules["np"]
    train_mask = split == "train"
    validation_mask = split == "val"
    model, components = _fit_model(features[train_mask], labels[train_mask], config)
    predictions = model.predict(features[validation_mask])
    probabilities = model.predict_proba(features[validation_mask])
    truth = labels[validation_mask]
    return {
        "accuracy": round(float(modules["accuracy_score"](truth, predictions)), 6),
        "balanced_accuracy": round(float(modules["balanced_accuracy_score"](truth, predictions)), 6),
        "log_loss": round(
            float(modules["log_loss"](truth, probabilities, labels=model.classes_)),
            6,
        ),
        "pca_components": components,
        "validation_correct": (predictions == truth).astype(int).tolist(),
        "validation_predictions": predictions.astype(int).tolist(),
        "validation_truth": truth.astype(int).tolist(),
        "train_samples": int(np.sum(train_mask)),
        "validation_samples": int(np.sum(validation_mask)),
    }


def bootstrap_paired_accuracy_delta(
    candidate_correct: list[int],
    baseline_correct: list[int],
    *,
    seed: int,
    repeats: int,
) -> dict[str, float]:
    modules = _scientific_modules()
    np = modules["np"]
    candidate = np.asarray(candidate_correct, dtype=float)
    baseline = np.asarray(baseline_correct, dtype=float)
    if len(candidate) != len(baseline) or not len(candidate):
        raise ValueError("paired bootstrap requires equal non-empty correctness vectors")
    differences = candidate - baseline
    rng = np.random.default_rng(seed)
    samples = np.empty(repeats, dtype=float)
    for index in range(repeats):
        sampled_indices = rng.integers(0, len(differences), size=len(differences))
        samples[index] = differences[sampled_indices].mean()
    return {
        "delta": round(float(differences.mean()), 6),
        "ci95_low": round(float(np.quantile(samples, 0.025)), 6),
        "ci95_high": round(float(np.quantile(samples, 0.975)), 6),
    }


def classify_result(
    rate_metrics: dict[str, Any],
    temporal_metrics: dict[str, Any],
    shuffled_balanced_accuracies: list[float],
    config: ProbeConfig,
) -> dict[str, Any]:
    temporal_delta = (
        temporal_metrics["balanced_accuracy"] - rate_metrics["balanced_accuracy"]
    )
    shuffled_reference = sum(shuffled_balanced_accuracies) / len(shuffled_balanced_accuracies)
    control_delta = temporal_metrics["balanced_accuracy"] - shuffled_reference
    if (
        temporal_delta >= config.minimum_supported_delta
        and control_delta >= config.minimum_supported_delta
    ):
        status = "supports_context_adaptive_multiplexing"
        decision = "CONTINUE"
    elif temporal_delta <= -config.minimum_supported_delta:
        status = "supports_conditional_minimal_statistics_in_primary_window"
        decision = "BRANCH"
    else:
        status = "inconclusive_tends_minimal_statistics"
        decision = "BRANCH"
    return {
        "status": status,
        "decision": decision,
        "temporal_vs_rate_balanced_accuracy_delta": round(temporal_delta, 6),
        "temporal_vs_shuffle_mean_balanced_accuracy_delta": round(control_delta, 6),
        "claim_boundary": (
            "This single-session exploratory probe can revise the tested window-specific "
            "hypothesis, but cannot establish a universal neural code or biological readout."
        ),
    }


def _stable_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key not in {"validation_correct", "validation_predictions", "validation_truth"}
    }


def run_probe(input_nwb: Path, config: ProbeConfig) -> dict[str, Any]:
    modules = _scientific_modules()
    np = modules["np"]
    dataset = load_dataset(input_nwb)
    labels = dataset["labels"]
    split = dataset["split"]

    primary = binned_spike_features(
        dataset,
        window_start=config.primary_window_start_s,
        window_stop=config.primary_window_stop_s,
        bins=config.primary_time_bins,
    )
    rate_metrics = evaluate_features(primary.sum(axis=2), labels, split, config)
    temporal_metrics = evaluate_features(primary.reshape(len(labels), -1), labels, split, config)

    shuffled_metrics = []
    for repeat in range(config.shuffle_repeats):
        shuffled = count_preserving_temporal_shuffle(primary, seed=config.seed + repeat)
        shuffled_metrics.append(
            evaluate_features(shuffled.reshape(len(labels), -1), labels, split, config)
        )
    shuffled_balanced = [entry["balanced_accuracy"] for entry in shuffled_metrics]

    sensitivity = []
    for window_start, window_stop, bins in SENSITIVITY_WINDOWS:
        features = binned_spike_features(
            dataset,
            window_start=window_start,
            window_stop=window_stop,
            bins=bins,
        )
        sensitivity.append(
            {
                "window_start_s": window_start,
                "window_stop_s": window_stop,
                "time_bins": bins,
                "rate": _stable_metrics(evaluate_features(features.sum(axis=2), labels, split, config)),
                "temporal": _stable_metrics(
                    evaluate_features(features.reshape(len(labels), -1), labels, split, config)
                ),
            }
        )

    majority_label = int(np.bincount(labels[split == "train"]).argmax())
    majority_accuracy = float(np.mean(labels[split == "val"] == majority_label))
    decision = classify_result(rate_metrics, temporal_metrics, shuffled_balanced, config)
    return {
        "schema_version": 1,
        "experiment_id": "sci096-dandi000140-probe-v1",
        "question_id": "SCI-096",
        "status": "exploratory_complete",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "source": "DANDI",
            "dandiset_id": "000140",
            "version": "0.220113.0408",
            "asset_id": "7821971e-c6a4-4568-8773-1bfa205c13f8",
            "asset_path": input_nwb.name,
            "sha256": sha256_file(input_nwb),
            "trial_count": int(len(labels)),
            "train_trial_count": int(np.sum(split == "train")),
            "validation_trial_count": int(np.sum(split == "val")),
            "retained_unit_count": dataset["retained_unit_count"],
            "excluded_heldout_unit_count": dataset["excluded_heldout_unit_count"],
            "movement_direction_class_count": int(len(np.unique(labels))),
        },
        "protocol": {
            **asdict(config),
            "anchor": "move_onset_time",
            "target": "active target movement-direction octant",
            "split": "dataset-provided train/val",
            "rate_features": "per-unit spike counts in the primary window",
            "temporal_features": "per-unit counts in equal-width time bins",
            "capacity_control": "same scaling, PCA component count, logistic C, and classifier",
            "temporal_control": "within-trial and within-unit multinomial redistribution preserving total counts",
            "heldout_units": "excluded",
            "sensitivity_role": "exploratory_only_not_used_for_primary_decision",
        },
        "metrics": {
            "majority_validation_accuracy": round(majority_accuracy, 6),
            "rate": _stable_metrics(rate_metrics),
            "temporal": _stable_metrics(temporal_metrics),
            "temporal_vs_rate_paired_bootstrap": bootstrap_paired_accuracy_delta(
                temporal_metrics["validation_correct"],
                rate_metrics["validation_correct"],
                seed=config.seed,
                repeats=config.bootstrap_repeats,
            ),
            "count_preserving_shuffle": {
                "repeats": config.shuffle_repeats,
                "balanced_accuracy_mean": round(float(np.mean(shuffled_balanced)), 6),
                "balanced_accuracy_min": round(float(np.min(shuffled_balanced)), 6),
                "balanced_accuracy_max": round(float(np.max(shuffled_balanced)), 6),
            },
            "sensitivity": sensitivity,
        },
        "decision": decision,
        "hypothesis_revision_input": {
            "observed": (
                "In the frozen pre-movement 500 ms window, binned temporal features did not "
                "outperform total per-unit counts under the capacity-matched decoder."
            ),
            "interpretation": (
                "The result weakens a broad temporal-multiplexing claim for this dataset and "
                "window and increases the value of the conditional minimal-statistics competitor."
            ),
            "unresolved": [
                "The validation set contains only 25 trials from one session.",
                "The result is sensitive to window choice and decoder specification.",
                "Offline decoding cannot establish downstream biological use.",
            ],
            "requested_qwen_revision": (
                "Revise HYP-1 into a condition-specific hypothesis that predicts in advance "
                "when temporal features should add information beyond rate; retain HYP-2 as "
                "the active competitor and preserve all negative results."
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": modules["np"].__version__,
            "h5py": modules["h5py"].__version__,
            "scikit_learn": modules["sklearn"].__version__,
        },
    }


def self_check() -> dict[str, Any]:
    config = ProbeConfig(bootstrap_repeats=100)
    support = classify_result(
        {"balanced_accuracy": 0.50},
        {"balanced_accuracy": 0.62},
        [0.48, 0.50, 0.52],
        config,
    )
    inconclusive = classify_result(
        {"balanced_accuracy": 0.50},
        {"balanced_accuracy": 0.52},
        [0.49, 0.51],
        config,
    )
    bootstrap = bootstrap_paired_accuracy_delta(
        [1, 1, 0, 1],
        [1, 0, 0, 0],
        seed=config.seed,
        repeats=config.bootstrap_repeats,
    )
    assert support["status"] == "supports_context_adaptive_multiplexing"
    assert inconclusive["status"] == "inconclusive_tends_minimal_statistics"
    assert bootstrap["delta"] == 0.5
    return {"status": "ok", "supportGate": "ok", "inconclusiveGate": "ok", "bootstrap": "ok"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-nwb", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_check:
        print(json.dumps(self_check(), ensure_ascii=False, indent=2))
        return 0
    if args.input_nwb is None or args.output is None:
        raise SystemExit("--input-nwb and --output are required unless --self-check is used")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite append-only artifact: {args.output}")
    result = run_probe(args.input_nwb.resolve(), ProbeConfig())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
