"""Official-SDK MCP adapter for the managed external-Agent gateway.

Business writes are intentionally delegated to the backend client.  This module
owns protocol lifecycle, discovery metadata, the fixed guide Resource, and the
stable five-tool surface only.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import Annotations, CallToolResult, TextContent, ToolAnnotations

from .backend_client import BackendClientError, ManagedAgentBackendClient
from .contracts import (
    GUIDE_URI,
    GUIDE_VERSION,
    MCP_TOOL_NAMES,
    SERVER_NAME,
    SERVER_VERSION,
)

SERVER_INSTRUCTIONS = f"""Before the first tool call, read {GUIDE_URI}.
Only non-team Agents are externally callable. Use list -> start -> get;
resolve only approvals belonging to your task, and cancel through the managed task API."""


class ManagedAgentBackend(Protocol):
    async def list_agents(self, *, limit: int = 50) -> dict[str, Any]: ...

    async def start_task(
        self,
        *,
        agent_id: str,
        task: str,
        permission_profile: str,
        client_request_id: str,
        title: str,
    ) -> dict[str, Any]: ...

    async def get_task(self, *, task_id: str) -> dict[str, Any]: ...

    async def resolve_approval(
        self,
        *,
        task_id: str,
        approval_id: str,
        decision: str,
        expected_revision: str,
        reason: str,
    ) -> dict[str, Any]: ...

    async def cancel_task(self, *, task_id: str) -> dict[str, Any]: ...


def default_backend(project_root: Path) -> ManagedAgentBackendClient:
    return ManagedAgentBackendClient(project_root)


def _tool_description(summary: str) -> str:
    return f"{summary} Read {GUIDE_URI} (guide version {GUIDE_VERSION}) before calling."


async def _managed_call(
    call: Awaitable[dict[str, Any]],
) -> dict[str, Any] | CallToolResult:
    try:
        return await call
    except BackendClientError as exc:
        payload = {
            "status": "error",
            "code": exc.code,
            "message": str(exc),
            "guideUri": GUIDE_URI,
            "guideVersion": GUIDE_VERSION,
        }
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))
            ],
            structuredContent=payload,
            isError=True,
        )


def build_server(
    project_root: Path,
    *,
    backend: ManagedAgentBackend | None = None,
) -> MCPServer[Any]:
    root = Path(project_root).expanduser().resolve()
    guide_path = root / "docs" / "agents" / "mcp-managed-agent-gateway.md"
    managed_backend: ManagedAgentBackend = backend or default_backend(root)

    @asynccontextmanager
    async def managed_lifespan(_server: MCPServer[Any]):
        lifecycle = getattr(managed_backend, "lifecycle", None)
        if callable(lifecycle):
            async with lifecycle():
                yield managed_backend
            return
        yield managed_backend

    server: MCPServer[Any] = MCPServer(
        name=SERVER_NAME,
        title="Vibelution Managed Agent Gateway",
        description="Managed local gateway for externally callable non-team Vibelution Agents.",
        instructions=SERVER_INSTRUCTIONS,
        version=SERVER_VERSION,
        log_level="WARNING",
        lifespan=managed_lifespan,
    )

    last_modified = ""
    if guide_path.is_file():
        last_modified = (
            datetime.fromtimestamp(
                guide_path.stat().st_mtime,
                tz=timezone.utc,
            )
            .isoformat()
            .replace("+00:00", "Z")
        )

    @server.resource(
        GUIDE_URI,
        name="mcp-managed-agent-gateway-guide",
        title="Vibelution MCP Managed Agent Gateway Guide",
        description="Read before deploying or calling the Vibelution managed Agent gateway.",
        mime_type="text/markdown",
        annotations=Annotations(
            audience=["assistant", "user"],
            priority=1.0,
            last_modified=last_modified or None,
        ),
        meta={"guideVersion": GUIDE_VERSION},
    )
    def managed_agent_guide() -> str:
        if not guide_path.is_file():
            raise FileNotFoundError("canonical managed-Agent gateway guide is missing")
        return guide_path.read_text(encoding="utf-8")

    @server.tool(
        name=MCP_TOOL_NAMES[0],
        description=_tool_description(
            "List externally eligible non-team project Agents."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    async def list_project_agents(limit: int = 50) -> dict[str, Any]:
        return await _managed_call(managed_backend.list_agents(limit=limit))

    @server.tool(
        name=MCP_TOOL_NAMES[1],
        description=_tool_description("Create one asynchronous managed Agent task."),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    async def start_project_agent_task(
        agent_id: str,
        task: str,
        permission_profile: str = "read_only",
        client_request_id: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        return await _managed_call(
            managed_backend.start_task(
                agent_id=agent_id,
                task=task,
                permission_profile=permission_profile,
                client_request_id=client_request_id,
                title=title,
            )
        )

    @server.tool(
        name=MCP_TOOL_NAMES[2],
        description=_tool_description("Read managed task status and bounded results."),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    async def get_project_agent_task(task_id: str) -> dict[str, Any]:
        return await _managed_call(managed_backend.get_task(task_id=task_id))

    @server.tool(
        name=MCP_TOOL_NAMES[3],
        description=_tool_description(
            "Explicitly resolve one approval owned by the managed task."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    async def resolve_project_agent_approval(
        task_id: str,
        approval_id: str,
        decision: str,
        expected_revision: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        return await _managed_call(
            managed_backend.resolve_approval(
                task_id=task_id,
                approval_id=approval_id,
                decision=decision,
                expected_revision=expected_revision,
                reason=reason,
            )
        )

    @server.tool(
        name=MCP_TOOL_NAMES[4],
        description=_tool_description(
            "Idempotently request cancellation of one managed task."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    async def cancel_project_agent_task(task_id: str) -> dict[str, Any]:
        return await _managed_call(managed_backend.cancel_task(task_id=task_id))

    return server


def tool_descriptors(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    server = build_server(root)

    async def collect() -> list[dict[str, Any]]:
        tools = await server.list_tools()
        return [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools]

    return anyio.run(collect)


def main(*, project_root: Path | None = None) -> int:
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    build_server(root).run(transport="stdio")
    return 0


__all__ = [
    "SERVER_INSTRUCTIONS",
    "build_server",
    "default_backend",
    "main",
    "tool_descriptors",
]
