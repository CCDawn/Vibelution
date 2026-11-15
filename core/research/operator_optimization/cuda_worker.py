"""Private JSON file boundary for the isolated, controlled CUDA worker."""
from __future__ import annotations

import json
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from core.infrastructure.atomic_io import atomic_write_text
from core.infrastructure.file_lock import cross_process_file_lock
from core.research.workflow.contracts._canonical import sha256_hex

from .contracts import Contract, Digest, Identity
from .cuda_runner import CudaCandidate, measure_cuda, source_hash
from .evaluation import workload_hash
from .measurement import MeasurementProtocol, OperatorMeasurement


class CudaTrialRequest(Contract):
    protocol: MeasurementProtocol
    baseline: CudaCandidate
    parent: CudaCandidate
    candidate: CudaCandidate
    campaign_id: Identity
    run_id: Identity
    measurement_id: Identity
    expected_environment_hash: Digest
    max_seconds: float = Field(gt=0)


class CudaMeasurementIdentity(Contract):
    measurementId: Identity
    optimizationCampaignId: Identity
    runId: Identity
    protocolHash: Digest
    workloadHash: Digest
    environmentHash: Digest
    baselineSourceHash: Digest
    parentSourceHash: Digest
    candidateSourceHash: Digest
    deviceName: str = Field(min_length=1, max_length=240)

    @classmethod
    def from_request(cls, request: CudaTrialRequest, device_name: str) -> CudaMeasurementIdentity:
        return cls(
            measurementId=request.measurement_id,
            optimizationCampaignId=request.campaign_id,
            runId=request.run_id,
            protocolHash=sha256_hex(request.protocol.model_dump(mode="json")),
            workloadHash=workload_hash(request.protocol),
            environmentHash=request.expected_environment_hash,
            baselineSourceHash=source_hash(request.baseline),
            parentSourceHash=source_hash(request.parent),
            candidateSourceHash=source_hash(request.candidate),
            deviceName=device_name,
        )

    def matches(self, measurement: OperatorMeasurement) -> bool:
        return all(getattr(measurement, name) == value for name, value in self.model_dump().items())


class CudaWorkerInvocation(Contract):
    request: CudaTrialRequest
    identity: CudaMeasurementIdentity
    fingerprint: Digest
    launchId: Identity
    leaseStartedNs: int = Field(ge=0)
    deviceLease: str


class CudaWorkerReceipt(Contract):
    fingerprint: Digest
    launchId: Identity
    outcome: Literal["terminal", "device_busy"]
    measurement: OperatorMeasurement | None

    @model_validator(mode="after")
    def paired_outcome(self) -> CudaWorkerReceipt:
        if (self.outcome == "terminal") != (self.measurement is not None):
            raise ValueError("CUDA worker receipt outcome differs from its measurement")
        return self

    def persist(self, path: Path) -> None:
        atomic_write_text(path, self.model_dump_json(), strict_replace=True)


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    output = Path(sys.argv[2])
    if isinstance(data, dict) and "request" not in data:
        # A supervisor already running at source cutover still sends the
        # original request and expects a bare measurement response.
        request = CudaTrialRequest.model_validate(data)
        result = measure_cuda(**{name: getattr(request, name) for name in type(request).model_fields})
        atomic_write_text(output, result.model_dump_json(), strict_replace=True)
        return

    invocation = CudaWorkerInvocation.model_validate(data)
    binding = {"fingerprint": invocation.fingerprint, "launchId": invocation.launchId}
    # This lease stays held if the backend dies while the worker is running.
    with ExitStack() as lease:
        try:
            lease.enter_context(cross_process_file_lock(invocation.deviceLease, timeout=0))
        except TimeoutError:
            CudaWorkerReceipt(**binding, outcome="device_busy", measurement=None).persist(output)
            return

        request = invocation.request
        started = invocation.leaseStartedNs
        try:
            result = measure_cuda(**{name: getattr(request, name) for name in type(request).model_fields})
            if not invocation.identity.matches(result):
                raise ValueError("Worker measurement identity or frozen inputs differ")
            result = result.model_copy(update={"gpuSeconds": (time.monotonic_ns() - started) / 1e9})
        except Exception as exc:
            result = OperatorMeasurement(
                **invocation.identity.model_dump(), status="failed",
                failureReason=f"{type(exc).__name__}: {exc}"[:2000],
                gpuSeconds=(time.monotonic_ns() - started) / 1e9,
            )
        CudaWorkerReceipt(**binding, outcome="terminal", measurement=result).persist(output)


if __name__ == "__main__":
    main()
