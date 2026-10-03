from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.infrastructure.owned_process import OwnedProcess
import scripts.web_workbench as workbench_entrypoint


PROJECT_ROOT = Path(__file__).resolve().parents[1]

_FIXTURE_SERVER_SCRIPT = r'''
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, sys.argv[5])

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

import core.web.server_shutdown as server_shutdown
from core.web.server_shutdown import mark_server_shutdown_clean, own_server, schedule_server_shutdown
from core.web.startup_jobs import StartupJobGroup
from scripts.web_workbench import create_workbench_server


marker_dir = Path(sys.argv[1])
mode = sys.argv[2]
port = int(sys.argv[3])
watchdog_timeout = float(sys.argv[4])


def mark(name: str, value: object = True) -> None:
    (marker_dir / name).write_text(json.dumps(value), encoding="utf-8")


jobs: StartupJobGroup
executor: ThreadPoolExecutor | None = None
server = None


def force_exit(code: int) -> None:
    mark(
        "watchdog-fired",
        {
            "activeServerRegistered": server_shutdown._ACTIVE_SERVER is server,
            "serverShouldExit": bool(server and server.should_exit),
        },
    )
    os._exit(code)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global executor, jobs
    jobs = StartupJobGroup()
    if mode == "stuck-worker":
        def block_until_process_exit() -> None:
            mark("worker-started")
            threading.Event().wait()

        jobs.start_thread("fixture-stuck-worker", block_until_process_exit)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fixture-open-executor")
        executor.submit(threading.Event().wait)
    mark("lifespan-started")
    try:
        yield
    finally:
        result = await jobs.shutdown(deadline=time.monotonic() + 0.2)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        mark("lifespan-finally", result)
        if result.get("closed") is True:
            mark_server_shutdown_clean()


app = FastAPI(lifespan=lifespan)


@app.get("/ready")
async def ready() -> dict[str, bool]:
    return {"ready": True}


@app.get("/hold")
async def hold_request() -> dict[str, bool]:
    mark("http-request-started")
    try:
        await asyncio.Event().wait()
    finally:
        mark("http-handler-finally")
    return {"finished": True}


@app.get("/events")
async def hold_event_stream() -> StreamingResponse:
    async def generate():
        mark("sse-request-started")
        try:
            yield b"data: connected\n\n"
            await asyncio.Event().wait()
        finally:
            mark("sse-generator-finally")

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/shutdown")
async def shutdown() -> dict[str, bool]:
    return {
        "scheduled": schedule_server_shutdown(
            delay_seconds=0.05,
            hard_exit_timeout_seconds=watchdog_timeout,
            hard_exit=force_exit,
        )
    }


server = create_workbench_server(app, host="127.0.0.1", port=port)
with own_server(server):
    server.run()
mark(
    "own-server-exited",
    {"activeServerRegistered": server_shutdown._ACTIVE_SERVER is server},
)
'''


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _spawn_fixture_server(
    tmp_path: Path,
    *,
    mode: str,
    watchdog_timeout: float = 5.0,
) -> tuple[OwnedProcess, int, Path]:
    script_path = tmp_path / "fixture_uvicorn_server.py"
    script_path.write_text(_FIXTURE_SERVER_SCRIPT, encoding="utf-8")
    port = _free_loopback_port()
    log_path = tmp_path / "fixture_uvicorn.log"
    log_handle = log_path.open("wb")
    try:
        owner = OwnedProcess.spawn(
            [
                sys.executable,
                str(script_path),
                str(tmp_path),
                mode,
                str(port),
                str(watchdog_timeout),
                str(PROJECT_ROOT),
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    finally:
        log_handle.close()
    return owner, port, log_path


def _log_tail(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-3000:]
    except OSError:
        return "<no child log>"


def _wait_for_marker(
    owner: OwnedProcess,
    marker_dir: Path,
    name: str,
    log_path: Path,
    *,
    timeout: float = 8.0,
) -> Any:
    marker_path = marker_dir / name
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker_path.is_file():
            try:
                return json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        if owner.process.poll() is not None:
            raise AssertionError(
                f"fixture server exited before {name}; code={owner.process.returncode}; log={_log_tail(log_path)}"
            )
        time.sleep(0.02)
    raise AssertionError(f"fixture marker {name!r} did not appear; log={_log_tail(log_path)}")


def _wait_for_ready(owner: OwnedProcess, port: int, log_path: Path) -> None:
    url = f"http://127.0.0.1:{port}/ready"
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if owner.process.poll() is not None:
            raise AssertionError(
                f"fixture server exited before readiness; code={owner.process.returncode}; log={_log_tail(log_path)}"
            )
        try:
            response = httpx.get(url, timeout=0.2, trust_env=False)
            if response.status_code == 200 and response.json() == {"ready": True}:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.02)
    raise AssertionError(f"fixture server did not become ready; log={_log_tail(log_path)}")


def _request_shutdown(port: int) -> None:
    response = httpx.get(f"http://127.0.0.1:{port}/shutdown", timeout=3.0, trust_env=False)
    assert response.status_code == 200
    assert response.json() == {"scheduled": True}


def _cleanup_owned_process(owner: OwnedProcess) -> None:
    try:
        owner.close(timeout=8.0)
    except (OSError, RuntimeError):
        # A root exit does not imply its Windows Job descendants are gone.
        if owner._job is not None:
            owner._job.close()
        if owner.process.poll() is None:
            owner.process.kill()
            owner.process.wait(timeout=3.0)


def test_entrypoint_server_factory_has_bounded_http_drain() -> None:
    server = workbench_entrypoint.create_workbench_server(
        "fixture.module:app",
        host="127.0.0.1",
        port=_free_loopback_port(),
    )

    timeout = server.config.timeout_graceful_shutdown
    assert timeout is not None
    assert 0 < timeout <= 2.0


def test_entrypoint_keeps_reload_under_uvicorn_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    port = _free_loopback_port()
    args = argparse.Namespace(
        host="127.0.0.1",
        port=port,
        open_browser=False,
        no_browser=True,
        reload=True,
    )
    monkeypatch.setattr(workbench_entrypoint, "parse_args", lambda: args)
    monkeypatch.setattr(workbench_entrypoint, "enable_user_env_fallback_for_workbench", lambda: None)
    monkeypatch.setattr(workbench_entrypoint, "install_access_log_filters", lambda: None)
    monkeypatch.setattr(workbench_entrypoint, "bootstrap_runtime_scene_for_workbench", lambda: False)
    monkeypatch.setattr(
        workbench_entrypoint.uvicorn,
        "run",
        lambda *call_args, **kwargs: calls.append((call_args, kwargs)),
    )
    monkeypatch.setattr(
        workbench_entrypoint,
        "create_workbench_server",
        lambda *_args, **_kwargs: pytest.fail("reload must stay on uvicorn's supervisor"),
    )

    workbench_entrypoint.main()

    assert calls == [(("core.web.app:app",), {"host": "127.0.0.1", "port": port, "reload": True})]


def test_entrypoint_non_reload_owns_the_product_server(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[Any] = []
    port = _free_loopback_port()
    args = argparse.Namespace(
        host="127.0.0.1",
        port=port,
        open_browser=False,
        no_browser=True,
        reload=False,
    )

    class FakeServer:
        def run(self) -> None:
            events.append("run")

    server = FakeServer()

    @contextmanager
    def own_fake_server(value: FakeServer):
        events.append(("own-enter", value is server))
        yield
        events.append(("own-exit", value is server))

    def create_server(app: object, *, host: str, port: int) -> FakeServer:
        events.append(("factory", app, host, port))
        return server

    monkeypatch.setattr(workbench_entrypoint, "parse_args", lambda: args)
    monkeypatch.setattr(workbench_entrypoint, "enable_user_env_fallback_for_workbench", lambda: None)
    monkeypatch.setattr(workbench_entrypoint, "install_access_log_filters", lambda: None)
    monkeypatch.setattr(workbench_entrypoint, "bootstrap_runtime_scene_for_workbench", lambda: False)
    monkeypatch.setattr(workbench_entrypoint, "create_workbench_server", create_server)
    monkeypatch.setattr(workbench_entrypoint, "own_server", own_fake_server)
    monkeypatch.setattr(
        workbench_entrypoint.uvicorn,
        "run",
        lambda *_args, **_kwargs: pytest.fail("non-reload must own a Uvicorn Server instance"),
    )

    workbench_entrypoint.main()

    assert events == [
        ("factory", "core.web.app:app", "127.0.0.1", port),
        ("own-enter", True),
        "run",
        ("own-exit", True),
    ]


def test_schedule_shutdown_runs_lifespan_finally_and_unregisters_server(tmp_path: Path) -> None:
    owner, port, log_path = _spawn_fixture_server(tmp_path, mode="clean")
    try:
        _wait_for_ready(owner, port, log_path)
        _wait_for_marker(owner, tmp_path, "lifespan-started", log_path)
        _request_shutdown(port)

        owner.process.wait(timeout=8.0)

        result = _wait_for_marker(owner, tmp_path, "lifespan-finally", log_path)
        unregister = _wait_for_marker(owner, tmp_path, "own-server-exited", log_path)
        assert owner.process.returncode == 0
        assert result["closed"] is True
        assert unregister["activeServerRegistered"] is False
        assert not (tmp_path / "watchdog-fired").exists()
    finally:
        _cleanup_owned_process(owner)


@pytest.mark.parametrize(
    ("route", "started_marker", "finally_marker"),
    [
        ("/hold", "http-request-started", "http-handler-finally"),
        ("/events", "sse-request-started", "sse-generator-finally"),
    ],
)
def test_finite_connection_drain_runs_http_and_sse_finally(
    tmp_path: Path,
    route: str,
    started_marker: str,
    finally_marker: str,
) -> None:
    owner, port, log_path = _spawn_fixture_server(tmp_path, mode="clean")
    request_done = threading.Event()
    request_connected = threading.Event()
    request_errors: list[BaseException] = []

    def hold_request() -> None:
        try:
            if route == "/events":
                with httpx.stream(
                    "GET",
                    f"http://127.0.0.1:{port}{route}",
                    timeout=8.0,
                    trust_env=False,
                ) as response:
                    response.raise_for_status()
                    iterator = response.iter_raw()
                    next(iterator)
                    request_connected.set()
                    for _chunk in iterator:
                        pass
            else:
                httpx.get(
                    f"http://127.0.0.1:{port}{route}",
                    timeout=8.0,
                    trust_env=False,
                )
        except Exception as exc:  # request is expected to end with server shutdown
            request_errors.append(exc)
        finally:
            request_done.set()

    request_thread = threading.Thread(target=hold_request, name="fixture-open-http-request", daemon=True)
    try:
        _wait_for_ready(owner, port, log_path)
        request_thread.start()
        _wait_for_marker(owner, tmp_path, started_marker, log_path)
        if route == "/events":
            assert request_connected.wait(timeout=3.0), "SSE client did not receive the first event"

        _request_shutdown(port)
        owner.process.wait(timeout=8.0)

        result = _wait_for_marker(owner, tmp_path, "lifespan-finally", log_path)
        _wait_for_marker(owner, tmp_path, finally_marker, log_path)
        assert owner.process.returncode == 0
        assert result["closed"] is True
        assert not (tmp_path / "watchdog-fired").exists()
        assert request_done.wait(timeout=3.0), f"client request did not drain: {request_errors}"
    finally:
        _cleanup_owned_process(owner)
        if request_thread.is_alive():
            request_thread.join(timeout=3.0)


@pytest.mark.skipif(os.name != "nt", reason="Windows owned-process shutdown acceptance")
def test_watchdog_forces_exit_after_lifespan_leaves_startup_worker_open(tmp_path: Path) -> None:
    owner, port, log_path = _spawn_fixture_server(
        tmp_path,
        mode="stuck-worker",
        watchdog_timeout=0.7,
    )
    try:
        _wait_for_ready(owner, port, log_path)
        _wait_for_marker(owner, tmp_path, "worker-started", log_path)
        _request_shutdown(port)

        owner.process.wait(timeout=5.0)

        result = _wait_for_marker(owner, tmp_path, "lifespan-finally", log_path)
        unregister = _wait_for_marker(owner, tmp_path, "own-server-exited", log_path)
        watchdog = _wait_for_marker(owner, tmp_path, "watchdog-fired", log_path)
        assert owner.process.returncode == 0
        assert result["closed"] is False
        assert "fixture-stuck-worker" in result["pendingWorkers"]
        assert unregister["activeServerRegistered"] is False
        assert watchdog["activeServerRegistered"] is False
        assert watchdog["serverShouldExit"] is True
    finally:
        _cleanup_owned_process(owner)
