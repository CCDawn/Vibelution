#!/usr/bin/env python3
"""Run Vibelution acceptance instances without sharing Launcher or operator state."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
MODE = "isolated-fixture"
BACKEND_PORTS = range(8100, 8200)
FRONTEND_PORTS = range(5200, 5300)
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SENTINEL_NAME = ".vibelution-acceptance-runtime"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _runtime_home(value: Path | str | None) -> Path:
    if value:
        return _resolved(value)
    return _resolved(Path(tempfile.gettempdir()) / "Vibelution" / "acceptance-runtimes")


def _formal_data_root() -> Path:
    return _resolved(Path.home() / "Documents" / "Vibelution")


def _assert_not_formal_path(path: Path) -> None:
    formal_root = _formal_data_root()
    if _is_relative_to(path, formal_root) or _is_relative_to(formal_root, path):
        raise ValueError(f"Acceptance runtime path must not overlap formal Vibelution data: {path}")


def _validate_instance_id(instance_id: str) -> str:
    normalized = str(instance_id or "").strip()
    if not INSTANCE_ID_RE.fullmatch(normalized):
        raise ValueError(
            "instance-id must start with an ASCII letter or digit and contain only "
            "letters, digits, dot, underscore, or dash (max 64 characters)"
        )
    return normalized


def _validate_project_root(project_root: Path | str) -> Path:
    project = _resolved(project_root)
    if not project.is_dir():
        raise ValueError(f"Project root does not exist: {project}")
    if not (project / ".git").exists():
        raise ValueError(f"Project root is not a Git checkout/worktree: {project}")
    if not (project / "scripts" / "web_workbench.py").is_file():
        raise ValueError(f"Project root is missing scripts/web_workbench.py: {project}")
    if not (project / "web" / "package.json").is_file():
        raise ValueError(f"Project root is missing web/package.json: {project}")
    return project


def _instance_paths(
    *,
    instance_id: str,
    runtime_home: Path | str | None,
) -> dict[str, Path]:
    safe_id = _validate_instance_id(instance_id)
    home = _runtime_home(runtime_home)
    _assert_not_formal_path(home)
    instance = (home / safe_id).resolve()
    if not _is_relative_to(instance, home):
        raise ValueError(f"Instance path escapes runtime home: {instance}")
    for child_name in ("data", "config", "logs"):
        child = instance / child_name
        if child.exists() and not _is_relative_to(child.resolve(), instance):
            raise ValueError(f"Instance {child_name} path escapes instance root: {child}")
    return {
        "runtimeHome": home,
        "instanceRoot": instance,
        "dataRoot": instance / "data",
        "configRoot": instance / "config",
        "logsRoot": instance / "logs",
        "statePath": instance / "state.json",
        "sentinelPath": instance / SENTINEL_NAME,
        "leaseRoot": home / ".leases",
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _process_create_time(pid: int) -> float | None:
    try:
        import psutil

        return float(psutil.Process(int(pid)).create_time())
    except Exception:
        return None


def _process_matches(pid: int, expected_create_time: float | int | None) -> bool:
    if int(pid or 0) <= 0:
        return False
    try:
        import psutil

        process = psutil.Process(int(pid))
        if not process.is_running():
            return False
        if expected_create_time is None:
            return True
        return abs(float(process.create_time()) - float(expected_create_time)) < 0.01
    except Exception:
        return False


def _port_available(port: int, host: str = "127.0.0.1") -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    except (AttributeError, OSError):
        pass
    try:
        probe.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _lease_path(lease_root: Path, kind: str, port: int) -> Path:
    return lease_root / f"{kind}-{int(port)}.json"


def _lease_is_stale(path: Path, payload: dict[str, Any]) -> bool:
    if _process_matches(
        int(payload.get("ownerPid") or 0),
        payload.get("ownerCreateTime"),
    ):
        return False
    return _port_available(int(payload.get("port") or 0))


def _allocate_port(
    *,
    lease_root: Path,
    kind: str,
    instance_id: str,
    candidates: Iterable[int],
) -> int:
    lease_root.mkdir(parents=True, exist_ok=True)
    owner_pid = os.getpid()
    owner_create_time = _process_create_time(owner_pid)
    for candidate in candidates:
        port = int(candidate)
        if not _port_available(port):
            continue
        lease_path = _lease_path(lease_root, kind, port)
        for _attempt in range(2):
            payload = {
                "schemaVersion": SCHEMA_VERSION,
                "kind": kind,
                "port": port,
                "instanceId": instance_id,
                "ownerPid": owner_pid,
                "ownerCreateTime": owner_create_time,
                "updatedAt": _now_iso(),
            }
            try:
                descriptor = os.open(
                    lease_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                )
            except FileExistsError:
                existing = _read_json(lease_path)
                if existing and _lease_is_stale(lease_path, existing):
                    try:
                        lease_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                break
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            return port
    raise RuntimeError(f"No free {kind} acceptance port is available")


def _update_lease_owner(
    *,
    lease_root: Path,
    kind: str,
    port: int,
    instance_id: str,
    pid: int,
    create_time: float | None,
) -> None:
    path = _lease_path(lease_root, kind, port)
    payload = _read_json(path)
    if payload.get("instanceId") != instance_id:
        raise RuntimeError(f"Lost {kind} port lease for {instance_id}")
    payload.update(
        {
            "ownerPid": int(pid),
            "ownerCreateTime": create_time,
            "updatedAt": _now_iso(),
        }
    )
    _write_json_atomic(path, payload)


def _release_lease(lease_root: Path, kind: str, port: int, instance_id: str) -> None:
    path = _lease_path(lease_root, kind, port)
    payload = _read_json(path)
    if payload.get("instanceId") != instance_id:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _release_ports(paths: dict[str, Path], state: dict[str, Any], instance_id: str) -> None:
    ports = state.get("ports") if isinstance(state.get("ports"), dict) else {}
    for kind in ("backend", "frontend"):
        port = int(ports.get(kind) or 0)
        if port > 0:
            _release_lease(paths["leaseRoot"], kind, port, instance_id)


def _source_commit(project_root: Path) -> str:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )
    return result.stdout.strip()


def _child_environment(
    *,
    instance_id: str,
    backend_port: int,
    frontend_port: int,
    data_root: Path,
    config_root: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("VIBELUTION_CONFIG_PATH", None)
    env.update(
        {
            "VIBELUTION_PORT": str(int(backend_port)),
            "AGENT_WORKBENCH_BACKEND_PORT": str(int(backend_port)),
            "VIBELUTION_FRONTEND_PORT": str(int(frontend_port)),
            "AGENT_WORKBENCH_FRONTEND_PORT": str(int(frontend_port)),
            "VIBELUTION_DATA_HOME": str(data_root),
            "VIBELUTION_CONFIG_HOME": str(config_root),
            "VIBELUTION_ACCEPTANCE_INSTANCE_ID": instance_id,
            "VIBELUTION_ACCEPTANCE_MODE": MODE,
            # Prevent the isolated backend from importing operator-scoped API-key files.
            "VIBELUTION_ENABLE_USER_ENV_FALLBACK": "0",
        }
    )
    return env


def _no_window_popen_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {
        "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    }
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _spawn(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.Popen[bytes]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("ab", buffering=0)
    stderr_handle = stderr_path.open("ab", buffering=0)
    try:
        return subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            **_no_window_popen_kwargs(),
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()


def _frontend_command(*, project: Path, frontend_port: int) -> list[str]:
    node = shutil.which("node.exe") or shutil.which("node")
    if not node:
        raise RuntimeError("node executable was not found")
    vite_entry = (project / "web" / "node_modules" / "vite" / "bin" / "vite.js").resolve()
    if not vite_entry.is_file():
        raise RuntimeError(f"Vite entrypoint was not found: {vite_entry}")
    return [
        node,
        str(vite_entry),
        "--host",
        "127.0.0.1",
        "--port",
        str(int(frontend_port)),
        "--strictPort",
    ]


def _http_ready(url: str, timeout: float = 0.8) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def _wait_ready(
    *,
    url: str,
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"Process exited before readiness with code {return_code}: {url}")
        if _http_ready(url):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for isolated acceptance runtime: {url}")


def _terminate_spawned(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=4.0)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=2.0)
        except Exception:
            pass


def _terminate_recorded(pid: int, create_time: float | int | None) -> bool:
    if not _process_matches(pid, create_time):
        return False
    try:
        import psutil

        process = psutil.Process(int(pid))
        children = process.children(recursive=True)
        for child in reversed(children):
            child.terminate()
        process.terminate()
        _, alive = psutil.wait_procs([*children, process], timeout=4.0)
        for remaining in alive:
            remaining.kill()
        if alive:
            psutil.wait_procs(alive, timeout=2.0)
        return True
    except Exception:
        return False


def start_instance(
    *,
    instance_id: str,
    project_root: Path | str,
    runtime_home: Path | str | None = None,
    mode: str = MODE,
    readiness_timeout: float = 45.0,
) -> dict[str, Any]:
    if str(mode or "").strip() != MODE:
        raise ValueError(
            "Only isolated-fixture may start here. formal-live is a singleton Launcher flow; "
            "shared-readonly must use the already running formal instance."
        )
    safe_id = _validate_instance_id(instance_id)
    project = _validate_project_root(project_root)
    paths = _instance_paths(instance_id=safe_id, runtime_home=runtime_home)
    existing_state = _read_json(paths["statePath"])
    if existing_state and status_instance(instance_id=safe_id, runtime_home=paths["runtimeHome"])[
        "status"
    ] == "running":
        raise RuntimeError(f"Acceptance instance is already running: {safe_id}")

    for key in ("instanceRoot", "dataRoot", "configRoot", "logsRoot", "leaseRoot"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        paths["sentinelPath"],
        {
            "schemaVersion": SCHEMA_VERSION,
            "instanceId": safe_id,
            "mode": MODE,
            "createdAt": _now_iso(),
        },
    )

    provisional_state: dict[str, Any] = {"ports": {}}
    backend_process: subprocess.Popen[bytes] | None = None
    frontend_process: subprocess.Popen[bytes] | None = None
    try:
        backend_port = _allocate_port(
            lease_root=paths["leaseRoot"],
            kind="backend",
            instance_id=safe_id,
            candidates=BACKEND_PORTS,
        )
        provisional_state["ports"]["backend"] = backend_port
        frontend_port = _allocate_port(
            lease_root=paths["leaseRoot"],
            kind="frontend",
            instance_id=safe_id,
            candidates=FRONTEND_PORTS,
        )
        provisional_state["ports"]["frontend"] = frontend_port
        env = _child_environment(
            instance_id=safe_id,
            backend_port=backend_port,
            frontend_port=frontend_port,
            data_root=paths["dataRoot"],
            config_root=paths["configRoot"],
        )
        backend_command = [
            sys.executable,
            str(project / "scripts" / "web_workbench.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
            "--no-browser",
        ]
        frontend_command = _frontend_command(project=project, frontend_port=frontend_port)
        backend_process = _spawn(
            backend_command,
            cwd=project,
            env=env,
            stdout_path=paths["logsRoot"] / "backend.stdout.log",
            stderr_path=paths["logsRoot"] / "backend.stderr.log",
        )
        _update_lease_owner(
            lease_root=paths["leaseRoot"],
            kind="backend",
            port=backend_port,
            instance_id=safe_id,
            pid=backend_process.pid,
            create_time=_process_create_time(backend_process.pid),
        )
        frontend_process = _spawn(
            frontend_command,
            cwd=project,
            env=env,
            stdout_path=paths["logsRoot"] / "frontend.stdout.log",
            stderr_path=paths["logsRoot"] / "frontend.stderr.log",
        )
        _update_lease_owner(
            lease_root=paths["leaseRoot"],
            kind="frontend",
            port=frontend_port,
            instance_id=safe_id,
            pid=frontend_process.pid,
            create_time=_process_create_time(frontend_process.pid),
        )
        backend_url = f"http://127.0.0.1:{backend_port}"
        frontend_url = f"http://127.0.0.1:{frontend_port}"
        _wait_ready(
            url=f"{backend_url}/api/health",
            process=backend_process,
            timeout_seconds=readiness_timeout,
        )
        _wait_ready(
            url=frontend_url,
            process=frontend_process,
            timeout_seconds=readiness_timeout,
        )
        state = {
            "schemaVersion": SCHEMA_VERSION,
            "instanceId": safe_id,
            "mode": MODE,
            "status": "running",
            "projectRoot": str(project),
            "sourceCommit": _source_commit(project),
            "ports": {"backend": backend_port, "frontend": frontend_port},
            "dataRoot": str(paths["dataRoot"]),
            "configRoot": str(paths["configRoot"]),
            "logsRoot": str(paths["logsRoot"]),
            "backendUrl": backend_url,
            "frontendUrl": frontend_url,
            "processes": {
                "backend": {
                    "pid": backend_process.pid,
                    "createTime": _process_create_time(backend_process.pid),
                },
                "frontend": {
                    "pid": frontend_process.pid,
                    "createTime": _process_create_time(frontend_process.pid),
                },
            },
            "createdAt": _now_iso(),
            "updatedAt": _now_iso(),
        }
        _write_json_atomic(paths["statePath"], state)
        return state
    except Exception as exc:
        _terminate_spawned(frontend_process)
        _terminate_spawned(backend_process)
        _release_ports(paths, provisional_state, safe_id)
        _write_json_atomic(
            paths["statePath"],
            {
                "schemaVersion": SCHEMA_VERSION,
                "instanceId": safe_id,
                "mode": MODE,
                "status": "failed",
                "projectRoot": str(project),
                "ports": {},
                "failure": str(exc)[:500],
                "updatedAt": _now_iso(),
            },
        )
        raise


def status_instance(
    *,
    instance_id: str,
    runtime_home: Path | str | None = None,
) -> dict[str, Any]:
    safe_id = _validate_instance_id(instance_id)
    paths = _instance_paths(instance_id=safe_id, runtime_home=runtime_home)
    state = _read_json(paths["statePath"])
    if not state:
        return {"instanceId": safe_id, "status": "not_found"}
    result = dict(state)
    processes = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    process_status: dict[str, bool] = {}
    for name in ("backend", "frontend"):
        identity = processes.get(name) if isinstance(processes.get(name), dict) else {}
        process_status[name] = _process_matches(
            int(identity.get("pid") or 0),
            identity.get("createTime"),
        )
    result["processAlive"] = process_status
    if state.get("status") == "running" and not all(process_status.values()):
        result["status"] = "stale"
    return result


def list_instances(*, runtime_home: Path | str | None = None) -> list[dict[str, Any]]:
    home = _runtime_home(runtime_home)
    _assert_not_formal_path(home)
    if not home.is_dir():
        return []
    instances: list[dict[str, Any]] = []
    for child in sorted(home.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            instances.append(status_instance(instance_id=child.name, runtime_home=home))
        except ValueError:
            continue
    return instances


def stop_instance(
    *,
    instance_id: str,
    runtime_home: Path | str | None = None,
) -> dict[str, Any]:
    safe_id = _validate_instance_id(instance_id)
    paths = _instance_paths(instance_id=safe_id, runtime_home=runtime_home)
    state = _read_json(paths["statePath"])
    if not state:
        return {"instanceId": safe_id, "status": "stopped", "existed": False}
    processes = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    terminated: dict[str, bool] = {}
    for name in ("frontend", "backend"):
        identity = processes.get(name) if isinstance(processes.get(name), dict) else {}
        terminated[name] = _terminate_recorded(
            int(identity.get("pid") or 0),
            identity.get("createTime"),
        )
    _release_ports(paths, state, safe_id)
    stopped = {
        **state,
        "status": "stopped",
        "terminated": terminated,
        "stoppedAt": state.get("stoppedAt") or _now_iso(),
        "updatedAt": _now_iso(),
    }
    _write_json_atomic(paths["statePath"], stopped)
    return stopped


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-home",
        default="",
        help="Acceptance broker/state root. Defaults to the system temp directory.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--instance-id", required=True)
    start.add_argument("--project", required=True)
    start.add_argument("--mode", default=MODE)
    start.add_argument("--readiness-timeout", type=float, default=45.0)
    for command in ("status", "stop"):
        action = subparsers.add_parser(command)
        action.add_argument("--instance-id", required=True)
    subparsers.add_parser("list")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    runtime_home = args.runtime_home or None
    try:
        if args.command == "start":
            payload: Any = start_instance(
                instance_id=args.instance_id,
                project_root=args.project,
                runtime_home=runtime_home,
                mode=args.mode,
                readiness_timeout=args.readiness_timeout,
            )
        elif args.command == "status":
            payload = status_instance(instance_id=args.instance_id, runtime_home=runtime_home)
        elif args.command == "stop":
            payload = stop_instance(instance_id=args.instance_id, runtime_home=runtime_home)
        else:
            payload = list_instances(runtime_home=runtime_home)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "result": payload}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
