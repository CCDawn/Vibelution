#!/usr/bin/env python3
"""CLI / MCP entry for local project-agent-as-tool.

Examples:
  python scripts/project_agent_tool.py list
  python scripts/project_agent_tool.py run --agent-id <id> --task "总结当前 git 状态"
  python scripts/project_agent_tool.py mcp
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.external_agent.mcp_stdio_server import main as mcp_main  # noqa: E402
from core.external_agent.project_agent_tool_service import (  # noqa: E402
    ProjectAgentToolError,
    list_project_agents_for_tool,
    run_project_agent_tool,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="project_agent_tool",
        description="Expose Vibelution project Agents as local sub-agent tools (CLI + MCP).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List project agents")
    list_parser.add_argument("--include-archived", action="store_true")

    run_parser = sub.add_parser("run", help="Run one task on a project agent (sync)")
    run_parser.add_argument("--agent-id", default="")
    run_parser.add_argument("--agent-code", default="")
    run_parser.add_argument("--task", required=True)
    run_parser.add_argument("--timeout-seconds", type=float, default=600.0)
    run_parser.add_argument(
        "--permission-mode",
        default="auto_review",
        choices=["auto_review", "full_access", "request_approval"],
    )
    run_parser.add_argument("--title", default="")

    sub.add_parser("mcp", help="Run MCP stdio server for host agents")

    args = parser.parse_args(argv)
    if args.command == "mcp":
        return mcp_main()
    if args.command == "list":
        payload = list_project_agents_for_tool(include_archived=bool(args.include_archived))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        try:
            payload = run_project_agent_tool(
                agent_id=args.agent_id,
                agent_code=args.agent_code,
                task=args.task,
                timeout_seconds=args.timeout_seconds,
                permission_mode=args.permission_mode,
                title=args.title,
            )
        except ProjectAgentToolError as exc:
            print(
                json.dumps(
                    {"status": "error", "code": "INVALID_ARGUMENT", "message": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("status") != "error" else 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
