"""Bounded JSON-lines MCP transport for the pinned, task-owned CUA driver.

The transport never retries a tool call. A deadline, cancellation or protocol
failure retires the whole owned tree and permanently closes input admission.
No driver payload (including screenshots and stderr) is logged.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Any, Callable

from scripts.windowless_subprocess import no_window_subprocess_kwargs

from .owned_process import OwnedProcess

_MAX_MESSAGE_BYTES = 8 * 1024 * 1024
_POLL_SECONDS = .05


class CuaDriverError(RuntimeError):
    """A sanitized transport or MCP failure; contains no driver payload."""


class CuaDriverClosedError(CuaDriverError):
    pass


class CuaDriverBusyError(CuaDriverError):
    pass


class CuaDriverCancelledError(CuaDriverError):
    pass


class CuaDriverTimeoutError(CuaDriverError, TimeoutError):
    pass


class CuaDriverClient:
    def __init__(self, binary_path: str | Path, *, timeout_seconds: float = 20.0) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self._binary_path = str(binary_path)
        self._timeout_seconds = timeout_seconds
        self._busy = threading.Lock()
        self._state = threading.Lock()
        self._retirement = threading.Lock()
        self._closed = threading.Event()
        self._owner: OwnedProcess | None = None
        self._threads: list[threading.Thread] = []
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._fault: str | None = None
        self._expected_id: int | None = None
        self._next_id = 0
        self._initialized = False

    def call(
        self, tool_name: str, arguments: dict, *,
        cancel_checker: Callable[[], str] | None = None,
    ) -> dict:
        if self._closed.is_set():
            raise CuaDriverClosedError("CUA MCP client is closed")
        if not self._busy.acquire(blocking=False):
            raise CuaDriverBusyError("CUA MCP client already has an active call")
        try:
            deadline = time.monotonic() + self._timeout_seconds
            self._check(deadline, cancel_checker)
            if not isinstance(tool_name, str) or not tool_name or not isinstance(arguments, dict):
                raise ValueError("A tool name and argument dictionary are required")
            if self._owner is None:
                self._start()
            if not self._initialized:
                result = self._request("initialize", {
                    "protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "vibelution-cua", "version": "1.0"},
                }, deadline, cancel_checker)
                info = result.get("serverInfo")
                if not isinstance(info, dict) or info.get("name") != "cua-driver" or info.get("version") != "0.36.0":
                    raise CuaDriverError("CUA MCP server identity does not match the pinned driver")
                self._write({"jsonrpc": "2.0", "method": "notifications/initialized"}, deadline, cancel_checker)
                self._initialized = True
            return self._request("tools/call", {"name": tool_name, "arguments": arguments}, deadline, cancel_checker)
        except BaseException:
            # No stale reply can be accepted by a later action after uncertainty.
            self.close()
            raise
        finally:
            self._busy.release()

    def _start(self) -> None:
        # Spawn outside the state lock so close can shut admission immediately.
        # Pinned upstream telemetry.rs::effective_enabled (cua-driver-rs-v0.36.0)
        # gives DO_NOT_TRACK precedence over config and inherited opt-in values.
        child_env = dict(os.environ)
        child_env.update(DO_NOT_TRACK="1", CUA_DRIVER_RS_TELEMETRY_ENABLED="false")
        owner = OwnedProcess.spawn(
            [self._binary_path, "mcp", "--direct", "--no-overlay"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, env=child_env, **no_window_subprocess_kwargs(),
        )
        with self._state:
            # Keep ownership even if close won the spawn race. The call's
            # failure path retires under _retirement; failed retirement must
            # leave this reference available for a later close() retry.
            self._owner = owner
            admitted = not self._closed.is_set()
        if not admitted:
            raise CuaDriverClosedError("CUA MCP client is closed")
        for target, stream in ((self._read_stdout, owner.process.stdout), (self._drain_stderr, owner.process.stderr)):
            thread = threading.Thread(target=target, args=(stream,), daemon=True, name="cua-mcp-reader")
            self._threads.append(thread)
            thread.start()

    def _fail(self, message: str) -> None:
        with self._state:
            if self._fault is None:
                self._fault = message

    def _read_stdout(self, stream: Any) -> None:
        try:
            while not self._closed.is_set():
                line = stream.readline(_MAX_MESSAGE_BYTES + 2)
                if not line:
                    self._fail("CUA MCP process exited before completing the request")
                    return
                if len(line.rstrip(b"\r\n")) > _MAX_MESSAGE_BYTES:
                    self._fail("CUA MCP response exceeds the 8 MiB limit")
                    return
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError, RecursionError):
                    self._fail("CUA MCP returned invalid JSON")
                    return
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    self._fail("CUA MCP returned an invalid envelope")
                    return
                # Notifications carry no receipt. Ignore unmatched/old ids.
                with self._state:
                    matches = type(message.get("id")) is int and message["id"] == self._expected_id
                if matches and "method" not in message:
                    try:
                        self._responses.put_nowait(message)
                    except queue.Full:
                        self._fail("CUA MCP returned duplicate responses")
                        return
        except (OSError, ValueError):
            self._fail("CUA MCP output pipe closed")

    def _drain_stderr(self, stream: Any) -> None:
        # Drain without retaining stderr; it may contain screenshots or secrets.
        try:
            while not self._closed.is_set() and stream.read(4096):
                pass
        except (OSError, ValueError):
            pass

    def _check(self, deadline: float, cancel_checker: Callable[[], str] | None) -> None:
        if self._closed.is_set():
            raise CuaDriverClosedError("CUA MCP client is closed")
        if cancel_checker is not None and cancel_checker():
            raise CuaDriverCancelledError("CUA MCP call was cancelled")
        if time.monotonic() >= deadline:
            raise CuaDriverTimeoutError("CUA MCP call exceeded its deadline")
        with self._state:
            fault = self._fault
        if fault is not None:
            raise CuaDriverError(fault)

    def _write(self, message: dict, deadline: float, cancel_checker: Callable[[], str] | None) -> None:
        payload = (json.dumps(message, ensure_ascii=True, allow_nan=False) + "\n").encode("utf8")
        if len(payload) > _MAX_MESSAGE_BYTES:
            raise CuaDriverError("CUA MCP request exceeds the 8 MiB limit")
        completed = threading.Event()
        failed = threading.Event()
        with self._state:
            owner = self._owner
        if owner is None:
            raise CuaDriverClosedError("CUA MCP client is closed")

        def write() -> None:
            try:
                # A full input pipe must not prevent cancellation or close.
                owner.process.stdin.write(payload)
                owner.process.stdin.flush()
            except (OSError, ValueError):
                failed.set()
            finally:
                completed.set()

        self._check(deadline, cancel_checker)
        thread = threading.Thread(target=write, daemon=True, name="cua-mcp-writer")
        thread.start()
        while not completed.wait(_POLL_SECONDS):
            self._check(deadline, cancel_checker)
        self._check(deadline, cancel_checker)
        if failed.is_set():
            raise CuaDriverError("CUA MCP input pipe closed")

    def _request(self, method: str, params: dict, deadline: float, cancel_checker: Callable[[], str] | None) -> dict:
        self._next_id += 1
        request_id = self._next_id
        with self._state:
            self._expected_id = request_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, deadline, cancel_checker)
        while True:
            self._check(deadline, cancel_checker)
            try:
                response = self._responses.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                continue
            self._check(deadline, cancel_checker)
            if response.get("id") != request_id:
                continue
            with self._state:
                self._expected_id = None
            if "error" in response:
                error = response["error"]
                code = error.get("code") if isinstance(error, dict) else None
                safe_code = str(code) if type(code) is int and -(2**31) <= code < 2**31 else "unknown"
                raise CuaDriverError(f"CUA MCP request failed (code {safe_code})")
            result = response.get("result")
            if not isinstance(result, dict):
                raise CuaDriverError("CUA MCP response has no result object")
            return result

    def close(self) -> None:
        """Close admission first, then retire only this client's owned tree."""
        self._closed.set()
        # This lock never protects call/wait. Concurrent closers share retirement.
        with self._retirement:
            with self._state:
                owner = self._owner
            if owner is None:
                return
            owner.close(timeout=2.0)
            for thread in self._threads:
                if thread is not threading.current_thread() and thread.ident is not None:
                    thread.join(timeout=.1)
            self._close_pipes(owner)
            with self._state:
                self._owner = None
                self._expected_id = None
            while not self._responses.empty():
                try:
                    self._responses.get_nowait()
                except queue.Empty:
                    break

    @staticmethod
    def _close_pipes(owner: OwnedProcess) -> None:
        for pipe in (owner.process.stdin, owner.process.stdout, owner.process.stderr):
            if pipe is not None:
                pipe.close()
