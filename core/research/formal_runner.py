"""Trusted, opt-in local runner for bounded multi-seed Challenge Cup experiments.

This module deliberately keeps the process boundary small:

* it only invokes the repository-owned FashionMNIST script;
* the Python executable, data root, and artifact root must be explicit;
* output artifacts must live under the current project's canonical data root; and
* completed execution is evidence for review, never an automatic research claim.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json
from scripts.windowless_subprocess import no_window_subprocess_kwargs
from vibelution_storage import resolve_project_data_home


FASHION_MNIST_MULTI_SEED_ADAPTER = "fashion_mnist_predictive_coding_multi_seed"
_TRUSTED_SCRIPT_RELATIVE_PATH = Path("experiments/challenge_cup_predictive_coding/fashion_mnist_smoke.py")
_MIN_SEED_COUNT = 3
_MAX_SEED_COUNT = 8
_SELF_CHECK_TIMEOUT_SECONDS = 45
_DEFAULT_TIMEOUT_SECONDS = 1800
_MIN_TIMEOUT_SECONDS = 60
_MAX_TIMEOUT_SECONDS = 7200


class FormalRunnerError(ValueError):
    """Raised when the explicit full-run contract cannot be safely executed."""


def prepare_full_run(
    adapter_id: str,
    *,
    method_config: dict[str, Any] | None,
    execution_config: dict[str, Any] | None,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate an explicit local execution environment and construct fixed commands.

    ``prepare`` runs the trusted script's self-check only.  It never trains a
    model, writes a result artifact, or changes a research-plan state.
    """

    if str(adapter_id or "").strip() != FASHION_MNIST_MULTI_SEED_ADAPTER:
        raise FormalRunnerError(f"Unsupported formal adapter: {adapter_id!r}")
    root = _project_root(project_root)
    script_path = root / _TRUSTED_SCRIPT_RELATIVE_PATH
    if not script_path.is_file():
        raise FormalRunnerError(f"Trusted experiment script is unavailable: {script_path}")

    method = method_config if isinstance(method_config, dict) else {}
    execution = execution_config if isinstance(execution_config, dict) else {}
    seeds = _validated_seeds(method.get("seeds"))
    python_executable = _required_path(execution.get("pythonExecutable"), "pythonExecutable", kind="file")
    data_root = _required_path(execution.get("dataRoot"), "dataRoot", kind="directory")
    output_root = assert_canonical_project_data_path(
        execution.get("outputRoot"),
        project_root=root,
        label="outputRoot",
        create=True,
    )
    timeout_seconds = _bounded_int(
        execution.get("timeoutSeconds", _DEFAULT_TIMEOUT_SECONDS),
        "timeoutSeconds",
        minimum=_MIN_TIMEOUT_SECONDS,
        maximum=_MAX_TIMEOUT_SECONDS,
    )
    training_mask_size = _bounded_int(
        execution.get("trainingMaskSize", method.get("trainingMaskSize", 8)),
        "trainingMaskSize",
        minimum=1,
        maximum=28,
    )
    candidate_loss_mask_modes = _validated_mask_modes(
        execution.get("candidateLossMaskModes"),
        fallback=str(
            execution.get("candidateLossMaskMode")
            or method.get("candidateLossMaskMode")
            or "aligned"
        ).strip(),
    )
    run_options = {
        "trainSamples": _bounded_int(execution.get("trainSamples", 4096), "trainSamples", minimum=1, maximum=60000),
        "testSamples": _bounded_int(execution.get("testSamples", 1024), "testSamples", minimum=1, maximum=10000),
        "epochs": _bounded_int(execution.get("epochs", 8), "epochs", minimum=1, maximum=1000),
        "batchSize": _bounded_int(execution.get("batchSize", 64), "batchSize", minimum=1, maximum=2048),
        "correctionSteps": _bounded_int(execution.get("correctionSteps", 3), "correctionSteps", minimum=1, maximum=64),
        "correctionRate": _bounded_float(execution.get("correctionRate", 0.8), "correctionRate", minimum=0.0, maximum=10.0),
        "candidateMechanism": str(
            execution.get("candidateMechanism")
            or method.get("candidateMechanism")
            or "inference_latent_correction"
        ).strip(),
        "candidateMaskedLossWeight": _bounded_float(
            execution.get("candidateMaskedLossWeight", method.get("candidateMaskedLossWeight", 4.0)),
            "candidateMaskedLossWeight",
            minimum=0.0,
            maximum=100.0,
        ),
        "candidateLossMaskMode": str(
            execution.get("candidateLossMaskMode")
            or method.get("candidateLossMaskMode")
            or "aligned"
        ).strip(),
        "candidateLossMaskModes": candidate_loss_mask_modes,
        "trainingMaskSize": training_mask_size,
        "evaluationMaskSizes": _validated_mask_sizes(
            execution.get("evaluationMaskSizes"),
            fallback=training_mask_size,
        ),
        "minimumMseImprovement": _bounded_float(
            execution.get("minimumMseImprovement", method.get("minimumMseImprovement", 0.001)),
            "minimumMseImprovement",
            minimum=0.0,
            maximum=1.0,
        ),
        "maximumLatencyMultiplier": _bounded_float(
            execution.get("maximumLatencyMultiplier", method.get("maximumLatencyMultiplier", 5.0)),
            "maximumLatencyMultiplier",
            minimum=0.01,
            maximum=100.0,
        ),
        "maximumGlobalMseRegression": _bounded_float(
            execution.get("maximumGlobalMseRegression", method.get("maximumGlobalMseRegression", 0.0005)),
            "maximumGlobalMseRegression",
            minimum=0.0,
            maximum=1.0,
        ),
    }
    if execution.get("candidateLossMaskModes"):
        run_options["candidateLossMaskMode"] = candidate_loss_mask_modes[0]
    if run_options["candidateMechanism"] not in {
        "inference_latent_correction",
        "masked_prediction_error_training",
    }:
        raise FormalRunnerError("candidateMechanism is not supported by the formal adapter.")
    if run_options["candidateLossMaskMode"] not in {
        "aligned",
        "spatially_shifted",
        "deterministically_permuted",
    }:
        raise FormalRunnerError("candidateLossMaskMode is not supported by the formal adapter.")
    if (
        len(run_options["candidateLossMaskModes"]) > 1
        and run_options["candidateMechanism"] != "masked_prediction_error_training"
    ):
        raise FormalRunnerError("candidateLossMaskModes matrix requires masked_prediction_error_training.")

    self_check = _run_process(
        [str(python_executable), str(script_path), "--self-check"],
        cwd=root,
        timeout_seconds=_SELF_CHECK_TIMEOUT_SECONDS,
    )
    if self_check.returncode != 0:
        raise FormalRunnerError(
            "Formal runner self-check failed: "
            f"{_process_error(self_check)}"
        )

    commands = [
        {
            "seed": seed,
            "outputDir": str(output_root / f"seed-{seed}"),
            "args": _experiment_command(
                python_executable=python_executable,
                script_path=script_path,
                data_root=data_root,
                output_dir=output_root / f"seed-{seed}",
                seed=seed,
                options=run_options,
            ),
        }
        for seed in seeds
    ]
    return {
        "adapterId": FASHION_MNIST_MULTI_SEED_ADAPTER,
        "status": "prepared",
        "executionMode": "local_process",
        "seedCount": len(seeds),
        "seeds": seeds,
        "commands": commands,
        "timeoutSecondsPerSeed": timeout_seconds,
        "environment": {
            "pythonExecutable": str(python_executable),
            "dataRoot": str(data_root),
            "outputRoot": str(output_root),
            "scriptPath": str(script_path),
            "selfCheck": _clip_process_output(self_check),
        },
        "runOptions": run_options,
        "boundaries": [
            "trusted_repository_script_only",
            "shell_disabled",
            "windowless_subprocess",
            "artifacts_inside_current_instance_canonical_data_root",
            "user_triggered_only",
            "manual_result_review_required",
            "not_an_official_competition_submission",
            "does_not_validate_neural_realism",
        ],
    }


