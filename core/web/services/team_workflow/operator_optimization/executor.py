"""One host CUDA lease and a bounded worker process; callers persist receipts.

gpuSeconds charges elapsed device lease time (including startup/compilation),
not CUDA kernel timing. Waiting for the lease is excluded.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

from core.infrastructure.codex_sandbox.process import (
    sandbox_popen_kwargs,
    terminate_process_tree,
)
from core.research.operator_optimization.cuda_runner import source_hash
from core.research.operator_optimization.cuda_worker import CudaTrialRequest
from core.research.operator_optimization.evaluation import workload_hash
from core.research.operator_optimization.measurement import OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services.team_workflow.storage_durability import inter_process_lock


def execute_cuda_trial(request: CudaTrialRequest, *, device_name: str) -> OperatorMeasurement:
    # Host-wide, independent of project/worktree. Worker currently owns device 0.
    lease = Path(tempfile.gettempdir()) / "vibelution-operator-cuda" / "device-0"
    with ExitStack() as device_lease:
        try:
            device_lease.enter_context(inter_process_lock(lease, timeout_s=0))
        except OSError as exc:
            # Windows lock contention raises PermissionError, POSIX raises
            # BlockingIOError. Only acquisition failures prove no worker ran;
            # errors after acquisition must retain their original meaning.
            raise BlockingIOError("CUDA device lease is unavailable; worker was not started") from exc
        started = time.monotonic()
        expected = {
            "measurementId": request.measurement_id,
            "optimizationCampaignId": request.campaign_id,
            "runId": request.run_id,
            "protocolHash": sha256_hex(request.protocol.model_dump(mode="json")),
            "workloadHash": workload_hash(request.protocol),
            "environmentHash": request.expected_environment_hash,
            "baselineSourceHash": source_hash(request.baseline),
            "parentSourceHash": source_hash(request.parent),
            "candidateSourceHash": source_hash(request.candidate),
        }
        status, reason = "failed", "Worker did not return a measurement"
        result = None
        with tempfile.TemporaryDirectory(prefix="operator-cuda-") as temporary:
            input_path, output_path = Path(temporary) / "input.json", Path(temporary) / "output.json"
            input_path.write_text(request.model_dump_json(), encoding="utf-8")
            process = None
            try:
                process = subprocess.Popen([sys.executable, "-m", "core.research.operator_optimization.cuda_worker",
                    str(input_path), str(output_path)], cwd=Path(__file__).resolve().parents[5],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    **sandbox_popen_kwargs())
            except OSError as exc:
                # Popen failed before a child existed. Emit a terminal failure
                # with zero GPU usage so dispatch can settle the admission and
                # never confuse startup failure with an uncertain execution.
                reason = f"CUDA worker failed to start: {exc}"[:2000]
            if process is not None:
                try:
                    try:
                        code = process.wait(timeout=request.max_seconds)
                        if code != 0:
                            reason = f"CUDA worker exited with code {code}"
                        elif output_path.exists():
                            try:
                                result = OperatorMeasurement.model_validate_json(output_path.read_text(encoding="utf-8"))
                                if any(getattr(result, key) != value for key, value in expected.items()):
                                    raise ValueError("Worker measurement identity or frozen inputs differ")
                            except ValueError as exc:
                                result = None
                                reason = str(exc)[:2000]
                    except subprocess.TimeoutExpired:
                        status, reason = "timed_out", "CUDA worker exceeded reserved device lease time"
                finally:
                    terminate_process_tree(process)
                    process.wait(timeout=5)
        elapsed = time.monotonic() - started
        if result is not None:
            return result.model_copy(update={"gpuSeconds": elapsed})
        return OperatorMeasurement(**expected, deviceName=device_name,
            status=status, failureReason=reason, gpuSeconds=elapsed if process is not None else 0)
