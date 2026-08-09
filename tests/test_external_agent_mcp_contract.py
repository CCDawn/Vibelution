from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIDE_URI = "vibelution://guide/mcp-managed-agent-gateway"
EXPECTED_TOOL_NAMES = {
    "list_project_agents",
    "start_project_agent_task",
    "get_project_agent_task",
    "resolve_project_agent_approval",
    "cancel_project_agent_task",
}


def _contracts_module():
    return importlib.import_module("core.external_agent.contracts")


def _mcp_server_module():
    return importlib.import_module("core.external_agent.mcp_server")


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def test_shared_contract_exposes_fixed_guide_and_five_tools() -> None:
    contracts = _contracts_module()

    assert contracts.GUIDE_URI == GUIDE_URI
    assert set(contracts.MCP_TOOL_NAMES) == EXPECTED_TOOL_NAMES
    assert "run_project_agent" not in contracts.MCP_TOOL_NAMES
    assert contracts.GUIDE_VERSION == "0.3.2"
    assert contracts.SERVER_VERSION == "0.3.1"


def test_mcp_server_metadata_contains_discovery_fallback() -> None:
    mcp_server = _mcp_server_module()

    assert GUIDE_URI in mcp_server.SERVER_INSTRUCTIONS
    assert "list" in mcp_server.SERVER_INSTRUCTIONS
    assert "start" in mcp_server.SERVER_INSTRUCTIONS
    assert "get" in mcp_server.SERVER_INSTRUCTIONS

    descriptors = mcp_server.tool_descriptors()
    assert {item["name"] for item in descriptors} == EXPECTED_TOOL_NAMES
    for descriptor in descriptors:
        assert GUIDE_URI in descriptor["description"]
        assert descriptor["outputSchema"]["type"] == "object"


def test_guide_resource_descriptor_uses_cross_protocol_stable_fields() -> None:
    mcp_server = _mcp_server_module()

    async def list_resources() -> list[dict[str, object]]:
        resources = await mcp_server.build_server(PROJECT_ROOT).list_resources()
        return [
            item.model_dump(by_alias=True, exclude_none=True) for item in resources
        ]

    descriptors = anyio.run(list_resources)

    assert len(descriptors) == 1
    assert descriptors[0]["uri"] == GUIDE_URI
    assert descriptors[0]["mimeType"] == "text/markdown"
    assert "annotations" not in descriptors[0]
    assert "_meta" not in descriptors[0]


def test_default_mcp_backend_is_loopback_client() -> None:
    mcp_server = _mcp_server_module()

    backend = mcp_server.default_backend(PROJECT_ROOT)

    assert backend.project_root == PROJECT_ROOT.resolve()
    assert backend.__class__.__name__ == "ManagedAgentBackendClient"


def test_adapter_source_does_not_spawn_shell_or_secondary_backend() -> None:
    sources = "\n".join(
        (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "core/external_agent/mcp_server.py",
            "core/external_agent/backend_client.py",
            "scripts/project_agent_tool.py",
        )
    )

    for forbidden in (
        "subprocess.Popen",
        "create_subprocess",
        "os.system",
        "cmd.exe",
        "powershell.exe",
    ):
        assert forbidden not in sources


@pytest.mark.skipif(os.name != "nt", reason="Windows no-console contract")
def test_official_sdk_test_host_uses_create_no_window_for_stdio_child() -> None:
    from mcp.os.win32.utilities import create_windows_process

    source = inspect.getsource(create_windows_process)

    assert "CREATE_NO_WINDOW" in source


def test_mcp_backend_business_error_is_structured_tool_error() -> None:
    mcp_server = _mcp_server_module()
    backend_client = importlib.import_module("core.external_agent.backend_client")

    class FailingBackend:
        async def list_agents(self, *, limit: int = 50) -> dict[str, object]:
            del limit
            raise backend_client.BackendClientError(
                "The managed task is not available.",
                code="TASK_NOT_FOUND",
            )

    async def call_tool():
        server = mcp_server.build_server(PROJECT_ROOT, backend=FailingBackend())
        return await server.call_tool("list_project_agents", {"limit": 1})

    result = anyio.run(call_tool)

    assert result.is_error is True
    assert result.structured_content == {
        "status": "error",
        "code": "TASK_NOT_FOUND",
        "message": "The managed task is not available.",
        "guideUri": GUIDE_URI,
        "guideVersion": "0.3.2",
    }
    assert "Traceback" not in result.content[0].text


