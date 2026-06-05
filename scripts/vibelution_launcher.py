#!/usr/bin/env python3
"""Cross-platform headless launcher adapter for the Vibelution workbench."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / ".runtime" / "launcher"
STATE_PATH = RUNTIME_DIR / "state.json"
BACKEND_STDOUT_PATH = RUNTIME_DIR / "backend.stdout.log"
BACKEND_STDERR_PATH = RUNTIME_DIR / "backend.stderr.log"
DEFAULT_HOST = "127.0.0.1"
TRUSTED_WEB_HOSTS_ENV = "VIBELUTION_TRUSTED_WEB_HOSTS"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_action(action: str) -> str:
    value = str(action or "start").strip().lower()
    aliases = {
        "internal-start": "start",
        "internal-stop": "stop",
        "internal-restart": "restart",
        "open": "start",
        "close": "stop",
    }
    return aliases.get(value, value)


def _read_state() -> dict:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STATE_PATH)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _health_url(port: int, host: str = DEFAULT_HOST) -> str:
    return f"http://{host}:{int(port)}/api/health"


def _backend_healthy(port: int, host: str = DEFAULT_HOST) -> bool:
    try:
        with urllib.request.urlopen(_health_url(port, host), timeout=1.5) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _wait_for_health(port: int, host: str, timeout_seconds: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _backend_healthy(port, host):
            return True
        time.sleep(0.35)
    return False


def _run_checked(args: list[str], *, cwd: Path, label: str) -> None:
    result = subprocess.run(args, cwd=str(cwd), check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}.")


def _host_is_wildcard(host: str) -> bool:
    return str(host or "").strip() in {"0.0.0.0", "::"}


def _local_lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            address = str(info[4][0] or "").strip()
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = str(probe.getsockname()[0] or "").strip()
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def _backend_environment(host: str) -> dict[str, str]:
    env = os.environ.copy()
    if _host_is_wildcard(host):
        existing = [item.strip() for item in env.get(TRUSTED_WEB_HOSTS_ENV, "").replace(";", ",").split(",") if item.strip()]
        merged = sorted({*existing, *_local_lan_addresses()})
        if merged:
            env[TRUSTED_WEB_HOSTS_ENV] = ",".join(merged)
    return env


def _ensure_frontend_build() -> None:
    web_dir = PROJECT_ROOT / "web"
    if not web_dir.exists():
        return
    node_modules = web_dir / "node_modules"
    if not node_modules.exists():
        _run_checked(["npm", "install"], cwd=web_dir, label="npm install")
    dist_index = web_dir / "dist" / "index.html"
    if not dist_index.exists():
        _run_checked(["npm", "run", "build"], cwd=web_dir, label="npm run build")


def _start_backend(port: int, host: str, *, no_browser: bool) -> dict:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_frontend_build()
    stdout = BACKEND_STDOUT_PATH.open("ab")
    stderr = BACKEND_STDERR_PATH.open("ab")
    args = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "web_workbench.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--managed-by-launcher",
    ]
    if no_browser:
        args.append("--no-browser")
    else:
        args.append("--open-browser")
    process = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        env=_backend_environment(host),
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    stdout.close()
    stderr.close()
    if not _wait_for_health(port, host):
        _terminate_pid(process.pid)
        raise RuntimeError(f"Backend did not become healthy at {_health_url(port, host)}.")
    state = {
        "schemaVersion": 1,
        "launcherAdapter": "python_headless",
        "desiredState": "open",
        "observedState": "open",
        "phase": "steady",
        "sessionRole": "workbench",
        "backendPid": int(process.pid),
        "backendLaunchPid": int(process.pid),
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "browserManaged": False,
        "url": f"http://{host}:{int(port)}",
        "backendPort": int(port),
        "statusLine": "Workbench is running.",
        "failureMessage": "",
        "lastReason": "python_launcher_start",
        "lastSource": "python_launcher",
        "updatedAt": _now_iso(),
    }
    _write_state(state)
    return state


def _terminate_pid(pid: int) -> None:
    if pid <= 0 or not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _stop_backend() -> dict:
    state = _read_state()
    pid = int(state.get("backendPid") or 0)
    _terminate_pid(pid)
    next_state = {
        **state,
        "desiredState": "closed",
        "observedState": "closed",
        "phase": "steady",
        "backendPid": 0,
        "backendLaunchPid": 0,
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "browserManaged": False,
        "statusLine": "Workbench is closed.",
        "failureMessage": "",
        "lastReason": "python_launcher_stop",
        "lastSource": "python_launcher",
        "updatedAt": _now_iso(),
    }
    _write_state(next_state)
    return next_state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vibelution cross-platform launcher adapter")
    parser.add_argument("-Action", "--action", default="start")
    parser.add_argument("-NoBrowser", "--no-browser", action="store_true")
    parser.add_argument("--host", default=os.environ.get("VIBELUTION_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VIBELUTION_PORT", "8000")))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    action = _normalize_action(args.action)
    try:
        if action == "start":
            current = _read_state()
            current_pid = int(current.get("backendPid") or 0)
            if current_pid > 0 and _pid_alive(current_pid) and _backend_healthy(args.port, args.host):
                print("Workbench already running.")
                return 0
            _start_backend(args.port, args.host, no_browser=bool(args.no_browser))
            print("Workbench started.")
            return 0
        if action == "stop":
            _stop_backend()
            print("Workbench stopped.")
            return 0
        if action == "restart":
            _stop_backend()
            _start_backend(args.port, args.host, no_browser=bool(args.no_browser))
            print("Workbench restarted.")
            return 0
        raise RuntimeError(f"Unsupported launcher action: {args.action}")
    except Exception as exc:
        state = _read_state()
        _write_state(
            {
                **state,
                "phase": "failed",
                "failureMessage": f"{type(exc).__name__}: {exc}",
                "lastSource": "python_launcher",
                "updatedAt": _now_iso(),
            }
        )
        print(f"Launcher failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
