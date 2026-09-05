"""SCI-091 CUDA operator-fusion benchmark with correctness-first timing.

The benchmark intentionally supports one bounded operator family.  It follows
the mature GPU microbenchmark pattern used by TritonBench/NVBench: compile and
warm up outside the timed region, verify numerical equivalence, synchronize
the device around measurements, repeat, and persist device/toolchain metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


def _torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch with CUDA support is required") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available to PyTorch")
    if not hasattr(torch, "compile"):
        raise RuntimeError("torch.compile is required for the fused candidate")
    return torch


def _device_metadata(torch) -> dict[str, Any]:
    index = torch.cuda.current_device()
    properties = torch.cuda.get_device_properties(index)
    return {
        "deviceIndex": index,
        "name": properties.name,
        "totalMemoryBytes": int(properties.total_memory),
        "computeCapability": f"{properties.major}.{properties.minor}",
        "torchVersion": torch.__version__,
        "cudaRuntimeVersion": str(torch.version.cuda or ""),
        "pythonVersion": platform.python_version(),
    }


def self_check() -> dict[str, Any]:
    torch = _torch()
    return {"status": "ok", "device": _device_metadata(torch)}


def _measure_cuda_ms(
    torch,
    fn: Callable[[], Any],
    *,
    warmup_iterations: int,
    measurement_iterations: int,
) -> list[float]:
    for _ in range(warmup_iterations):
        fn()
    torch.cuda.synchronize()
    values: list[float] = []
    for _ in range(measurement_iterations):
        start = torch.cuda.Event(enable_timing=True)
        stop = torch.cuda.Event(enable_timing=True)
        start.record()
        fn()
        stop.record()
        stop.synchronize()
        values.append(float(start.elapsed_time(stop)))
    return values


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "count": float(len(values)),
        "medianMs": round(float(statistics.median(ordered)), 6),
        "meanMs": round(float(statistics.mean(ordered)), 6),
        "minimumMs": round(float(ordered[0]), 6),
        "maximumMs": round(float(ordered[-1]), 6),
    }


def run_benchmark(
    *,
    operator_family: str,
    warmup_iterations: int,
    measurement_iterations: int,
    tensor_elements: int,
) -> dict[str, Any]:
    if operator_family != "elementwise_fusion":
        raise RuntimeError("unsupported operator family")
    torch = _torch()
    torch.manual_seed(20260905)
    x = torch.randn(tensor_elements, device="cuda", dtype=torch.float32)
    bias = torch.randn(tensor_elements, device="cuda", dtype=torch.float32)
    scale = torch.tensor(0.125, device="cuda", dtype=torch.float32)

    def baseline():
        shifted = x + bias
        activated = torch.relu(shifted)
        return activated * scale

    candidate = torch.compile(baseline, fullgraph=True)
    expected = baseline()
    actual = candidate()
    torch.cuda.synchronize()
    torch.testing.assert_close(actual, expected, rtol=1e-5, atol=1e-6)

    baseline_ms = _measure_cuda_ms(
        torch,
        baseline,
        warmup_iterations=warmup_iterations,
        measurement_iterations=measurement_iterations,
    )
    candidate_ms = _measure_cuda_ms(
        torch,
        candidate,
        warmup_iterations=warmup_iterations,
        measurement_iterations=measurement_iterations,
    )
    baseline_summary = _summary(baseline_ms)
    candidate_summary = _summary(candidate_ms)
    speedup = baseline_summary["medianMs"] / candidate_summary["medianMs"]
    body = {
        "schemaVersion": 1,
        "questionId": "SCI-091",
        "status": "benchmark_complete",
        "createdAt": datetime.now(UTC).isoformat(),
        "operatorFamily": operator_family,
        "correctness": {
            "passed": True,
            "rtol": 1e-5,
            "atol": 1e-6,
        },
        "protocol": {
            "warmupIterations": warmup_iterations,
            "measurementIterations": measurement_iterations,
            "tensorElements": tensor_elements,
            "synchronization": "cuda_event_stop_synchronize_each_iteration",
            "compileOutsideTimedRegion": True,
        },
        "metrics": {
            "baseline": baseline_summary,
            "candidate": candidate_summary,
            "medianSpeedup": round(speedup, 6),
        },
        "environment": _device_metadata(torch),
        "claimBoundary": "device-specific microbenchmark; no cross-device generalization",
    }
    body["contentSha256"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--operator-family", default="elementwise_fusion")
    parser.add_argument("--warmup-iterations", type=int, default=25)
    parser.add_argument("--measurement-iterations", type=int, default=100)
    parser.add_argument("--tensor-elements", type=int, default=1_048_576)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_check:
        try:
            result = self_check()
        except RuntimeError as exc:
            print(
                json.dumps(
                    {"status": "blocked", "reason": str(exc)},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.output is None:
        raise SystemExit("--output is required unless --self-check is used")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite append-only artifact: {args.output}")
    result = run_benchmark(
        operator_family=args.operator_family,
        warmup_iterations=args.warmup_iterations,
        measurement_iterations=args.measurement_iterations,
        tensor_elements=args.tensor_elements,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
