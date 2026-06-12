"""Process inventory helpers for repo-owned runtime processes."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from config.workbench import configured_backend_port

from .constants import PROJECT_ROOT

try:
    import psutil
except Exception:  # pragma: no cover - dependency fallback for degraded installs
    psutil = None  # type: ignore[assignment]


RESIDUAL_RUNTIME_KINDS = {"unmanaged_workbench", "unmanaged_frontend_dev_server"}
MANAGED_WORKBENCH_MARKER = "--managed-by-launcher"


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


@dataclass(frozen=True)
class BrowserProcessSnapshot:
    pid: int
    parent_pid: int
    name: str
    process_type: str
    subtype: str
    working_set_mb: float
    private_mb: float
    command_line_preview: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "parentPid": self.parent_pid,
            "name": self.name,
            "type": self.process_type,
            "subtype": self.subtype,
            "workingSetMB": self.working_set_mb,
            "privateMB": self.private_mb,
            "commandLinePreview": self.command_line_preview,
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
    raw_processes: list[dict[str, Any]] = []
    processes: list[RuntimeProcess] = []

    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "cwd"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        raw_processes.append(dict(info))

    excluded = _expand_excluded_process_tree(raw_processes, excluded)

    for info in raw_processes:
        pid = int(info.get("pid") or 0)
        if pid <= 0 or pid in excluded:
            continue
        command_line = _command_line_text(info.get("cmdline"))
        cwd = str(info.get("cwd") or "")
        kind = _classify_repo_runtime_process(command_line=command_line, cwd=cwd, project_root=root)
        if not kind:
            continue
        port = _extract_port_from_command_line(command_line)
        if port == 0 and kind in {"managed_workbench_backend", "unmanaged_workbench"}:
            port = configured_backend_port()
        if port == 0 and kind == "unmanaged_frontend_dev_server":
            port = 5173
        processes.append(
            RuntimeProcess(
                pid=pid,
                parent_pid=int(info.get("ppid") or 0),
                kind=kind,
                name=str(info.get("name") or ""),
                command_line=command_line,
                cwd=cwd,
                port=port,
            )
        )

    return sorted(processes, key=lambda item: (item.kind, item.pid))


def managed_browser_process_payload(
    *,
    profile_dir: Path | str,
    command_preview_chars: int = 220,
) -> dict[str, Any]:
    """Return memory grouped by Edge processes that belong to the managed app profile."""

    if psutil is None:
        return {
            "supported": False,
            "profileDir": str(profile_dir),
            "count": 0,
            "totalWorkingSetMB": 0.0,
            "totalPrivateMB": 0.0,
            "items": [],
        }

    profile_marker = _profile_marker_text(profile_dir)
    raw_processes: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "memory_info"]):
        try:
            raw_processes.append(dict(proc.info))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    children_by_parent: dict[int, list[int]] = {}
    by_pid: dict[int, dict[str, Any]] = {}
    managed_seed_pids: set[int] = set()
    for info in raw_processes:
        pid = int(info.get("pid") or 0)
        parent_pid = int(info.get("ppid") or 0)
        if pid <= 0:
            continue
        by_pid[pid] = info
        if parent_pid > 0:
            children_by_parent.setdefault(parent_pid, []).append(pid)
        command_line = _command_line_text(info.get("cmdline"))
        if _looks_like_edge_process(info) and _command_line_has_profile_marker(command_line, profile_marker):
            managed_seed_pids.add(pid)

    managed_pids = set(managed_seed_pids)
    queue = list(managed_seed_pids)
    while queue:
        parent_pid = queue.pop()
        for child_pid in children_by_parent.get(parent_pid, []):
            if child_pid in managed_pids:
                continue
            managed_pids.add(child_pid)
            queue.append(child_pid)

    items: list[BrowserProcessSnapshot] = []
    for pid in sorted(managed_pids):
        info = by_pid.get(pid)
        if not info or not _looks_like_edge_process(info):
            continue
        command_line = _command_line_text(info.get("cmdline"))
        working_set_mb, private_mb = _memory_info_mb(info.get("memory_info"))
        items.append(
            BrowserProcessSnapshot(
                pid=pid,
                parent_pid=int(info.get("ppid") or 0),
                name=str(info.get("name") or ""),
                process_type=_edge_process_type(command_line),
                subtype=_edge_process_subtype(command_line),
                working_set_mb=working_set_mb,
                private_mb=private_mb,
                command_line_preview=_truncate_text(command_line, max(40, int(command_preview_chars or 220))),
            )
        )

    return {
        "supported": True,
        "profileDir": str(profile_dir),
        "count": len(items),
        "totalWorkingSetMB": round(sum(item.working_set_mb for item in items), 1),
        "totalPrivateMB": round(sum(item.private_mb for item in items), 1),
        "items": [item.to_dict() for item in sorted(items, key=lambda item: item.private_mb, reverse=True)],
    }


def _expand_excluded_process_tree(processes: list[dict[str, Any]], excluded: set[int]) -> set[int]:
    expanded = set(excluded)
    children_by_parent: dict[int, list[int]] = {}
    for info in processes:
        pid = int(info.get("pid") or 0)
        parent_pid = int(info.get("ppid") or 0)
        if pid > 0 and parent_pid > 0:
            children_by_parent.setdefault(parent_pid, []).append(pid)

    queue = list(expanded)
    while queue:
        parent_pid = queue.pop()
        for child_pid in children_by_parent.get(parent_pid, []):
            if child_pid in expanded:
                continue
            expanded.add(child_pid)
            queue.append(child_pid)
    return expanded


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


def unmanaged_workbench_process_payload(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
) -> dict[str, Any]:
    items = list_unmanaged_workbench_processes(project_root=project_root, exclude_pids=exclude_pids)
    return {
        "count": len(items),
        "items": [item.to_dict() for item in items],
    }


def list_residual_runtime_processes(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
) -> list[RuntimeProcess]:
    return [
        item
        for item in list_repo_runtime_processes(project_root=project_root, exclude_pids=exclude_pids)
        if item.kind in RESIDUAL_RUNTIME_KINDS
    ]


def residual_process_payload(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
) -> dict[str, Any]:
    items = list_residual_runtime_processes(project_root=project_root, exclude_pids=exclude_pids)
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
    candidates = list_residual_runtime_processes(project_root=project_root, exclude_pids=excluded)
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
    remaining = list_residual_runtime_processes(project_root=project_root, exclude_pids=excluded)
    remaining_pids = {item.pid for item in remaining}
    return {
        "supported": True,
        "requested": sorted(target_pids),
        "terminated": sorted(pid for pid in target_pids if pid not in remaining_pids),
        "remaining": [item.to_dict() for item in remaining],
    }


def terminate_workbench_processes(
    *,
    project_root: Path | str = PROJECT_ROOT,
    browser_profile_dir: Path | str = "",
    exclude_pids: Iterable[int] | None = None,
    timeout_seconds: float = 5.0,
    verify_remaining_with_inventory: bool = True,
) -> dict[str, Any]:
    """Terminate repo-owned workbench backend/frontend processes and managed browser profile processes."""

    if psutil is None:
        return {
            "supported": False,
            "requested": [],
            "terminated": [],
            "remaining": [],
            "repoCandidates": [],
            "browserCandidates": [],
        }

    excluded = {int(pid) for pid in (exclude_pids or []) if int(pid) > 0}
    repo_candidates = [
        item
        for item in list_repo_runtime_processes(project_root=project_root)
        if item.kind in {"managed_workbench_backend", "unmanaged_workbench", "unmanaged_frontend_dev_server"}
        and item.pid not in excluded
    ]
    target_pids = _target_process_tree_pids(repo_candidates, excluded=excluded)

    browser_candidates: list[dict[str, Any]] = []
    profile_text = str(browser_profile_dir or "").strip()
    if profile_text:
        browser_payload = managed_browser_process_payload(profile_dir=profile_text, command_preview_chars=220)
        browser_candidates = [
            item
            for item in list(browser_payload.get("items") or [])
            if isinstance(item, dict) and int(item.get("pid") or 0) > 0
        ]
        target_pids.update(int(item.get("pid") or 0) for item in browser_candidates if int(item.get("pid") or 0) not in excluded)

    if not target_pids:
        return {
            "supported": True,
            "requested": [],
            "terminated": [],
            "remaining": [],
            "repoCandidates": [item.to_dict() for item in repo_candidates],
            "browserCandidates": browser_candidates,
        }

    target_processes = _live_processes(target_pids)
    for proc in sorted(target_processes, key=lambda item: _process_depth(item), reverse=True):
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _, alive = psutil.wait_procs(target_processes, timeout=max(0.1, float(timeout_seconds)))
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=1.0)

    time.sleep(0.05)
    remaining: list[dict[str, Any]]
    if verify_remaining_with_inventory:
        remaining_repo = [
            item
            for item in list_repo_runtime_processes(project_root=project_root)
            if item.kind in {"managed_workbench_backend", "unmanaged_workbench", "unmanaged_frontend_dev_server"}
            and item.pid not in excluded
        ]
        remaining_browser: list[dict[str, Any]] = []
        if profile_text:
            browser_payload = managed_browser_process_payload(profile_dir=profile_text, command_preview_chars=220)
            remaining_browser = [
                item
                for item in list(browser_payload.get("items") or [])
                if isinstance(item, dict) and int(item.get("pid") or 0) > 0
            ]
        remaining = [item.to_dict() for item in remaining_repo] + remaining_browser
    else:
        repo_by_pid = {item.pid: item.to_dict() for item in repo_candidates}
        browser_by_pid = {
            int(item.get("pid") or 0): item
            for item in browser_candidates
            if isinstance(item, dict) and int(item.get("pid") or 0) > 0
        }
        remaining = []
        seen_remaining: set[int] = set()
        for proc in _live_processes(target_pids):
            pid = int(getattr(proc, "pid", 0) or 0)
            if pid <= 0 or pid in seen_remaining:
                continue
            seen_remaining.add(pid)
            if pid in repo_by_pid:
                remaining.append(repo_by_pid[pid])
                continue
            if pid in browser_by_pid:
                remaining.append(browser_by_pid[pid])
                continue
            try:
                name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = ""
            remaining.append(
                {
                    "pid": pid,
                    "name": name,
                    "kind": "target_process_still_alive",
                    "source": "target_process_tree",
                }
            )
    remaining_pids = {int(item.get("pid") or 0) for item in remaining if isinstance(item, dict)}
    return {
        "supported": True,
        "requested": sorted(target_pids),
        "terminated": sorted(pid for pid in target_pids if pid not in remaining_pids),
        "remaining": remaining,
        "repoCandidates": [item.to_dict() for item in repo_candidates],
        "browserCandidates": browser_candidates,
        "browserProfileDir": profile_text,
        "remainingCheck": "inventory" if verify_remaining_with_inventory else "target_processes",
    }


def terminate_unmanaged_workbench_backends(
    *,
    project_root: Path | str = PROJECT_ROOT,
    exclude_pids: Iterable[int] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Terminate repo-local unmanaged backend workbench processes, leaving dev servers alone."""

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

    _, alive = psutil.wait_procs(target_processes, timeout=max(0.1, float(timeout_seconds)))
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
        if _has_token(normalized, MANAGED_WORKBENCH_MARKER):
            return "managed_workbench_backend"
        return "unmanaged_workbench"
    if _looks_like_frontend_dev_server(normalized):
        return "unmanaged_frontend_dev_server"
    if "core.runtime_manager.cli" in normalized and _has_token(normalized, "daemon"):
        return "runtime_manager_daemon"
    return ""