def test_mcp_legacy_initialize_uses_newline_stdio_and_advertises_guide() -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "vibelution-contract-test", "version": "1"},
        },
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "project_agent_tool.py"),
            "mcp",
            "--project-root",
            str(PROJECT_ROOT),
        ],
        input=(json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8"),
        capture_output=True,
        cwd=PROJECT_ROOT,
        timeout=15,
        check=False,
        creationflags=_creation_flags(),
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    stdout_lines = [
        line for line in completed.stdout.decode("utf-8").splitlines() if line.strip()
    ]
    assert stdout_lines, completed.stderr.decode("utf-8", errors="replace")
    assert not stdout_lines[0].lower().startswith("content-length:")

    response = json.loads(stdout_lines[0])
    assert response["id"] == 1
    assert GUIDE_URI in response["result"]["instructions"]
    assert "resources" in response["result"]["capabilities"]
    assert "tools" in response["result"]["capabilities"]


async def _probe_official_client(mode: str) -> tuple[str, str, set[str], str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(PROJECT_ROOT / "scripts" / "project_agent_tool.py"),
            "mcp",
            "--project-root",
            str(PROJECT_ROOT),
        ],
        cwd=PROJECT_ROOT,
    )
    async with Client(
        stdio_client(params, errlog=subprocess.DEVNULL),
        mode=mode,
        read_timeout_seconds=10,
        cache=None,
    ) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        assert [str(item.uri) for item in resources.resources] == [GUIDE_URI]
        guide = await client.read_resource(GUIDE_URI)
        guide_text = guide.contents[0].text
        with pytest.raises(MCPError):
            await client.read_resource("vibelution://guide/not-allowlisted")
        return (
            client.protocol_version,
            client.instructions or "",
            {item.name for item in tools.tools},
            guide_text,
        )


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_official_sdk_client_discovers_tools_and_allowlisted_guide(mode: str) -> None:
    protocol_version, instructions, tool_names, guide_text = anyio.run(
        _probe_official_client,
        mode,
    )

    assert protocol_version
    assert GUIDE_URI in instructions
    assert tool_names == EXPECTED_TOOL_NAMES
    assert "# Vibelution MCP 受管 Agent 网关部署与调用指南" in guide_text


@pytest.mark.anyio
async def test_stdio_tool_errors_are_structured_and_protocol_stays_alive(
    tmp_path,
) -> None:
    guide = tmp_path / "docs" / "agents" / "mcp-managed-agent-gateway.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# Isolated MCP guide\n", encoding="utf-8")
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(PROJECT_ROOT / "scripts" / "project_agent_tool.py"),
            "mcp",
            "--project-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
    )
    async with Client(
        stdio_client(params, errlog=subprocess.DEVNULL),
        mode="auto",
        read_timeout_seconds=10,
        cache=None,
    ) as client:
        unavailable = await client.call_tool("list_project_agents", {"limit": 1})
        invalid = await client.call_tool(
            "list_project_agents", {"limit": "not-an-integer"}
        )
        unknown = await client.call_tool("not_a_vibelution_tool", {})
        resources = await client.list_resources()

    assert unavailable.is_error is True
    assert unavailable.structured_content["code"] == "BACKEND_UNAVAILABLE"
    assert unavailable.structured_content["guideUri"] == GUIDE_URI
    assert invalid.is_error is True
    assert unknown.is_error is True
    assert [str(item.uri) for item in resources.resources] == [GUIDE_URI]


@pytest.mark.anyio
async def test_in_process_tool_call_honors_request_cancellation() -> None:
    mcp_server = _mcp_server_module()

    class BlockingBackend:
        async def list_agents(self, *, limit: int = 50) -> dict[str, object]:
            del limit
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

    server = mcp_server.build_server(PROJECT_ROOT, backend=BlockingBackend())

    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.05):
            await server.call_tool("list_project_agents", {"limit": 1})
