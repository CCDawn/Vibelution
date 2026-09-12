import subprocess
import sys

import pytest

from core.research.operator_optimization.cuda_worker import CudaTrialRequest
from core.web.services.team_workflow.operator_optimization import executor


@pytest.fixture(autouse=True)
def isolated_device_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))


@pytest.fixture
def request_data():
    return CudaTrialRequest(protocol={"protocolId": "p1", "split": "tuning", "cases": [
        {"caseId": "c1", "rows": 2, "columns": 32, "dtype": "float32", "seed": 1}]},
        baseline={"implementation": "torch_softmax"}, parent={"implementation": "torch_softmax"},
        candidate={"implementation": "torch_softmax"}, campaign_id="campaign1", run_id="run1",
        measurement_id="trial1", expected_environment_hash="a" * 64, max_seconds=0.2)


def replace_worker(monkeypatch, code):
    original = subprocess.Popen
    processes = []

    def start(args, **kwargs):
        process = original([sys.executable, "-c", code, *args[-2:]], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(executor.subprocess, "Popen", start)
    return processes


def test_timeout_reaps_real_worker_and_releases_device(monkeypatch, request_data):
    processes = replace_worker(monkeypatch, "import time; time.sleep(30)")
    result = executor.execute_cuda_trial(request_data, device_name="test device")
    assert result.status == "timed_out"
    assert result.gpuSeconds >= request_data.max_seconds
    assert processes[0].poll() is not None
    # The second lease must be immediately obtainable after termination.
    again = executor.execute_cuda_trial(request_data, device_name="test device")
    assert again.status == "timed_out"


def test_abnormal_exit_retains_failure_cost(monkeypatch, request_data):
    replace_worker(monkeypatch, "raise SystemExit(7)")
    result = executor.execute_cuda_trial(request_data, device_name="test device")
    assert result.status == "failed"
    assert "code 7" in result.failureReason
    assert result.gpuSeconds > 0
    assert result.measurementId == "trial1"
    assert not result.cases


def test_worker_start_failure_is_terminal_without_gpu_cost(monkeypatch, request_data):
    def fail_start(*args, **kwargs):
        raise FileNotFoundError("cuda worker executable missing")

    monkeypatch.setattr(executor.subprocess, "Popen", fail_start)
    result = executor.execute_cuda_trial(request_data, device_name="test device")
    assert result.status == "failed"
    assert "failed to start" in result.failureReason
    assert result.gpuSeconds == 0
    assert not result.cases


def test_invalid_worker_receipt_is_not_success(monkeypatch, request_data):
    replace_worker(monkeypatch, "import pathlib,sys; pathlib.Path(sys.argv[2]).write_text('{}')")
    result = executor.execute_cuda_trial(request_data, device_name="test device")
    assert result.status == "failed"
    assert result.failureReason


def test_busy_device_does_not_spawn_worker(monkeypatch, request_data):
    from contextlib import contextmanager

    @contextmanager
    def busy(*args, **kwargs):
        raise BlockingIOError("device busy")
        yield

    monkeypatch.setattr(executor, "inter_process_lock", busy)
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(BlockingIOError):
        executor.execute_cuda_trial(request_data, device_name="test device")