def _looks_like_frontend_dev_server(normalized_command_line: str) -> bool:
    parts = normalized_command_line.split()
    if _contains_python_inline_command(parts):
        return False
    if _looks_like_frontend_build_command(parts):
        return False
    if "http.server" in parts and "frontend" in parts:
        return True
    if any(_looks_like_vite_invocation(part) for part in parts):
        return True
    if any(_looks_like_package_runner(part) for part in parts) and any(_looks_like_dev_script(part) for part in parts):
        return True
    return False


def _looks_like_frontend_build_command(parts: list[str]) -> bool:
    if "build" in parts and any(_looks_like_package_runner(part) for part in parts):
        return True
    if "vite" in parts and "build" in parts:
        return True
    if any(_looks_like_vite_invocation(part) for part in parts) and "build" in parts:
        return True
    if "tsc" in parts and "-b" in parts and "build" in parts:
        return True
    return False


def _contains_python_inline_command(parts: list[str]) -> bool:
    for index, part in enumerate(parts):
        if part == "-c" and any(_looks_like_python_executable(previous) for previous in parts[:index]):
            return True
    return False


def _looks_like_python_executable(part: str) -> bool:
    normalized = str(part or "").replace("\\", "/").lower()
    return normalized in {"python", "python.exe", "py", "py.exe"} or normalized.endswith("/python.exe")


