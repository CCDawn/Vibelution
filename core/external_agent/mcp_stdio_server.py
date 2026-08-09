"""Compatibility import for the official-SDK MCP stdio entrypoint.

The former hand-written Content-Length framing and direct business-service
dispatch have been removed.  New code should import :mod:`mcp_server`.
"""

from .mcp_server import main

__all__ = ["main"]
