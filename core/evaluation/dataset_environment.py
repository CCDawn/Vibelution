# -*- coding: utf-8 -*-
"""Dataset execution environment contracts and preflight helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


TERMINAL_BENCH_CORE_REPO = "https://github.com/harbor-framework/terminal-bench-2"
TERMINAL_BENCH_CORE_REVISION = "2fd12b88aafdd04a52c298e3940bcb189f9766d6"
TERMINAL_BENCH_WINDOWS_APP_ALIAS = "C:\\app"
_TOOL_REQUIREMENT_NAMES = {"uv", "docker"}
_DOCKER_DAEMON_REQUIREMENT_NAME = "docker daemon"


def terminal_bench_environment_contract(*, official_seed: bool) -> Dict[str, Any]:
    if not official_seed:
        return {
            "kind": "terminal_bench_local_smoke",
            "preflight": {"required": False},
            "official_score_available": False,
        }
    return {
        "kind": "terminal_bench_task_environment",
        "preflight": {
            "required": True,
            "strategy": "path_alias",
        },
        "required_paths": [
            {
                "path": "/app",
                "aliases": [TERMINAL_BENCH_WINDOWS_APP_ALIAS],
                "required_for": "custom_harness_task_files",
                "description": "Terminal-Bench task workspace mounted as /app in official containers.",
            }
        ],
        "official_verifier": {
            "status": "harbor_pending",
            "requires": ["uv", "docker", "docker daemon"],
            "dataset": "terminal-bench@2.0",
            "repo": TERMINAL_BENCH_CORE_REPO,
            "revision": TERMINAL_BENCH_CORE_REVISION,
        },
        "official_score_available": False,
        "custom_harness_score_label": "Vibelution custom score (non-official Terminal-Bench score)",
    }


def render_environment_contract_prompt(contract: Dict[str, Any]) -> str:
    if not contract or contract.get("kind") != "terminal_bench_task_environment":
        return ""
    required_paths = [item for item in contract.get("required_paths") or [] if isinstance(item, dict)]
    path_lines: List[str] = []
    for item in required_paths:
        path = str(item.get("path") or "").strip()
        aliases = [str(alias).strip() for alias in item.get("aliases") or [] if str(alias).strip()]
        alias_text = f" (Windows/local alias: {', '.join(aliases)})" if aliases else ""
        if path:
            path_lines.append(f"- Required task path: {path}{alias_text}")
    path_block = "\n".join(path_lines) or "- Required task paths: use dataset environment metadata."
    return (
        "\n\n"
        "Custom harness environment contract:\n"
        "- This is a Vibelution custom-harness run, not an official Terminal-Bench score.\n"
        "- Before editing, run an environment preflight using the required task paths below.\n"
        f"{path_block}\n"
        "- On Windows, treat a declared alias as equivalent to the POSIX path; for example, "
        "/app may be available as C:\\app.\n"
        "- If all declared path aliases for a required task path are missing, treat the case as "
        "environment_unavailable: record the missing path/tool evidence, close the transaction "
        "with status=failed, and stop cleanly.\n"
        "- Do not keep retrying Unix-only commands on Windows after an environment/path/tool preflight fails.\n"
        "- Do not claim task success unless the verifier actually passes in an available task environment."
    )


def _candidate_paths(path_text: str, aliases: Iterable[str], *, project_root: Optional[Path] = None) -> List[Path]:
    candidates: List[Path] = []
    raw_items = [path_text, *list(aliases)]
    for raw in raw_items:
        item = str(raw or "").strip()
        if not item:
            continue
        path = Path(item)
        candidates.append(path if path.is_absolute() else (project_root or Path.cwd()) / path)
        if os.name == "nt" and item.startswith("/") and len(item) > 1:
            candidates.append(Path(f"C:{item.replace('/', os.sep)}"))
    deduped: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            deduped.append(candidate)
            seen.add(key)
    return deduped


def _subprocess_no_window_kwargs() -> Dict[str, int]:
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"creationflags": flags} if flags else {}


def _tool_requirement_status(name: str) -> Dict[str, Any]:
    executable = shutil.which(name)
    return {
        "name": name,
        "available": bool(executable),
        "evidence": executable or "not_found",
    }


def _docker_daemon_requirement_status(*, project_root: Optional[Path] = None) -> Dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return {
            "name": _DOCKER_DAEMON_REQUIREMENT_NAME,
            "available": False,
            "evidence": "docker_cli_not_found",
        }
    try:
        proc = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            cwd=str(project_root or Path.cwd()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
    except Exception as exc:
        return {
            "name": _DOCKER_DAEMON_REQUIREMENT_NAME,
            "available": False,
            "evidence": f"{type(exc).__name__}: {exc}",
        }
    output = (proc.stdout or "").strip()
    error = (proc.stderr or "").strip()
    return {
        "name": _DOCKER_DAEMON_REQUIREMENT_NAME,
        "available": proc.returncode == 0 and bool(output),
        "evidence": output or error or f"returncode={proc.returncode}",
    }


def _verifier_requirement_status(requirement: str, *, project_root: Optional[Path] = None) -> Dict[str, Any]:
    name = str(requirement or "").strip().lower()
    if name in _TOOL_REQUIREMENT_NAMES:
        return _tool_requirement_status(name)
    if name == _DOCKER_DAEMON_REQUIREMENT_NAME:
        return _docker_daemon_requirement_status(project_root=project_root)
    return {
        "name": str(requirement or "").strip(),
        "available": False,
        "evidence": "unsupported_requirement",
    }


def _preflight_official_verifier(
    contract: Dict[str, Any],
    *,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    verifier = contract.get("official_verifier") if isinstance(contract.get("official_verifier"), dict) else {}
    requirements: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in verifier.get("requires") or []:
        requirement = str(raw or "").strip()
        key = requirement.lower()
        if not requirement or key in seen:
            continue
        seen.add(key)
        requirements.append(_verifier_requirement_status(requirement, project_root=project_root))
    missing = [item for item in requirements if not bool(item.get("available"))]
    return {
        "required": bool(requirements),
        "status": str(verifier.get("status") or "").strip(),
        "requirements": requirements,
        "missing": missing,
        "available": not missing,
    }


def preflight_environment_contract(
    contract: Dict[str, Any],
    *,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    required_paths = [item for item in contract.get("required_paths") or [] if isinstance(item, dict)]
    checked: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    for item in required_paths:
        path_text = str(item.get("path") or "").strip()
        aliases = [str(alias).strip() for alias in item.get("aliases") or [] if str(alias).strip()]
        candidates = _candidate_paths(path_text, aliases, project_root=project_root)
        existing = [str(path) for path in candidates if path.exists()]
        payload = {
            "path": path_text,
            "aliases": aliases,
            "candidates": [str(path) for path in candidates],
            "existing": existing,
            "available": bool(existing),
        }
        checked.append(payload)
        if not existing:
            missing.append(payload)
    verifier = _preflight_official_verifier(contract, project_root=project_root)
    missing_verifier = list(verifier.get("missing") or [])
    available = not missing and not missing_verifier
    if missing:
        status = "missing"
    elif missing_verifier:
        status = "missing_verifier_dependency"
    else:
        status = "available"
    return {
        "status": status,
        "available": available,
        "checked": checked,
        "missing": missing,
        "official_verifier": verifier,
    }
