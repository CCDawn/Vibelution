"""Transport tests use a private fake MCP server; no desktop actions occur."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import psutil
import pytest

from core.infrastructure import cua_driver_client as transport


SERVER = r'''
import json, os, subprocess, sys, time
from pathlib import Path
mode, trace = sys.argv[1:]
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    message = json.loads(line)
    with open(trace, "a", encoding="utf8") as stream:
        stream.write(json.dumps(message) + "\n")
    if message["method"] == "initialize":
        version = "wrong" if mode == "wrong-version" else "0.36.0"
        name = "wrong" if mode == "wrong-name" else "cua-driver"
        send({"jsonrpc":"2.0", "id":message["id"], "result":{
            "protocolVersion":"2024-11-05", "capabilities":{},
            "serverInfo":{"name":name, "version":version}}})
    elif message["method"] == "notifications/initialized" and mode == "no-read":
        Path(trace + ".waiting").touch()
        time.sleep(120)
    elif message["method"] == "tools/call":
        if mode in ("hang", "child"):
            if mode == "child":
                child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                Path(trace + ".child").write_text(str(child.pid))
            Path(trace + ".waiting").touch()
            time.sleep(120)
        elif mode == "oversize":
            print("x" * (8 * 1024 * 1024 + 1), flush=True)
        elif mode == "malformed":
            print("not JSON PRIVATE_SCREENSHOT", flush=True)
        elif mode == "rpc-error":
            send({"jsonrpc":"2.0", "id":message["id"],
                  "error":{"code":-32000, "message":"PRIVATE_SCREENSHOT"}})
        else:
            sys.stderr.write("s" * 100000)
            sys.stderr.flush()
            send({"jsonrpc":"2.0", "method":"notifications/message", "params":{}})
            send({"jsonrpc":"2.0", "id":message["id"] - 1,
                  "result":{"wrong":True}})
            send({"jsonrpc":"2.0", "id":message["id"],
                  "result":{"content":[{"type":"text", "text":"ok"}]}})
'''


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    script = tmp_path / "fake_mcp.py"
    script.write_text(SERVER, encoding="utf8")
    trace = tmp_path / "trace.jsonl"
    owners = []
    commands = []
    spawn = transport.OwnedProcess.spawn

    def factory(mode="normal", *, timeout=2):
        def replacement(args, **kwargs):
            commands.append((args, kwargs))
            owner = spawn([sys.executable, str(script), mode, str(trace)], **kwargs)
            owners.append(owner)
            return owner
        monkeypatch.setattr(transport.OwnedProcess, "spawn", replacement)
        return transport.CuaDriverClient(Path("private-driver.exe"), timeout_seconds=timeout)

    yield factory, trace, owners, commands
    for owner in owners:
        owner.close()


def until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate()


def test_lazy_handshake_matching_ids_and_hidden_owned_spawn(fake_server, monkeypatch):
    monkeypatch.setenv("CUA_DRIVER_RS_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("DO_NOT_TRACK", "0")
    factory, trace, owners, commands = fake_server
    client = factory()
    assert not owners
    try:
        assert client.call("screenshot", {}) == {"content": [{"type": "text", "text": "ok"}]}
        assert client.call("click", {"x": 4})["content"][0]["text"] == "ok"
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        assert [row["method"] for row in rows] == [
            "initialize", "notifications/initialized", "tools/call", "tools/call"]
        assert [row["id"] for row in rows if "id" in row] == [1, 2, 3]
        assert rows[2]["params"] == {"name": "screenshot", "arguments": {}}
        assert commands[0][0] == ["private-driver.exe", "mcp", "--direct", "--no-overlay"]
        assert commands[0][1].get("shell", False) is False
        assert commands[0][1]["stdin"] == subprocess.PIPE
        assert commands[0][1]["env"]["DO_NOT_TRACK"] == "1"
        assert commands[0][1]["env"]["CUA_DRIVER_RS_TELEMETRY_ENABLED"] == "false"
        assert os.environ["CUA_DRIVER_RS_TELEMETRY_ENABLED"] == "true"
        assert os.environ["DO_NOT_TRACK"] == "0"
        if os.name == "nt":
            assert commands[0][1]["creationflags"] & subprocess.CREATE_NO_WINDOW
    finally:
        client.close()
        client.close()
    assert owners[0].process.poll() is not None
    with pytest.raises(transport.CuaDriverClosedError):
        client.call("click", {})


@pytest.mark.parametrize("mode", ["wrong-version", "wrong-name"])
def test_refuses_unverified_driver(fake_server, mode):
    factory, trace, owners, _ = fake_server
    client = factory(mode)
    with pytest.raises(transport.CuaDriverError, match="identity"):
        client.call("click", {})
    assert owners[0].process.poll() is not None
    assert "tools/call" not in trace.read_text()


@pytest.mark.parametrize("cancel", [False, True])
def test_deadline_or_cancel_closes_admission_and_reaps_tree(fake_server, cancel):
    factory, trace, owners, _ = fake_server
    client = factory("child", timeout=2 if cancel else .3)
    started = time.monotonic()
    checker = (lambda: "stopped" if Path(str(trace) + ".waiting").exists() else "") if cancel else None
    expected = transport.CuaDriverCancelledError if cancel else transport.CuaDriverTimeoutError
    with pytest.raises(expected):
        client.call("click", {}, cancel_checker=checker)
    assert time.monotonic() - started < 2
    assert owners[0].process.poll() is not None
    marker = Path(str(trace) + ".child")
    assert marker.exists()
    until(lambda: not psutil.pid_exists(int(marker.read_text())))
    with pytest.raises(transport.CuaDriverClosedError):
        client.call("click", {})


def test_close_does_not_wait_for_inflight_call_lock(fake_server):
    factory, trace, owners, _ = fake_server
    client = factory("hang", timeout=20)
    failures = []
    def run():
        try:
            client.call("click", {})
        except Exception as error:
            failures.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        until(lambda: Path(str(trace) + ".waiting").exists())
        with pytest.raises(transport.CuaDriverBusyError):
            client.call("click", {})
        started = time.monotonic()
        client.close()
        thread.join(1)
        assert time.monotonic() - started < 1
        assert not thread.is_alive()
        assert isinstance(failures[0], transport.CuaDriverClosedError)
        assert owners[0].process.poll() is not None
    finally:
        client.close()
        thread.join(3)


def test_cancel_during_blocked_input_pipe(fake_server, monkeypatch):
    factory, trace, owners, _ = fake_server
    client = factory("no-read", timeout=3)
    marker = Path(str(trace) + ".waiting")
    writing = threading.Event()
    written = threading.Event()
    done = threading.Event()
    watchdog_fired = threading.Event()
    caller = threading.current_thread()
    cycles = []

    class ObservedInput:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, payload):
            if len(payload) <= 65536:
                return self.stream.write(payload)
            writing.set()
            try:
                return self.stream.write(payload)
            finally:
                written.set()

    class ObservedEvent(threading.Event):
        def wait(self, timeout=None):
            result = super().wait(timeout)
            if (threading.current_thread() is caller and not result
                    and writing.is_set() and not written.is_set() and marker.exists()):
                # Observe the real wait budget, excluding OS scheduling delay.
                assert timeout is not None and 0 < timeout <= .05
                cycles.append("wait")
            return result

    monkeypatch.setattr(transport, "threading", SimpleNamespace(
        **{**vars(threading), "Event": ObservedEvent}
    ))
    start = client._start

    def observed_start():
        start()
        owners[0].process.stdin = ObservedInput(owners[0].process.stdin)

    monkeypatch.setattr(client, "_start", observed_start)

    def checker():
        if cycles and cycles[-1] == "wait":
            assert marker.exists() and writing.is_set() and not written.is_set()
            cycles.append("check")
        return "stop" if len(cycles) >= 6 else ""

    def watchdog():
        if not done.wait(10):
            watchdog_fired.set()
            client.close()

    guard = threading.Thread(target=watchdog, daemon=True)
    guard.start()
    try:
        with pytest.raises(transport.CuaDriverCancelledError):
            client.call("type", {"text": "x" * 1_000_000}, cancel_checker=checker)
        assert cycles == ["wait", "check"] * 3
        assert not watchdog_fired.is_set()
        assert owners[0].process.poll() is not None
        assert owners[0].process.stdin.closed
    finally:
        done.set()
        client.close()
        guard.join(1)


@pytest.mark.parametrize("retirement_fails", [False, True])
def test_close_while_spawn_is_still_returning(fake_server, monkeypatch, retirement_fails):
    factory, _, owners, _ = fake_server
    client = factory()
    spawn = transport.OwnedProcess.spawn
    starting = threading.Event()
    release = threading.Event()
    allow_retirement = threading.Event()
    retirement_attempts = []
    failures = []
    def delayed_spawn(*args, **kwargs):
        owner = spawn(*args, **kwargs)
        original_close = owner.close
        def close(**kwargs):
            retirement_attempts.append(True)
            if retirement_fails and not allow_retirement.is_set():
                raise RuntimeError("synthetic retirement failure")
            return original_close(**kwargs)
        monkeypatch.setattr(owner, "close", close)
        starting.set()
        assert release.wait(2)
        return owner
    monkeypatch.setattr(transport.OwnedProcess, "spawn", delayed_spawn)
    def run():
        try:
            client.call("click", {})
        except Exception as error:
            failures.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert starting.wait(2)
        client.close()
        release.set()
        thread.join(2)
        assert not thread.is_alive()
        if retirement_fails:
            assert isinstance(failures[0], RuntimeError)
            assert "synthetic retirement failure" in str(failures[0])
            assert client._owner is owners[0]
            assert len(retirement_attempts) == 1
            assert owners[0].process.poll() is None
            with pytest.raises(RuntimeError, match="synthetic retirement failure"):
                client.close()
            assert len(retirement_attempts) == 2
            assert client._owner is owners[0]
            with pytest.raises(transport.CuaDriverClosedError):
                client.call("click", {})
            allow_retirement.set()
            client.close()
            assert len(retirement_attempts) == 3
        else:
            assert isinstance(failures[0], transport.CuaDriverClosedError)
        assert client._owner is None
        assert owners[0].process.poll() is not None
        assert all(pipe.closed for pipe in (owners[0].process.stdin, owners[0].process.stdout, owners[0].process.stderr))
    finally:
        allow_retirement.set()
        release.set()
        client.close()
        thread.join(3)


def test_cancel_before_start_and_close_before_start_never_spawn(fake_server):
    factory, _, owners, _ = fake_server
    client = factory()
    with pytest.raises(transport.CuaDriverCancelledError):
        client.call("click", {}, cancel_checker=lambda: "stop")
    assert not owners
    client = factory()
    client.close()
    with pytest.raises(transport.CuaDriverClosedError):
        client.call("click", {})
    assert not owners


@pytest.mark.parametrize("mode", ["oversize", "malformed", "rpc-error"])
def test_bounded_failures_do_not_expose_payload(fake_server, mode, caplog):
    factory, _, owners, _ = fake_server
    client = factory(mode)
    try:
        with pytest.raises(transport.CuaDriverError) as failure:
            client.call("screenshot", {})
        assert "PRIVATE_SCREENSHOT" not in str(failure.value) + caplog.text
        assert len(str(failure.value)) < 200
    finally:
        client.close()
    assert owners[0].process.poll() is not None
