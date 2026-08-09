"""Shared wire contracts for the managed external-Agent gateway."""

from __future__ import annotations

API_PROTOCOL_VERSION = "1.0"
GUIDE_URI = "vibelution://guide/mcp-managed-agent-gateway"
GUIDE_VERSION = "0.3.3"
SERVER_NAME = "vibelution"
SERVER_VERSION = "0.3.1"

MCP_TOOL_NAMES = (
    "list_project_agents",
    "start_project_agent_task",
    "get_project_agent_task",
    "resolve_project_agent_approval",
    "cancel_project_agent_task",
)

TASK_ACTIVE_STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "cancelling",
    "stop_unconfirmed",
)
TASK_TERMINAL_STATUSES = (
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)
