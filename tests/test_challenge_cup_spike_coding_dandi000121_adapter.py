from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = PROJECT_ROOT / "experiments" / "challenge_cup_spike_coding"
SCRIPT = EXPERIMENT_DIR / "sci096_dandi000121_adapter.py"


def _load_adapter_module():
    sys.path.insert(0, str(EXPERIMENT_DIR))
    spec = importlib.util.spec_from_file_location("sci096_dandi000121_adapter", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fixture(path: Path, *, trial_count: int) -> None:
    sample_rate = 100.0
    spacing = 1.2
    end_time = trial_count * spacing + 1.0
    timestamps = np.arange(0.0, end_time, 1.0 / sample_rate)
    hand = np.zeros((len(timestamps), 3), dtype=float)
    target_positions = []
    target_position_ends = []
    target_acquisitions = []
    target_acquisition_ends = []
    go_cues = []
    successful = []
    for trial_index in range(trial_count):
        base = trial_index * spacing
        go_cue = base + 0.20
        intended_onset = base + 0.35
        target_acquire = base + 0.70
        angle = 2 * np.pi * (trial_index % 8) / 8.0
        target = np.asarray([np.cos(angle), np.sin(angle)])
        go_cues.append(go_cue)
        successful.append(1)
        target_positions.extend([target[0], target[1], 0.0])
        target_position_ends.append(len(target_positions))
        target_acquisitions.append(target_acquire)
        target_acquisition_ends.append(len(target_acquisitions))
        segment = (timestamps >= intended_onset) & (timestamps <= target_acquire)
        phase = (timestamps[segment] - intended_onset) / (target_acquire - intended_onset)
        progress = 0.5 - 0.5 * np.cos(np.pi * phase)
        hand[segment, :2] = progress[:, None] * target[None, :]
        held = (timestamps > target_acquire) & (timestamps < base + spacing)
        hand[held, :2] = target

    with h5py.File(path, "w") as nwb:
        units = nwb.create_group("units")
        units.create_dataset("id", data=np.arange(4))
        spike_rows = [
            np.arange(0.1 + offset, end_time, 0.4 + offset)
            for offset in (0.0, 0.01, 0.02, 0.03)
        ]
        units.create_dataset("spike_times", data=np.concatenate(spike_rows))
        units.create_dataset(
            "spike_times_index",
            data=np.cumsum([len(row) for row in spike_rows]),
        )

        trials = nwb.create_group("intervals").create_group("trials")
        trials.create_dataset("id", data=np.arange(trial_count))
        trials.create_dataset("go_cue_time", data=np.asarray(go_cues))
        trials.create_dataset("is_successful", data=np.asarray(successful))
        trials.create_dataset("target_pos", data=np.asarray(target_positions))
        trials.create_dataset("target_pos_index", data=np.asarray(target_position_ends))
        trials.create_dataset(
            "target_acquire_time",
            data=np.asarray(target_acquisitions),
        )
        trials.create_dataset(
            "target_acquire_time_index",
            data=np.asarray(target_acquisition_ends),
        )

        position = (
            nwb.create_group("processing")
            .create_group("behavior")
            .create_group("Position")
            .create_group("Hand")
        )
        position.create_dataset("timestamps", data=timestamps)
        position.create_dataset("data", data=hand)


def test_adapter_derives_frozen_onsets_and_deterministic_split(tmp_path: Path) -> None:
    module = _load_adapter_module()
    source = tmp_path / "session.nwb"
    _write_fixture(source, trial_count=120)

    first = module.load_dandi000121_dataset(source)
    second = module.load_dandi000121_dataset(source)

    assert len(first["labels"]) == 120
    assert first["retained_unit_count"] == 4
    assert set(first["labels"].tolist()) == set(range(8))
    assert int(np.sum(first["split"] == "train")) == 90
    assert int(np.sum(first["split"] == "val")) == 30
    assert np.array_equal(first["split"], second["split"])
    assert np.allclose(first["anchors"], second["anchors"])
    assert np.all(first["anchors"] > first["go_cue_times"] + 0.05)
    assert np.all(first["anchors"] < first["target_acquire_times"])
    assert np.all(first["sensitivity_anchors"]["0.1"] <= first["anchors"])
    assert np.all(first["anchors"] <= first["sensitivity_anchors"]["0.3"])
    protocol = first["adapter_protocol"]
    assert protocol["lowpass_cutoff_hz"] == 15.0
    assert protocol["primary_onset_fraction"] == 0.20
    assert protocol["filter_padding_s"] == 0.25
    assert protocol["minimum_reaction_time_s"] == 0.05
    assert protocol["effective_filter_order"] == 8


def test_adapter_rejects_session_below_usable_trial_gate(tmp_path: Path) -> None:
    module = _load_adapter_module()
    source = tmp_path / "short-session.nwb"
    _write_fixture(source, trial_count=99)

    with pytest.raises(ValueError, match="at least 100 usable trials"):
        module.load_dandi000121_dataset(source)


def test_adapter_rejects_undersampled_hand_signal(tmp_path: Path) -> None:
    module = _load_adapter_module()
    source = tmp_path / "session.nwb"
    _write_fixture(source, trial_count=100)
    config = module.Dandi000121AdapterConfig(lowpass_cutoff_hz=60.0)

    with pytest.raises(ValueError, match="twice the frozen low-pass cutoff"):
        module.load_dandi000121_dataset(source, config)


def test_adapter_rejects_session_missing_required_direction_octants(
    tmp_path: Path,
) -> None:
    module = _load_adapter_module()
    source = tmp_path / "session.nwb"
    _write_fixture(source, trial_count=100)
    config = module.Dandi000121AdapterConfig(required_direction_octants=9)

    with pytest.raises(ValueError, match="requires all movement-direction octants"):
        module.load_dandi000121_dataset(source, config)
