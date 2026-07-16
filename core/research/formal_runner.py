"""Trusted, opt-in local runner for bounded multi-seed Challenge Cup experiments.

This module deliberately keeps the process boundary small:

* it only invokes the repository-owned FashionMNIST script;
* the Python executable, data root, and artifact root must be explicit;
* output artifacts must live outside the repository; and
* completed execution is evidence for review, never an automatic research claim.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path
from typing import Any

from scripts.windowless_subprocess import no_window_subprocess_kwargs


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
    output_root = _external_output_root(execution.get("outputRoot"), root)
    timeout_seconds = _bounded_int(
        execution.get("timeoutSeconds", _DEFAULT_TIMEOUT_SECONDS),
        "timeoutSeconds",
        minimum=_MIN_TIMEOUT_SECONDS,
        maximum=_MAX_TIMEOUT_SECONDS,
    )
    run_options = {
        "trainSamples": _bounded_int(execution.get("trainSamples", 4096), "trainSamples", minimum=1, maximum=60000),
        "testSamples": _bounded_int(execution.get("testSamples", 1024), "testSamples", minimum=1, maximum=10000),
        "epochs": _bounded_int(execution.get("epochs", 8), "epochs", minimum=1, maximum=1000),
        "batchSize": _bounded_int(execution.get("batchSize", 64), "batchSize", minimum=1, maximum=2048),
        "correctionSteps": _bounded_int(execution.get("correctionSteps", 3), "correctionSteps", minimum=1, maximum=64),
        "correctionRate": _bounded_float(execution.get("correctionRate", 0.8), "correctionRate", minimum=0.0, maximum=10.0),
    }

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
            "artifacts_outside_repository",
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
            }
        )

    aggregate = _aggregate_records(records)
    output_root = Path(str(prepared["environment"]["outputRoot"]))
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "formal-run-log.json"
    result_path = output_root / "formal-run-result.json"
    log_path.write_text(
        json.dumps({"adapterId": adapter_id, "processes": process_records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result = {
        "adapterId": FASHION_MNIST_MULTI_SEED_ADAPTER,
        "status": "completed",
        "executionMode": "local_process",
        "seedCount": len(records),
        "seeds": list(prepared["seeds"]),
        "runs": records,
        "aggregate": aggregate,
        "resultPath": str(result_path),
        "logRef": str(log_path),
        "requiresResultReview": True,
        "automaticPromotion": False,
        "boundaries": list(prepared["boundaries"]),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
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


def _external_output_root(value: Any, project_root: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise FormalRunnerError("outputRoot is required.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise FormalRunnerError("outputRoot must be an absolute path.")
    resolved = path.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError:
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
    raise FormalRunnerError("outputRoot must be outside the repository.")


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


def _experiment_command(
    *,
    python_executable: Path,
    script_path: Path,
    data_root: Path,
    output_dir: Path,
    seed: int,
    options: dict[str, Any],
) -> list[str]:
    return [
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
    ]


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


def _metric_value(record: dict[str, Any], name: str) -> float:
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    delta = metrics.get("delta") if isinstance(metrics.get("delta"), dict) else {}
    try:
        return float(delta[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise FormalRunnerError(f"Formal-run artifact is missing metrics.delta.{name}.") from exc


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "mean": round(statistics.mean(values), 10),
        "stddev": round(statistics.pstdev(values), 10),
        "minimum": round(min(values), 10),
        "maximum": round(max(values), 10),
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
