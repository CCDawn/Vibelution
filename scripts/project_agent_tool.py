#!/usr/bin/env python3
"""CLI and official-SDK MCP entry for the managed project-Agent gateway."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from functools import partial
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import anyio

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.external_agent.backend_client import (
    BackendClientError,
    ManagedAgentBackendClient,
)
from core.external_agent.contracts import (
    API_PROTOCOL_VERSION,
    GUIDE_URI,
    GUIDE_VERSION,
    MCP_TOOL_NAMES,
    SERVER_VERSION,
)
from core.external_agent.mcp_server import main as mcp_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project_agent_tool",
        description="Call the Vibelution managed external-Agent backend or run its MCP adapter.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser(
        "list", help="List externally callable non-team Agents"
    )
    list_parser.add_argument("--project-root", type=Path, default=REPO_ROOT)
    list_parser.add_argument("--limit", type=int, default=50)

    run_parser = sub.add_parser(
        "run",
        help="Compatibility wrapper: start a task and poll briefly without auto-approving",
    )
    run_parser.add_argument("--project-root", type=Path, default=REPO_ROOT)
    run_parser.add_argument("--agent-id", default="")
    run_parser.add_argument("--agent-code", default="")
    run_parser.add_argument("--task", required=True)
    run_parser.add_argument("--client-request-id", default="")
    run_parser.add_argument("--timeout-seconds", type=float, default=10.0)
    run_parser.add_argument(
        "--permission-profile",
        default="read_only",
        choices=["read_only", "workspace_write", "full_access"],
    )
    run_parser.add_argument("--title", default="")

    mcp_parser = sub.add_parser(
        "mcp", help="Run the managed official-SDK MCP stdio server"
    )
    mcp_parser.add_argument("--project-root", type=Path, default=REPO_ROOT)

    self_check_parser = sub.add_parser(
        "self-check",
        help="Verify project interpreter, guide, runtime identity, and MCP contract",
    )
    self_check_parser.add_argument("--project-root", type=Path, default=REPO_ROOT)
    self_check_parser.add_argument("--json", action="store_true")
    return parser


def _git_revision(project_root: Path) -> str:
    git_entry = project_root / ".git"
    git_dir = git_entry
    if git_entry.is_file():
        text = git_entry.read_text(encoding="utf-8", errors="replace").strip()
        if not text.lower().startswith("gitdir:"):
            return ""
        git_dir = Path(text.split(":", 1)[1].strip())
        if not git_dir.is_absolute():
            git_dir = (project_root / git_dir).resolve()
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return ""
    head = head_path.read_text(encoding="utf-8", errors="replace").strip()
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    candidates = [git_dir / ref]
    common_dir_path = git_dir / "commondir"
    if common_dir_path.is_file():
        common_dir = Path(common_dir_path.read_text(encoding="utf-8").strip())
        if not common_dir.is_absolute():
            common_dir = (git_dir / common_dir).resolve()
        candidates.append(common_dir / ref)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _guide_status(project_root: Path) -> str:
    path = project_root / "docs" / "agents" / "mcp-managed-agent-gateway.md"
    if not path.is_file():
        return "MISSING"
    match = re.search(
        r"Gateway Status:\*\*\s*`([^`]+)`",
        path.read_text(encoding="utf-8", errors="replace"),
    )
    return str(match.group(1) if match else "UNKNOWN").strip()


async def build_self_check(
    project_root: Path,
    backend: ManagedAgentBackendClient,
    interpreter_path: Path,
    sdk_version: str,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    source_revision = _git_revision(root)
    guide_status = _guide_status(root)
    interpreter = Path(interpreter_path).expanduser().resolve()
    venv_root = (root / ".venv").resolve()
    interpreter_in_project_venv = (
        interpreter == venv_root or venv_root in interpreter.parents
    )
    failed_checks: list[str] = []
    backend_info: dict[str, Any]
    try:
        backend_info = await backend.diagnostics()
    except BackendClientError as exc:
        backend_info = {"status": "unavailable", "error": str(exc)}
        failed_checks.append("backend")
    if not interpreter_in_project_venv:
        failed_checks.append("project_interpreter")
    if str(sdk_version or "") != "2.0.0":
        failed_checks.append("mcp_sdk_version")
    if guide_status != "DEPLOYABLE":
        failed_checks.append("guide_status")
    if not source_revision:
        failed_checks.append("source_revision")
    backend_root = str(backend_info.get("projectRoot") or "").strip()
    if backend_root and Path(backend_root).expanduser().resolve() != root:
        failed_checks.append("backend_project_root")
    backend_revision = str(backend_info.get("runtimeSourceRevision") or "").strip()
    if source_revision and backend_revision != source_revision:
        failed_checks.append("backend_source_revision")
    if str(backend_info.get("apiProtocolVersion") or "") != API_PROTOCOL_VERSION:
        failed_checks.append("api_protocol_version")
    if str(backend_info.get("serverVersion") or "") != SERVER_VERSION:
        failed_checks.append("server_version")
    if not bool(backend_info.get("enabled")):
        failed_checks.append("gateway_enabled")
    failed_checks = list(dict.fromkeys(failed_checks))
    deployable = not failed_checks
    return {
        "status": "ready" if deployable else "not_ready",
        "deployable": deployable,
        "sourceRevision": source_revision,
        "projectRoot": str(root),
        "interpreter": str(interpreter),
        "backend": str(backend_info.get("status") or "unavailable"),
        "backendIdentity": backend_info,
        "apiProtocolVersion": API_PROTOCOL_VERSION,
        "serverVersion": SERVER_VERSION,
        "protocolEras": ["legacy", "modern"],
        "guideUri": GUIDE_URI,
        "guideVersion": GUIDE_VERSION,
        "guideStatus": guide_status,
        "tools": list(MCP_TOOL_NAMES),
        "mcpSdkVersion": str(sdk_version or ""),
        "tasksExtension": "not_available_in_mcp_sdk_2.0.0",
        "failedChecks": failed_checks,
    }


async def list_via_backend(
    backend: ManagedAgentBackendClient,
    *,
    limit: int,
) -> dict[str, Any]:
    return await backend.list_agents(limit=limit)


async def run_via_backend(
    backend: ManagedAgentBackendClient,
    *,
    agent_id: str,
    agent_code: str,
    task: str,
    permission_profile: str,
    client_request_id: str,
    title: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    resolved_agent_id = str(agent_id or "").strip()
    if not resolved_agent_id and str(agent_code or "").strip():
        catalog = await backend.list_agents(limit=200)
        needle = str(agent_code).strip().casefold()
        matches = [
            item
            for item in list(catalog.get("agents") or [])
            if isinstance(item, dict)
            and needle
            in {
                str(item.get("agentId") or "").casefold(),
                str(item.get("agentCode") or "").casefold(),
                str(item.get("displayName") or "").casefold(),
            }
        ]
        if len(matches) == 1:
            resolved_agent_id = str(matches[0].get("agentId") or "")
    if not resolved_agent_id:
        raise ValueError("agent-id or a uniquely matching agent-code is required")

    result = await backend.start_task(
        agent_id=resolved_agent_id,
        task=task,
        permission_profile=permission_profile,
        client_request_id=client_request_id,
        title=title,
    )
    task_id = str(result.get("taskId") or "")
    deadline = time.monotonic() + max(0.0, min(float(timeout_seconds), 30.0))
    while task_id and result.get("shouldPoll", True) and time.monotonic() < deadline:
        if str(result.get("status") or "") == "awaiting_approval":
            break
        await anyio.sleep(0.5)
        result = await backend.get_task(task_id=task_id)
    if result.get("shouldPoll", False):
        result = dict(result)
        result["compatibilityWrapper"] = (
            "task remains managed; use get/resolve/cancel through MCP"
        )
    return result


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "mcp":
        return mcp_main(project_root=args.project_root)

    backend = ManagedAgentBackendClient(Path(args.project_root).resolve())
    try:
        if args.command == "self-check":
            try:
                sdk_version = importlib_metadata.version("mcp")
            except importlib_metadata.PackageNotFoundError:
                sdk_version = ""
            payload = anyio.run(
                build_self_check,
                Path(args.project_root),
                backend,
                Path(sys.executable),
                sdk_version,
            )
        elif args.command == "list":
            payload = anyio.run(partial(list_via_backend, backend, limit=args.limit))
        elif args.command == "run":
            payload = anyio.run(
                partial(
                    run_via_backend,
                    backend,
                    agent_id=args.agent_id,
                    agent_code=args.agent_code,
                    task=args.task,
                    permission_profile=args.permission_profile,
                    client_request_id=args.client_request_id,
                    title=args.title,
                    timeout_seconds=args.timeout_seconds,
                )
            )
        else:
            raise ValueError(f"unknown command: {args.command}")
    except (BackendClientError, ValueError) as exc:
        _print(
            {
                "status": "error",
                "code": exc.code
                if isinstance(exc, BackendClientError)
                else "INVALID_ARGUMENT",
                "message": str(exc),
            }
        )
        return 2
    _print(payload)
    if args.command == "self-check":
        return 0 if bool(payload.get("deployable")) else 1
    return 1 if str(payload.get("status") or "") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
