"""Outcome-blind DANDI 000121 adapter for the SCI-096 v3 protocol.

The adapter derives movement onset from hand kinematics before any neural
decoder is evaluated.  It does not run the experiment or change its frozen
epochs, decoder capacity, shuffle control, or decision gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sci096_dandi_probe import _ragged_rows, _scientific_modules


@dataclass(frozen=True)
class Dandi000121AdapterConfig:
    seed: int = 20260723
    lowpass_cutoff_hz: float = 15.0
    butterworth_order: int = 4
    filter_padding_s: float = 0.25
    primary_onset_fraction: float = 0.20
    sensitivity_onset_fractions: tuple[float, ...] = (0.10, 0.30)
    minimum_reaction_time_s: float = 0.05
    validation_fraction: float = 0.25
    minimum_usable_trials: int = 100
    minimum_train_trials: int = 75
    minimum_validation_trials: int = 25
    minimum_sorted_units: int = 2
    required_direction_octants: int = 8


def _adapter_modules() -> dict[str, Any]:
    modules = _scientific_modules()
    try:
        from scipy.signal import butter, sosfiltfilt
    except ImportError as exc:  # pragma: no cover - environment gate
        raise RuntimeError(
            "DANDI 000121 adapter requires scipy in the isolated experiment environment."
        ) from exc
    return {**modules, "butter": butter, "sosfiltfilt": sosfiltfilt}


def _first_finite_after(values, lower_bound: float, np) -> float | None:
    candidates = np.asarray(values, dtype=float)
    valid = candidates[np.isfinite(candidates) & (candidates > lower_bound)]
    if not len(valid):
        return None
    return float(valid[0])


def _movement_onsets(
    *,
    hand_data,
    hand_timestamps,
    go_cue: float,
    target_acquire: float,
    sample_rate_hz: float,
    fractions: tuple[float, ...],
    config: Dandi000121AdapterConfig,
    modules: dict[str, Any],
) -> dict[float, float] | None:
    np = modules["np"]
    start = int(
        np.searchsorted(
            hand_timestamps,
            go_cue - config.filter_padding_s,
            side="left",
        )
    )
    stop = int(
        np.searchsorted(
            hand_timestamps,
            target_acquire + config.filter_padding_s,
            side="right",
        )
    )
    if stop - start < 16:
        return None
    timestamps = np.asarray(hand_timestamps[start:stop], dtype=float)
    positions = np.asarray(hand_data[start:stop, :2], dtype=float)
    if not np.all(np.isfinite(timestamps)) or not np.all(np.isfinite(positions)):
        return None
    deltas = np.diff(timestamps)
    if not len(deltas) or np.any(deltas <= 0):
        return None
    sos = modules["butter"](
        config.butterworth_order,
        config.lowpass_cutoff_hz,
        btype="lowpass",
        fs=sample_rate_hz,
        output="sos",
    )
    filtered = modules["sosfiltfilt"](sos, positions, axis=0)
    velocity = np.diff(filtered, axis=0) / deltas[:, None]
    speed = np.linalg.norm(velocity, axis=1)
    velocity_timestamps = (timestamps[:-1] + timestamps[1:]) / 2.0
    analysis_mask = (velocity_timestamps >= go_cue) & (
        velocity_timestamps <= target_acquire
    )
    speed = speed[analysis_mask]
    velocity_timestamps = velocity_timestamps[analysis_mask]
    if not len(speed):
        return None
    peak_speed = float(np.max(speed))
    if not np.isfinite(peak_speed) or peak_speed <= 0:
        return None
    onsets: dict[float, float] = {}
    for fraction in fractions:
        crossings = np.flatnonzero(speed >= fraction * peak_speed)
        if not len(crossings):
            return None
        onset = float(velocity_timestamps[int(crossings[0])])
        if not go_cue <= onset <= target_acquire:
            return None
        onsets[fraction] = onset
    return onsets


def _stratified_split(labels, config: Dandi000121AdapterConfig, np):
    split = np.full(len(labels), "train", dtype="<U5")
    rng = np.random.default_rng(config.seed)
    unique_labels, class_counts = np.unique(labels, return_counts=True)
    if np.any(class_counts < 4):
        sparse_label = int(unique_labels[int(np.argmin(class_counts))])
        raise ValueError(
            f"label {sparse_label} has fewer than four usable trials for stratification"
        )
    validation_total = max(
        config.minimum_validation_trials,
        int(round(len(labels) * config.validation_fraction)),
    )
    if len(labels) - validation_total < config.minimum_train_trials:
        raise ValueError(
            f"frozen split requires at least {config.minimum_train_trials} train trials"
        )
    ideal_counts = class_counts * config.validation_fraction
    validation_counts = np.floor(ideal_counts).astype(int)
    validation_counts = np.maximum(validation_counts, 1)
    while int(validation_counts.sum()) < validation_total:
        eligible = validation_counts < class_counts - 1
        if not np.any(eligible):
            raise ValueError("stratified split cannot allocate the validation target")
        priorities = np.where(
            eligible,
            ideal_counts - validation_counts,
            -np.inf,
        )
        validation_counts[int(np.argmax(priorities))] += 1
    while int(validation_counts.sum()) > validation_total:
        eligible = validation_counts > 1
        if not np.any(eligible):
            raise ValueError("stratified split cannot reduce the validation allocation")
        priorities = np.where(
            eligible,
            validation_counts - ideal_counts,
            -np.inf,
        )
        validation_counts[int(np.argmax(priorities))] -= 1
    for label, validation_count in zip(
        unique_labels,
        validation_counts,
        strict=True,
    ):
        indices = np.flatnonzero(labels == label)
        shuffled = rng.permutation(indices)
        if validation_count >= len(indices):
            raise ValueError(f"label {int(label)} has no training trials after stratification")
        split[shuffled[:validation_count]] = "val"
    train_count = int(np.sum(split == "train"))
    validation_count = int(np.sum(split == "val"))
    if train_count < config.minimum_train_trials:
        raise ValueError(
            f"frozen split requires at least {config.minimum_train_trials} train trials; "
            f"found {train_count}"
        )
    if validation_count < config.minimum_validation_trials:
        raise ValueError(
            f"frozen split requires at least {config.minimum_validation_trials} "
            f"validation trials; found {validation_count}"
        )
    return split


def load_dandi000121_dataset(
    path: Path,
    config: Dandi000121AdapterConfig | None = None,
) -> dict[str, Any]:
    """Load one DANDI 000121 session into the existing decoder dataset contract."""

    config = config or Dandi000121AdapterConfig()
    modules = _adapter_modules()
    h5py = modules["h5py"]
    np = modules["np"]
    fractions = (config.primary_onset_fraction, *config.sensitivity_onset_fractions)
    if len(set(fractions)) != len(fractions) or any(not 0 < value < 1 for value in fractions):
        raise ValueError("movement-onset fractions must be unique values between zero and one")

    with h5py.File(path, "r") as nwb:
        units = nwb["units"]
        unit_spikes = _ragged_rows(
            units["spike_times"][()],
            units["spike_times_index"][()],
            np,
        )
        if len(unit_spikes) < config.minimum_sorted_units:
            raise ValueError(
                f"frozen protocol requires at least {config.minimum_sorted_units} sorted units; "
                f"found {len(unit_spikes)}"
            )

        trials = nwb["intervals"]["trials"]
        target_positions = _ragged_rows(
            trials["target_pos"][()],
            trials["target_pos_index"][()],
            np,
        )
        target_acquisitions = _ragged_rows(
            trials["target_acquire_time"][()],
            trials["target_acquire_time_index"][()],
            np,
        )
        successful = trials["is_successful"][()].astype(bool)
        go_cues = trials["go_cue_time"][()].astype(float)
        trial_ids = trials["id"][()].astype(int)
        hand = nwb["processing"]["behavior"]["Position"]["Hand"]
        hand_timestamps = np.asarray(hand["timestamps"][()], dtype=float)
        hand_data = hand["data"]
        timestamp_deltas = np.diff(hand_timestamps)
        valid_deltas = timestamp_deltas[
            np.isfinite(timestamp_deltas) & (timestamp_deltas > 0)
        ]
        if not len(valid_deltas):
            raise ValueError("hand timestamps do not define a positive sampling interval")
        sample_rate_hz = float(1.0 / np.median(valid_deltas))
        if sample_rate_hz <= 2 * config.lowpass_cutoff_hz:
            raise ValueError(
                "hand sampling rate must exceed twice the frozen low-pass cutoff"
            )

        retained_ids = []
        labels = []
        movement_vectors = []
        go_cue_times = []
        target_acquire_times = []
        primary_anchors = []
        sensitivity_anchors = {
            fraction: [] for fraction in config.sensitivity_onset_fractions
        }
        rejection_counts = {
            "unsuccessful": 0,
            "invalid_event_times": 0,
            "invalid_target": 0,
            "movement_onset_unavailable": 0,
            "anticipatory_movement": 0,
        }
        for index, trial_id in enumerate(trial_ids):
            if not successful[index]:
                rejection_counts["unsuccessful"] += 1
                continue
            go_cue = float(go_cues[index])
            target_acquire = _first_finite_after(
                target_acquisitions[index],
                go_cue,
                np,
            )
            if not np.isfinite(go_cue) or target_acquire is None:
                rejection_counts["invalid_event_times"] += 1
                continue
            position = np.asarray(target_positions[index], dtype=float)
            if position.size < 2 or not np.all(np.isfinite(position[:2])):
                rejection_counts["invalid_target"] += 1
                continue
            go_index = int(np.searchsorted(hand_timestamps, go_cue, side="left"))
            if go_index >= len(hand_timestamps):
                rejection_counts["invalid_event_times"] += 1
                continue
            origin = np.asarray(hand_data[go_index, :2], dtype=float)
            movement_vector = position[:2] - origin
            if not np.all(np.isfinite(movement_vector)) or np.linalg.norm(movement_vector) <= 0:
                rejection_counts["invalid_target"] += 1
                continue
            onsets = _movement_onsets(
                hand_data=hand_data,
                hand_timestamps=hand_timestamps,
                go_cue=go_cue,
                target_acquire=target_acquire,
                sample_rate_hz=sample_rate_hz,
                fractions=fractions,
                config=config,
                modules=modules,
            )
            if onsets is None:
                rejection_counts["movement_onset_unavailable"] += 1
                continue
            if (
                onsets[config.primary_onset_fraction] - go_cue
                < config.minimum_reaction_time_s
            ):
                rejection_counts["anticipatory_movement"] += 1
                continue
            angle = float(np.arctan2(movement_vector[1], movement_vector[0]))
            label = int(
                np.floor((angle + np.pi + np.pi / 8) / (np.pi / 4))
            ) % 8
            retained_ids.append(int(trial_id))
            labels.append(label)
            movement_vectors.append(movement_vector)
            go_cue_times.append(go_cue)
            target_acquire_times.append(target_acquire)
            primary_anchors.append(onsets[config.primary_onset_fraction])
            for fraction in config.sensitivity_onset_fractions:
                sensitivity_anchors[fraction].append(onsets[fraction])

    if len(labels) < config.minimum_usable_trials:
        raise ValueError(
            f"frozen protocol requires at least {config.minimum_usable_trials} usable trials; "
            f"found {len(labels)}"
        )
    label_array = np.asarray(labels, dtype=int)
    observed_octants = set(np.unique(label_array).tolist())
    required_octants = set(range(config.required_direction_octants))
    if observed_octants != required_octants:
        raise ValueError(
            "frozen protocol requires all movement-direction octants; "
            f"observed {sorted(observed_octants)}"
        )
    split = _stratified_split(label_array, config, np)
    return {
        "unit_spikes": unit_spikes,
        "labels": label_array,
        "selected_positions": np.asarray(movement_vectors, dtype=float),
        "split": split,
        "anchors": np.asarray(primary_anchors, dtype=float),
        "sensitivity_anchors": {
            str(fraction): np.asarray(values, dtype=float)
            for fraction, values in sensitivity_anchors.items()
        },
        "trial_ids": np.asarray(retained_ids, dtype=int),
        "go_cue_times": np.asarray(go_cue_times, dtype=float),
        "target_acquire_times": np.asarray(target_acquire_times, dtype=float),
        "retained_unit_count": len(unit_spikes),
        "excluded_heldout_unit_count": 0,
        "rejection_counts": rejection_counts,
        "adapter_protocol": {
            **asdict(config),
            "effective_filter_order": config.butterworth_order * 2,
            "sample_rate_hz": round(sample_rate_hz, 6),
            "movement_onset_definition": (
                "first post-go-cue hand-speed sample at or above the configured "
                "fraction of trial peak speed before first target acquisition"
            ),
            "filter_context": (
                "fixed symmetric kinematic padding around the go-cue to "
                "target-acquisition analysis interval"
            ),
            "label_definition": "movement-vector octant relative to hand position at go cue",
            "split_definition": "deterministic per-octant stratified train/validation split",
        },
    }
