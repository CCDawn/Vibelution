"""Minimal MCP stdio server exposing project agents as tools.

Transport: JSON-RPC 2.0 with LSP-style Content-Length framing (MCP stdio).
No third-party MCP SDK required for v1.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .project_agent_tool_service import (
    ProjectAgentToolError,
    list_project_agents_for_tool,
    run_project_agent_tool,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "vibelution-project-agent"
SERVER_VERSION = "0.1.0"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_project_agents",
        "description": (
            "List Vibelution project Agents available as local sub-agents. "
            "Returns agentId, agentCode, displayName, status, and permissionPreset."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_archived": {
                    "type": "boolean",
                    "description": "Include archived agents (default false).",
                    "default": False,
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "run_project_agent",
        "description": (
            "Run one synchronous task against a project Agent (single-round sub-agent). "
            "Waits for the agent turn to finish and returns a JSON summary with reply text. "
            "Default permission_mode is auto_review (tighter than full_access); "
            "pending tool approvals are auto-accepted for headless hosts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Project agent id (preferred).",
                },
                "agent_code": {
                    "type": "string",
                    "description": "Project agent code/name if id is unknown.",
                },
                "task": {
                    "type": "string",
                    "description": "Task prompt for the project agent.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Max wait seconds (default 600, max 1800).",
                    "default": 600,
                },
                "permission_mode": {
                    "type": "string",
                    "enum": ["auto_review", "full_access", "request_approval"],
                    "description": "Tool permission posture (default auto_review).",
                    "default": "auto_review",
                },
                "title": {
                    "type": "string",
                    "description": "Optional session title override.",
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        },
    },
]


def main(argv: list[str] | None = None) -> int:
    del argv  # MCP stdio ignores CLI args in v1.
    return serve_stdio(sys.stdin.buffer, sys.stdout.buffer, sys.stderr)


def serve_stdio(
    stdin: Any,
    stdout: Any,
    stderr: TextIO,
) -> int:
    while True:
        message = _read_message(stdin)
        if message is None:
            return 0
        response = _dispatch(message)
        if response is not None:
            _write_message(stdout, response)
        # Exit cleanly if client closed after a fatal parse error loop.
        if not isinstance(message, dict):
            print(f"[vibelution-mcp] ignored non-object message", file=stderr)


def _dispatch(message: dict[str, Any]) -> dict[str, Any] | None:
    if "method" not in message:
        return _error(message.get("id"), -32600, "Invalid Request")
    method = str(message.get("method") or "")
    msg_id = message.get("id", None)
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    # Notifications have no id and must not be answered.
    is_notification = "id" not in message

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "notifications/initialized" or method == "initialized":
        return None
    if method == "ping":
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        if is_notification:
            return None
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            result_payload = _call_tool(name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json_dumps(result_payload),
                        }
                    ],
                    "structuredContent": result_payload,
                    "isError": str(result_payload.get("status") or "") == "error",
                },
            }
        except ProjectAgentToolError as exc:
            err = {"status": "error", "code": "INVALID_ARGUMENT", "message": str(exc)}
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json_dumps(err)}],
                    "structuredContent": err,
                    "isError": True,
                },
            }
        except Exception as exc:  # noqa: BLE001 - surface to host agent
            err = {
                "status": "error",
                "code": "INTERNAL_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
            }
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json_dumps(err)}],
                    "structuredContent": err,
                    "isError": True,
                },
            }
    if is_notification:
        return None
    return _error(msg_id, -32601, f"Method not found: {method}")


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "list_project_agents":
        return list_project_agents_for_tool(
            include_archived=bool(arguments.get("include_archived")),
        )
    if name == "run_project_agent":
        return run_project_agent_tool(
            agent_id=str(arguments.get("agent_id") or ""),
            agent_code=str(arguments.get("agent_code") or ""),
            task=str(arguments.get("task") or ""),
            timeout_seconds=float(arguments.get("timeout_seconds") or 600),
            permission_mode=str(arguments.get("permission_mode") or "auto_review"),
            title=str(arguments.get("title") or ""),
        )
    raise ProjectAgentToolError(f"unknown tool: {name}")


def _read_message(stdin: Any) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            break
        if ":" in text:
            key, value = text.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length_raw = headers.get("content-length", "")
    if not length_raw:
        # Fallback: newline-delimited JSON (handy for manual tests).
        if headers:
            return None
        return None
    try:
        length = int(length_raw)
    except ValueError:
        return None
    body = stdin.read(length)
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_message(stdout: Any, message: dict[str, Any]) -> None:
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
    stdout.write(header)
    stdout.write(raw)
    stdout.flush()


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
