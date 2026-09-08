"""Real serial CUDA measurements for the bounded row-softmax candidate family.

The caller owns process isolation, device reservation and billing. This worker
never imports model-generated Python and never falls back to a CPU fixture.
"""
from __future__ import annotations

import math
import platform
import random
import time

from core.research.workflow.contracts._canonical import sha256_hex

from .candidate import CudaCandidate, source_hash
from .evaluation import workload_hash
from .measurement import (
    CaseMeasurement,
    MeasurementProtocol,
    OperatorMeasurement,
    PairedTiming,
)


class CudaEnvironmentUnavailable(RuntimeError):
    pass


def inspect_cuda_environment() -> dict:
    try:
        import torch
    except ModuleNotFoundError as exc:
        if exc.name != "torch":
            raise
        raise CudaEnvironmentUnavailable("CUDA-enabled PyTorch is not installed in the worker environment") from exc
    if not torch.cuda.is_available():
        raise CudaEnvironmentUnavailable("A real CUDA device and CUDA-enabled PyTorch are required")
    properties = torch.cuda.get_device_properties(0)
    return {"deviceKind": "cuda", "deviceIndex": 0, "deviceName": properties.name,
        "capability": list(torch.cuda.get_device_capability(0)), "totalMemoryBytes": properties.total_memory,
        "deviceUuid": str(getattr(properties, "uuid", "")),
        "python": platform.python_version(), "platform": platform.platform(),
        "torch": torch.__version__, "cuda": torch.version.cuda}


def _operation(candidate: CudaCandidate):
    import torch
    if candidate.implementation == "torch_softmax":
        return lambda x: torch.softmax(x, dim=-1)
    from .triton_softmax import softmax
    return lambda x: softmax(x, num_warps=candidate.numWarps)


def measure_cuda(*, protocol: MeasurementProtocol, baseline: CudaCandidate,
    parent: CudaCandidate, candidate: CudaCandidate, campaign_id: str, run_id: str,
    measurement_id: str, expected_environment_hash: str, max_seconds: float) -> OperatorMeasurement:
    import torch
    if max_seconds <= 0:
        raise ValueError("A positive reserved device-time budget is required")
    started = time.monotonic()
    environment = inspect_cuda_environment()
    if sha256_hex(environment) != expected_environment_hash:
        raise ValueError("CUDA environment changed since protocol freeze")
    rows = []
    status, failure = "succeeded", ""

    def check_time():
        if time.monotonic() - started >= max_seconds:
            raise TimeoutError("Reserved GPU time exhausted")

    try:
        operations = [_operation(spec) for spec in (baseline, parent, candidate)]
        with torch.inference_mode(), torch.cuda.device(0):
            for case in protocol.cases:
                check_time()
                generator = torch.Generator(device="cuda").manual_seed(case.seed)
                source = torch.randn((case.rows, case.columns), generator=generator, device="cuda", dtype=torch.float32)
                if case.distribution == "large_magnitude":
                    source.mul_(100)
                elif case.distribution == "constant":
                    source.fill_(1)
                source = source.to(getattr(torch, case.dtype))
                reference = torch.softmax(source.to(torch.float64), dim=-1)
                outputs = [operation(source) for operation in operations]
                torch.cuda.synchronize()
                correct = all(bool(torch.isfinite(output).all()) and
                    torch.allclose(output.to(torch.float64), reference, atol=protocol.atol, rtol=protocol.rtol)
                    for output in outputs)
                error = max(float((output.to(torch.float64) - reference).abs().max()) for output in outputs)
                if not correct:
                    rows.append(CaseMeasurement(caseId=case.caseId, correctnessPassed=False,
                        maxAbsoluteError=error if math.isfinite(error) else None))
                    raise ValueError(f"Correctness failed for {case.caseId}")
                for _ in range(protocol.warmup):
                    check_time()
                    for operation in operations:
                        operation(source)
                torch.cuda.synchronize()
                timings = []
                rng = random.Random(case.seed)
                for _ in range(protocol.pairs):
                    check_time()
                    order = [0, 1, 2]
                    rng.shuffle(order)
                    observed = [0.0, 0.0, 0.0]
                    for index in order:
                        start, stop = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                        start.record()
                        _output = operations[index](source)
                        stop.record()
                        stop.synchronize()
                        observed[index] = float(start.elapsed_time(stop))
                    timings.append(PairedTiming(baselineMs=observed[0], parentMs=observed[1], candidateMs=observed[2]))
                rows.append(CaseMeasurement(caseId=case.caseId, correctnessPassed=True,
                    maxAbsoluteError=error, timings=tuple(timings)))
    except TimeoutError as exc:
        status, failure = "timed_out", str(exc)
    except Exception as exc:  # noqa: BLE001 - runner failures are terminal evidence
        # Failure is a terminal observation, never a made-up performance score.
        status, failure = "failed", f"{type(exc).__name__}: {exc}"[:2000]
    return OperatorMeasurement(measurementId=measurement_id, optimizationCampaignId=campaign_id,
        runId=run_id, protocolHash=sha256_hex(protocol.model_dump(mode="json")), workloadHash=workload_hash(protocol),
        environmentHash=sha256_hex(environment), baselineSourceHash=source_hash(baseline),
        parentSourceHash=source_hash(parent), candidateSourceHash=source_hash(candidate),
        deviceName=environment["deviceName"], status=status, failureReason=failure,
        gpuSeconds=time.monotonic() - started, cases=tuple(rows))
