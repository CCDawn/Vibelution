"""Local project-agent-as-tool surface for host agents (MCP/CLI)."""

from .project_agent_tool_service import (
    ProjectAgentToolError,
    list_project_agents_for_tool,
    run_project_agent_tool,
)

__all__ = [
    "ProjectAgentToolError",
    "list_project_agents_for_tool",
    "run_project_agent_tool",
]
