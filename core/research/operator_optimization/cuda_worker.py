"""Private JSON file boundary for the isolated, controlled CUDA worker."""
from __future__ import annotations

import sys
from pathlib import Path

from pydantic import Field

from .contracts import Contract, Digest, Identity
from .cuda_runner import CudaCandidate, measure_cuda
from .measurement import MeasurementProtocol


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


def main() -> None:
    request = CudaTrialRequest.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = measure_cuda(**{name: getattr(request, name) for name in type(request).model_fields})
    Path(sys.argv[2]).write_text(result.model_dump_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
