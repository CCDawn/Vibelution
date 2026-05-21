"""Process inventory helpers for repo-owned runtime processes."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .constants import PROJECT_ROOT

try:
    import psutil
except Exception:  # pragma: no cover - dependency fallback for degraded installs
    psutil = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RuntimeProcess:
    pid: int
    parent_pid: int
    kind: str
    name: str
    command_line: str
    cwd: str
    port: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "parentPid": self.parent_pid,
            "kind": self.kind,
            "name": self.name,
            "commandLine": self.command_line,
            "cwd": self.cwd,
            "port": self.port,
        }


def list_repo_runtime_processes(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
) -> list[RuntimeProcess]:
    """Return Vibelution runtime processes that belong to this repo."""

    if psutil is None:
        return []

    root = _resolve_project_root(project_root)
    excluded = {int(pid) for pid in (exclude_pids or []) if int(pid) > 0}
    processes: list[RuntimeProcess] = []

    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "cwd"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        pid = int(info.get("pid") or 0)
        if pid <= 0 or pid in excluded:
            continue
        command_line = _command_line_text(info.get("cmdline"))
        cwd = str(info.get("cwd") or "")
        kind = _classify_repo_runtime_process(command_line=command_line, cwd=cwd, project_root=root)
        if not kind:
            continue
        processes.append(
            RuntimeProcess(
                pid=pid,
                parent_pid=int(info.get("ppid") or 0),
                kind=kind,
                name=str(info.get("name") or ""),
                command_line=command_line,
                cwd=cwd,
                port=_extract_port_from_command_line(command_line),
            )
        )

    return sorted(processes, key=lambda item: (item.kind, item.pid))


def list_unmanaged_workbench_processes(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
) -> list[RuntimeProcess]:
    return [
        item
        for item in list_repo_runtime_processes(project_root=project_root, exclude_pids=exclude_pids)
        if item.kind == "unmanaged_workbench"
    ]


def residual_process_payload(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
) -> dict[str, Any]:
    items = list_unmanaged_workbench_processes(project_root=project_root, exclude_pids=exclude_pids)
    return {
        "count": len(items),
        "items": [item.to_dict() for item in items],
    }


def terminate_unmanaged_workbench_processes(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Terminate repo-local workbench processes that are not the active managed backend."""

    if psutil is None:
        return {
            "supported": False,
            "requested": [],
            "terminated": [],
            "remaining": [],
        }

    excluded = {int(pid) for pid in (exclude_pids or []) if int(pid) > 0}
    candidates = list_unmanaged_workbench_processes(project_root=project_root, exclude_pids=excluded)
    target_pids = _target_process_tree_pids(candidates, excluded=excluded)
    if not target_pids:
        return {
            "supported": True,
            "requested": [],
            "terminated": [],
            "remaining": [],
        }

    target_processes = _live_processes(target_pids)
    for proc in sorted(target_processes, key=lambda item: _process_depth(item), reverse=True):
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    gone, alive = psutil.wait_procs(target_processes, timeout=max(0.1, float(timeout_seconds)))
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=1.0)

    time.sleep(0.05)
    remaining = list_unmanaged_workbench_processes(project_root=project_root, exclude_pids=excluded)
    remaining_pids = {item.pid for item in remaining}
    return {
        "supported": True,
        "requested": sorted(target_pids),
        "terminated": sorted(pid for pid in target_pids if pid not in remaining_pids),
        "remaining": [item.to_dict() for item in remaining],
    }


