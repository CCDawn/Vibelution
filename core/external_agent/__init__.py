"""Managed local project-Agent gateway for host agents."""

from .backend_client import BackendClientError, ManagedAgentBackendClient
from .contracts import GUIDE_URI, GUIDE_VERSION, MCP_TOOL_NAMES

__all__ = [
    "GUIDE_URI",
    "GUIDE_VERSION",
    "MCP_TOOL_NAMES",
    "BackendClientError",
    "ManagedAgentBackendClient",
]