def _looks_like_vite_invocation(part: str) -> bool:
    normalized = str(part or "").replace("\\", "/").lower().strip('"')
    return normalized in {"vite", "vite.cmd"} or normalized.endswith("/vite") or normalized.endswith("/vite.cmd")


def _looks_like_package_runner(part: str) -> bool:
    normalized = str(part or "").replace("\\", "/").lower().strip('"')
    return normalized in {
        "npm",
        "npm.cmd",
        "pnpm",
        "pnpm.cmd",
        "yarn",
        "yarn.cmd",
        "bun",
        "bun.exe",
    } or normalized.endswith(
        ("/npm", "/npm.cmd", "/pnpm", "/pnpm.cmd", "/yarn", "/yarn.cmd", "/bun", "/bun.exe")
    )


def _looks_like_dev_script(part: str) -> bool:
    normalized = str(part or "").replace("\\", "/").lower().strip('"')
    return normalized == "dev" or normalized.endswith(":dev")


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


def _profile_marker_text(profile_dir: Path | str) -> str:
    try:
        return os.path.normcase(str(Path(profile_dir).resolve())).replace("\\", "/").rstrip("/")
    except OSError:
        return os.path.normcase(str(profile_dir)).replace("\\", "/").rstrip("/")


def _looks_like_edge_process(info: dict[str, Any]) -> bool:
    return str(info.get("name") or "").strip().lower() == "msedge.exe"