def terminate_process_descendants(
    root_pid: int,
    *,
    exclude_pids: Iterable[int] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Terminate descendants of one process without touching the root process."""

    if psutil is None:
        return {
            "supported": False,
            "rootPid": int(root_pid or 0),
            "requested": [],
            "terminated": [],
            "remaining": [],
        }

    normalized_root_pid = int(root_pid or 0)
    excluded = {normalized_root_pid}
    excluded.update(int(pid) for pid in (exclude_pids or []) if int(pid) > 0)
    if normalized_root_pid <= 0:
        return {
            "supported": True,
            "rootPid": normalized_root_pid,
            "requested": [],
            "terminated": [],
            "remaining": [],
        }

    try:
        root = psutil.Process(normalized_root_pid)
        descendants = [proc for proc in root.children(recursive=True) if int(proc.pid) not in excluded]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = []

    target_pids = {int(proc.pid) for proc in descendants}
    if not target_pids:
        return {
            "supported": True,
            "rootPid": normalized_root_pid,
            "requested": [],
            "terminated": [],
            "remaining": [],
        }

    for proc in sorted(descendants, key=lambda item: _process_depth(item), reverse=True):
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _, alive = psutil.wait_procs(descendants, timeout=max(0.1, float(timeout_seconds)))
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=1.0)

    remaining: list[dict[str, Any]] = []
    for pid in sorted(target_pids):
        try:
            proc = psutil.Process(pid)
            if proc.is_running():
                remaining.append(
                    {
                        "pid": int(proc.pid),
                        "parentPid": int(proc.ppid()),
                        "name": str(proc.name() or ""),
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    remaining_pids = {int(item["pid"]) for item in remaining}
    return {
        "supported": True,
        "rootPid": normalized_root_pid,
        "requested": sorted(target_pids),
        "terminated": sorted(pid for pid in target_pids if pid not in remaining_pids),
        "remaining": remaining,
    }


def _resolve_project_root(value: Path | str) -> Path:
    try:
        return Path(value).resolve()
    except OSError:
        return Path(value).absolute()


def _command_line_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value if str(item))
    return str(value or "")


def _classify_repo_runtime_process(*, command_line: str, cwd: str, project_root: Path) -> str:
    if not _is_project_owned(command_line=command_line, cwd=cwd, project_root=project_root):
        return ""
    normalized = command_line.replace("\\", "/").lower()
    if "scripts/web_workbench.py" in normalized:
        return "unmanaged_workbench"
    if "core.runtime_manager.cli" in normalized and _has_token(normalized, "daemon"):
        return "runtime_manager_daemon"
    return ""


def _is_project_owned(*, command_line: str, cwd: str, project_root: Path) -> bool:
    if cwd:
        try:
            Path(cwd).resolve().relative_to(project_root)
            return True
        except (OSError, ValueError):
            pass

    root_text = os.path.normcase(str(project_root)).replace("\\", "/").rstrip("/")
    command_text = os.path.normcase(command_line).replace("\\", "/")
    return _contains_path_segment(command_text, root_text)


def _contains_path_segment(text: str, path_text: str) -> bool:
    if not text or not path_text:
        return False
    start = 0
    path_length = len(path_text)
    while True:
        index = text.find(path_text, start)
        if index < 0:
            return False
        before = text[index - 1] if index > 0 else ""
        after_index = index + path_length
        after = text[after_index] if after_index < len(text) else ""
        before_ok = not before or before.isspace() or before in {'"', "'", "=", ":"}
        after_ok = not after or after.isspace() or after in {"/", '"', "'"}
        if before_ok and after_ok:
            return True
        start = index + 1


def _has_token(text: str, token: str) -> bool:
    return any(part == token for part in text.replace("\\", "/").split())


def _extract_port_from_command_line(command_line: str) -> int:
    parts = command_line.split()
    for index, part in enumerate(parts):
        if part == "--port" and index + 1 < len(parts):
            try:
                port = int(parts[index + 1])
            except ValueError:
                return 0
            return port if 0 < port < 65536 else 0
    return 0


def _target_process_tree_pids(candidates: list[RuntimeProcess], *, excluded: set[int]) -> set[int]:
    target_pids = {item.pid for item in candidates if item.pid not in excluded}
    for pid in list(target_pids):
        try:
            proc = psutil.Process(pid)
            descendants = proc.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for child in descendants:
            if child.pid not in excluded:
                target_pids.add(int(child.pid))
    return target_pids


def _live_processes(pids: Iterable[int]) -> list[Any]:
    processes = []
    for pid in sorted({int(item) for item in pids if int(item) > 0}):
        try:
            processes.append(psutil.Process(pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def _process_depth(proc: Any) -> int:
    depth = 0
    current = proc
    while depth < 64:
        try:
            current = current.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        if current is None:
            break
        depth += 1
    return depth
