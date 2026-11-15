"""A bounded CUDA worker with a durable receipt before canonical publication.

gpuSeconds charges elapsed device lease time (including startup/compilation),
not CUDA kernel timing. Waiting for the lease is excluded.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import ContextManager
from uuid import uuid4

from core.infrastructure.codex_sandbox.process import (
    sandbox_popen_kwargs,
    terminate_process_tree,
)
from core.infrastructure.file_lock import cross_process_file_lock
from core.research.operator_optimization.cuda_worker import (
    CudaMeasurementIdentity,
    CudaTrialRequest,
    CudaWorkerInvocation,
    CudaWorkerReceipt,
)
from core.research.operator_optimization.measurement import OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services.team_workflow.storage_durability import inter_process_lock


@dataclass(frozen=True)
class TrialReceiptTarget:
    path: Path
    fingerprint: str
    launch_id: str
    identity: CudaMeasurementIdentity

    def read(self) -> CudaWorkerReceipt | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        receipt = CudaWorkerReceipt.model_validate_json(text)
        if (receipt.fingerprint, receipt.launchId) != (self.fingerprint, self.launch_id):
            raise ValueError("Worker receipt belongs to a different trial launch")
        if receipt.measurement is not None and not self.identity.matches(receipt.measurement):
            raise ValueError("Worker measurement identity or frozen inputs differ")
        return receipt

    def persist(self, measurement: OperatorMeasurement) -> None:
        if not self.identity.matches(measurement):
            raise ValueError("Worker measurement identity or frozen inputs differ")
        CudaWorkerReceipt(fingerprint=self.fingerprint, launchId=self.launch_id,
            outcome="terminal", measurement=measurement).persist(self.path)


def _device_lease_path() -> Path:
    return Path(tempfile.gettempdir()) / "vibelution-operator-cuda" / "device-0"


def cuda_worker_lease_busy() -> bool:
    try:
        with cross_process_file_lock(_device_lease_path().with_name("device-0-active"), timeout=0):
            return False
    except TimeoutError:
        return True


def execute_cuda_trial(
    request: CudaTrialRequest, *, device_name: str,
    receipt_target: TrialReceiptTarget | None = None,
    start_fence: Callable[[], ContextManager[None]] | None = None,
) -> OperatorMeasurement:
    # Host-wide, independent of project/worktree. Worker currently owns device 0.
    lease = _device_lease_path()
    worker_lease = lease.with_name("device-0-active")
    with ExitStack() as device_lease:
        try:
            device_lease.enter_context(inter_process_lock(lease, timeout_s=0))
            # A previous child may still be alive across a backend crash.
            # The child also takes this lock as the final CUDA authority.
            with cross_process_file_lock(worker_lease, timeout=0):
                pass
        except OSError as exc:
            # Windows lock contention raises PermissionError, POSIX raises
            # BlockingIOError. Only acquisition failures prove no worker ran;
            # errors after acquisition must retain their original meaning.
            raise BlockingIOError("CUDA device lease is unavailable; worker was not started") from exc
        started = time.monotonic_ns()
        status, reason = "failed", "Worker did not return a measurement"
        with tempfile.TemporaryDirectory(prefix="operator-cuda-") as temporary:
            input_path = Path(temporary) / "input.json"
            target = receipt_target or TrialReceiptTarget(
                path=Path(temporary) / "output.json",
                fingerprint=sha256_hex(request.model_dump(mode="json")),
                launch_id=uuid4().hex,
                identity=CudaMeasurementIdentity.from_request(request, device_name),
            )
            invocation = CudaWorkerInvocation(
                request=request, identity=target.identity, fingerprint=target.fingerprint,
                launchId=target.launch_id, leaseStartedNs=started, deviceLease=str(worker_lease),
            )
            input_path.write_text(invocation.model_dump_json(), encoding="utf-8")
            process = None
            try:
                with start_fence() if start_fence is not None else nullcontext():
                    try:
                        process = subprocess.Popen(
                            [sys.executable, "-m", "core.research.operator_optimization.cuda_worker",
                                str(input_path), str(target.path)],
                            cwd=Path(__file__).resolve().parents[5],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            **sandbox_popen_kwargs(),
                        )
                    except OSError as exc:
                        reason = f"CUDA worker failed to start: {exc}"[:2000]
                if process is not None:
                    try:
                        code = process.wait(timeout=request.max_seconds)
                        if code != 0:
                            reason = f"CUDA worker exited with code {code}"
                    except subprocess.TimeoutExpired:
                        status, reason = "timed_out", "CUDA worker exceeded reserved device lease time"
            finally:
                if process is not None:
                    terminate_process_tree(process)
                    process.wait(timeout=5)

            try:
                receipt = target.read()
            except ValueError:
                receipt = None
                reason = "CUDA worker returned an invalid terminal receipt"
            if receipt is not None:
                if receipt.measurement is None:
                    raise BlockingIOError("CUDA device lease is unavailable; worker was not started")
                return receipt.measurement

            # The supervisor can attest a failure only when it has observed
            # spawn fail, or has reaped the child and obtained its outcome.
            elapsed = (time.monotonic_ns() - started) / 1e9 if process is not None else 0
            result = OperatorMeasurement(**target.identity.model_dump(),
                status=status, failureReason=reason, gpuSeconds=elapsed)
            target.persist(result)
            return result