def _command_line_has_profile_marker(command_line: str, profile_marker: str) -> bool:
    if not command_line or not profile_marker:
        return False
    normalized = os.path.normcase(command_line).replace("\\", "/")
    return _contains_path_segment(normalized, profile_marker)


def _memory_info_mb(memory_info: object) -> tuple[float, float]:
    rss = getattr(memory_info, "rss", 0) or 0
    private = getattr(memory_info, "private", 0) or getattr(memory_info, "private_bytes", 0) or rss
    return round(float(rss) / 1024 / 1024, 1), round(float(private) / 1024 / 1024, 1)


def _edge_process_type(command_line: str) -> str:
    return _extract_switch_value(command_line, "--type") or "browser"


def _edge_process_subtype(command_line: str) -> str:
    return _extract_switch_value(command_line, "--utility-sub-type") or _extract_switch_value(command_line, "--renderer-sub-type")


def _extract_switch_value(command_line: str, switch_name: str) -> str:
    prefix = f"{switch_name}="
    for part in str(command_line or "").split():
        if part.startswith(prefix):
            return part[len(prefix) :].strip().strip('"')
    return ""


def _truncate_text(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


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
        if _is_port_candidate(part):
            previous = parts[index - 1].lower() if index > 0 else ""
            if previous in {"http.server", "serve", "server"}:
                return int(part)
    return 0


def _is_port_candidate(value: str) -> bool:
    try:
        port = int(str(value or "").strip())
    except ValueError:
        return False
    return 0 < port < 65536


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


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or clean repo-owned runtime processes.")
    parser.add_argument("--json", action="store_true", help="Write machine-readable JSON.")
    parser.add_argument(
        "--cleanup-residual-workbench",
        action="store_true",
        help="Terminate repo-local unmanaged workbench residual processes.",
    )
    parser.add_argument(
        "--cleanup-unmanaged-workbench-backends",
        action="store_true",
        help="Terminate repo-local unmanaged workbench backend residual processes without touching frontend dev servers.",
    )
    parser.add_argument("--exclude-pid", action="append", type=int, default=[], help="PID to exclude from cleanup.")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--managed-browser-profile", default="", help="Edge profile directory for managed browser memory snapshot.")
    args = parser.parse_args(argv)

    if args.managed_browser_profile:
        payload = managed_browser_process_payload(profile_dir=args.managed_browser_profile)
    elif args.cleanup_unmanaged_workbench_backends:
        payload = terminate_unmanaged_workbench_backends(
            project_root=PROJECT_ROOT,
            exclude_pids=args.exclude_pid,
            timeout_seconds=args.timeout_seconds,
        )
    elif args.cleanup_residual_workbench:
        payload = terminate_unmanaged_workbench_processes(
            project_root=PROJECT_ROOT,
            exclude_pids=args.exclude_pid,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        payload = residual_process_payload(project_root=PROJECT_ROOT, exclude_pids=args.exclude_pid)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