def run_full_run(
    adapter_id: str,
    *,
    method_config: dict[str, Any] | None,
    execution_config: dict[str, Any] | None,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Run the prepared, trusted command sequence and aggregate per-seed artifacts.

    This performs no state promotion.  The caller must explicitly review and
    register a result through the existing research workflow gate.
    """

    root = _project_root(project_root)
    prepared = prepare_full_run(
        adapter_id,
        method_config=method_config,
        execution_config=execution_config,
        project_root=root,
    )
    timeout_seconds = int(prepared["timeoutSecondsPerSeed"])
    records: list[dict[str, Any]] = []
    process_records: list[dict[str, Any]] = []
    for command in prepared["commands"]:
        args = list(command["args"])
        completed = _run_process(args, cwd=root, timeout_seconds=timeout_seconds)
        process_record = {
            "seed": command["seed"],
            "exitCode": int(completed.returncode),
            "stdout": _clip_text(completed.stdout),
            "stderr": _clip_text(completed.stderr),
        }
        process_records.append(process_record)
        if completed.returncode != 0:
            raise FormalRunnerError(
                f"Formal run failed for seed {command['seed']}: {_process_error(completed)}"
            )
        result_path = Path(str(command["outputDir"])) / "result.json"
        if not result_path.is_file():
            raise FormalRunnerError(f"Formal run for seed {command['seed']} did not create result.json")
        try:
            seed_result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FormalRunnerError(f"Unable to read seed {command['seed']} result artifact: {exc}") from exc
        records.append(
            {
                "seed": command["seed"],
                "resultPath": str(result_path),
                "artifactHash": str(seed_result.get("artifactHash") or ""),
                "decision": seed_result.get("decision") if isinstance(seed_result.get("decision"), dict) else {},
                "metrics": seed_result.get("metrics") if isinstance(seed_result.get("metrics"), dict) else {},
                "comparisonMatrix": (
                    seed_result.get("comparisonMatrix")
                    if isinstance(seed_result.get("comparisonMatrix"), list)
                    else []
                ),
                "sharedBaseline": seed_result.get("sharedBaseline") is True,
            }
        )

    aggregate = _aggregate_records(records)
    benchmark_matrix = _aggregate_benchmark_matrix(records)
    output_root = Path(str(prepared["environment"]["outputRoot"]))
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "formal-run-log.json"
    result_path = output_root / "formal-run-result.json"
    # Shared atomic-write helper (temp + fsync + os.replace) so an interrupted
    # backend can never leave a half-written summary behind.
    atomic_write_json(
        log_path,
        {"adapterId": adapter_id, "processes": process_records},
    )
    result = {
        "adapterId": FASHION_MNIST_MULTI_SEED_ADAPTER,
        "status": "completed",
        "executionMode": "local_process",
        "seedCount": len(records),
        "seeds": list(prepared["seeds"]),
        "runs": records,
        "aggregate": aggregate,
        "benchmarkMatrix": benchmark_matrix,
        "sharedBaseline": bool(benchmark_matrix) and all(record.get("sharedBaseline") is True for record in records),
        "resultPath": str(result_path),
        "logRef": str(log_path),
        "requiresResultReview": True,
        "automaticPromotion": False,
        "boundaries": list(prepared["boundaries"]),
    }
    atomic_write_json(result_path, result)
    return result


def _project_root(value: Path | str | None) -> Path:
    root = Path(value) if value is not None else Path.cwd()
    return root.expanduser().resolve()


def _required_path(value: Any, label: str, *, kind: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise FormalRunnerError(f"{label} is required.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise FormalRunnerError(f"{label} must be an absolute path.")
    resolved = path.resolve()
    if kind == "file" and not resolved.is_file():
        raise FormalRunnerError(f"{label} must reference an existing file.")
    if kind == "directory" and not resolved.is_dir():
        raise FormalRunnerError(f"{label} must reference an existing directory.")
    return resolved


def assert_canonical_project_data_path(
    value: Any,
    *,
    project_root: Path | str,
    label: str = "outputRoot",
    create: bool = False,
) -> Path:
    """Resolve a path inside the current project's canonical data root.

    The candidate is resolved before any directory is created so existing
    symlink/reparse ancestors cannot redirect a run outside the active
    instance. A missing leaf is valid when its resolved path remains inside
    the canonical root; ``create=True`` creates it only after that check.
    """

    raw = str(value or "").strip()
    if not raw:
        raise FormalRunnerError(f"{label} is required.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise FormalRunnerError(f"{label} must be an absolute path.")

    root = _project_root(project_root)
    try:
        canonical_root = Path(resolve_project_data_home(root)).expanduser().resolve(strict=False)
        resolved = path.resolve(strict=False)
        resolved.relative_to(canonical_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise FormalRunnerError(
            f"{label} must be inside the current project canonical data root."
        ) from exc

    if create and resolved.exists() and not resolved.is_dir():
        raise FormalRunnerError(
            f"{label} must be inside the current project canonical data root."
        )
    if create:
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            post_create = resolved.resolve(strict=False)
            post_create.relative_to(canonical_root)
            if not post_create.is_dir():
                raise OSError("resolved output path is not a directory")
        except (OSError, RuntimeError, ValueError) as exc:
            raise FormalRunnerError(
                f"{label} must be inside the current project canonical data root."
            ) from exc
    return resolved


def _validated_seeds(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        raise FormalRunnerError("methodConfig.seeds must be a list of integers.")
    seeds: list[int] = []
    for item in value:
        try:
            seed = int(item)
        except (TypeError, ValueError) as exc:
            raise FormalRunnerError("methodConfig.seeds must contain integers.") from exc
        if seed < 0 or seed > 2_147_483_647:
            raise FormalRunnerError("methodConfig.seeds values must be within the supported range.")
        if seed not in seeds:
            seeds.append(seed)
    if not _MIN_SEED_COUNT <= len(seeds) <= _MAX_SEED_COUNT:
        raise FormalRunnerError(
            f"methodConfig.seeds must contain {_MIN_SEED_COUNT} to {_MAX_SEED_COUNT} unique values."
        )
    return seeds


def _bounded_int(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise FormalRunnerError(f"{label} must be an integer.") from exc
    if not minimum <= normalized <= maximum:
        raise FormalRunnerError(f"{label} must be between {minimum} and {maximum}.")
    return normalized


def _bounded_float(value: Any, label: str, *, minimum: float, maximum: float) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise FormalRunnerError(f"{label} must be a number.") from exc
    if not minimum <= normalized <= maximum:
        raise FormalRunnerError(f"{label} must be between {minimum} and {maximum}.")
    return normalized


def _validated_mask_modes(value: Any, *, fallback: str) -> list[str]:
    raw_modes = value if isinstance(value, (list, tuple)) and value else [fallback]
    supported = {"aligned", "spatially_shifted", "deterministically_permuted"}
    modes: list[str] = []
    for item in raw_modes:
        mode = str(item or "").strip()
        if mode not in supported:
            raise FormalRunnerError("candidateLossMaskModes contains an unsupported mode.")
        if mode not in modes:
            modes.append(mode)
    return modes


def _validated_mask_sizes(value: Any, *, fallback: int) -> list[int]:
    raw_sizes = value if isinstance(value, (list, tuple)) and value else [fallback]
    sizes: list[int] = []
    for item in raw_sizes:
        size = _bounded_int(item, "evaluationMaskSizes", minimum=1, maximum=28)
        if size not in sizes:
            sizes.append(size)
    return sizes


def _experiment_command(
    *,
    python_executable: Path,
    script_path: Path,
    data_root: Path,
    output_dir: Path,
    seed: int,
    options: dict[str, Any],
) -> list[str]:
    command = [
        str(python_executable),
        str(script_path),
        "--data-root",
        str(data_root),
        "--output-dir",
        str(output_dir),
        "--seed",
        str(seed),
        "--train-samples",
        str(options["trainSamples"]),
        "--test-samples",
        str(options["testSamples"]),
        "--epochs",
        str(options["epochs"]),
        "--batch-size",
        str(options["batchSize"]),
        "--correction-steps",
        str(options["correctionSteps"]),
        "--correction-rate",
        str(options["correctionRate"]),
        "--mask-size",
        str(options["trainingMaskSize"]),
        "--candidate-mechanism",
        str(options["candidateMechanism"]),
        "--candidate-masked-loss-weight",
        str(options["candidateMaskedLossWeight"]),
        "--candidate-loss-mask-mode",
        str(options["candidateLossMaskMode"]),
        "--minimum-mse-improvement",
        str(options["minimumMseImprovement"]),
        "--maximum-latency-multiplier",
        str(options["maximumLatencyMultiplier"]),
        "--maximum-global-mse-regression",
        str(options["maximumGlobalMseRegression"]),
    ]
    if len(options["candidateLossMaskModes"]) > 1:
        command.extend(["--candidate-loss-mask-modes", *[str(mode) for mode in options["candidateLossMaskModes"]]])
    if options["evaluationMaskSizes"] != [options["trainingMaskSize"]]:
        command.extend(["--evaluation-mask-sizes", *[str(size) for size in options["evaluationMaskSizes"]]])
    return command


def _run_process(args: list[str], *, cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            **no_window_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise FormalRunnerError(f"Formal runner timed out after {timeout_seconds} seconds.") from exc
    except OSError as exc:
        raise FormalRunnerError(f"Formal runner could not start: {exc}") from exc


def _aggregate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise FormalRunnerError("No formal-run artifacts were collected.")
    mse_improvements = [_metric_value(record, "mse_improvement") for record in records]
    masked_improvements = [_metric_value(record, "masked_mse_improvement") for record in records]
    return {
        "mseImprovement": _summary(mse_improvements),
        "maskedMseImprovement": _summary(masked_improvements),
        "supportCount": sum(1 for record in records if record.get("decision", {}).get("status") == "support"),
        "inconclusiveCount": sum(1 for record in records if record.get("decision", {}).get("status") != "support"),
    }


def _aggregate_benchmark_matrix(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    per_seed: dict[int, dict[tuple[str, int], dict[str, Any]]] = {}
    for record in records:
        seed = int(record["seed"])
        seed_cells: dict[tuple[str, int], dict[str, Any]] = {}
        for raw_cell in record.get("comparisonMatrix") or []:
            if not isinstance(raw_cell, dict):
                continue
            mode = str(raw_cell.get("candidateLossMaskMode") or "")
            try:
                mask_size = int(raw_cell.get("maskSize"))
            except (TypeError, ValueError) as exc:
                raise FormalRunnerError("Benchmark matrix cell has an invalid maskSize.") from exc
            key = (mode, mask_size)
            if key in seed_cells:
                raise FormalRunnerError(f"Benchmark matrix contains duplicate cell for seed {seed}: {key}.")
            seed_cells[key] = raw_cell
            grouped.setdefault(key, []).append(raw_cell)
        per_seed[seed] = seed_cells
    if not grouped:
        return {}
    if any(set(seed_cells) != set(grouped) for seed_cells in per_seed.values()):
        raise FormalRunnerError("Benchmark matrix is incomplete across seeds.")
    cells = []
    for (mode, mask_size), entries in sorted(grouped.items()):
        cells.append(
            {
                "candidateLossMaskMode": mode,
                "maskSize": mask_size,
                "mseImprovement": _summary([_cell_metric(entry, "mse_improvement") for entry in entries]),
                "maskedMseImprovement": _summary(
                    [_cell_metric(entry, "masked_mse_improvement") for entry in entries]
                ),
                "latencyMultiplier": _summary([_cell_metric(entry, "latency_multiplier") for entry in entries]),
                "supportCount": sum(
                    1
                    for entry in entries
                    if isinstance(entry.get("decision"), dict) and entry["decision"].get("status") == "support"
                ),
                "inconclusiveCount": sum(
                    1
                    for entry in entries
                    if not isinstance(entry.get("decision"), dict) or entry["decision"].get("status") != "support"
                ),
            }
        )
    contrast_sizes = sorted(
        {
            mask_size
            for mode, mask_size in grouped
            if mode == "aligned" and ("deterministically_permuted", mask_size) in grouped
        }
    )
    contrasts = []
    for mask_size in contrast_sizes:
        values = [
            _cell_metric(seed_cells[("aligned", mask_size)], "masked_mse_improvement")
            - _cell_metric(seed_cells[("deterministically_permuted", mask_size)], "masked_mse_improvement")
            for seed_cells in per_seed.values()
        ]
        contrasts.append({"maskSize": mask_size, "maskedMseImprovement": _summary(values)})
    return {
        "cells": cells,
        "alignedMinusPermuted": contrasts,
        "seedCount": len(records),
        "complete": True,
    }


def _cell_metric(cell: dict[str, Any], name: str) -> float:
    metrics = cell.get("metrics") if isinstance(cell.get("metrics"), dict) else {}
    delta = metrics.get("delta") if isinstance(metrics.get("delta"), dict) else {}
    try:
        return float(delta[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise FormalRunnerError(f"Benchmark matrix cell is missing metrics.delta.{name}.") from exc


def _metric_value(record: dict[str, Any], name: str) -> float:
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    delta = metrics.get("delta") if isinstance(metrics.get("delta"), dict) else {}
    try:
        return float(delta[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise FormalRunnerError(f"Formal-run artifact is missing metrics.delta.{name}.") from exc


def _summary(values: list[float]) -> dict[str, Any]:
    mean = statistics.mean(values)
    stddev = statistics.pstdev(values)
    half_width = 1.96 * stddev / (len(values) ** 0.5)
    return {
        "count": len(values),
        "mean": round(mean, 10),
        "stddev": round(stddev, 10),
        "minimum": round(min(values), 10),
        "maximum": round(max(values), 10),
        "confidenceInterval95": {
            "method": "normal_approximation",
            "lower": round(mean - half_width, 10),
            "upper": round(mean + half_width, 10),
        },
    }


def _clip_process_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "exitCode": int(result.returncode),
        "stdout": _clip_text(result.stdout),
        "stderr": _clip_text(result.stderr),
    }


def _process_error(result: subprocess.CompletedProcess[str]) -> str:
    return _clip_text(result.stderr) or _clip_text(result.stdout) or f"exitCode={result.returncode}"


def _clip_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}…"
