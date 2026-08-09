from __future__ import annotations

import importlib.util
from functools import partial
from pathlib import Path

import anyio

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _script_module():
    path = PROJECT_ROOT / "scripts" / "project_agent_tool.py"
    spec = importlib.util.spec_from_file_location("project_agent_tool_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBackend:
    def __init__(self) -> None:
        self.get_calls = 0

    async def list_agents(self, *, limit: int = 50):
        return {
            "status": "ok",
            "agents": [
                {"agentId": "coder", "agentCode": "code", "displayName": "Coder"}
            ][:limit],
        }

    async def start_task(self, **_kwargs):
        return {"taskId": "eat-1", "status": "running", "shouldPoll": True}

    async def get_task(self, *, task_id: str):
        self.get_calls += 1
        assert task_id == "eat-1"
        return {
            "taskId": task_id,
            "status": "awaiting_approval",
            "shouldPoll": True,
            "pendingApprovals": [{"approvalId": "approval-1"}],
        }


def test_cli_source_has_no_backend_write_service_or_auto_approval_import() -> None:
    source = (PROJECT_ROOT / "scripts" / "project_agent_tool.py").read_text(
        encoding="utf-8"
    )

    assert "project_agent_tool_service" not in source
    assert "core.web.services" not in source
    assert "auto_accept" not in source.lower()
    assert "ManagedAgentBackendClient" in source


def test_list_cli_uses_managed_backend() -> None:
    module = _script_module()

    result = anyio.run(partial(module.list_via_backend, FakeBackend(), limit=20))

    assert result["agents"][0]["agentId"] == "coder"


def test_run_wrapper_returns_task_when_explicit_approval_is_required() -> None:
    module = _script_module()
    backend = FakeBackend()

    result = anyio.run(
        partial(
            module.run_via_backend,
            backend,
            agent_id="coder",
            agent_code="",
            task="write something",
            permission_profile="workspace_write",
            client_request_id="request-1",
            title="",
            timeout_seconds=2,
        )
    )

    assert result["status"] == "awaiting_approval"
    assert result["taskId"] == "eat-1"
    assert result["pendingApprovals"] == [{"approvalId": "approval-1"}]
    assert backend.get_calls == 1
    assert "compatibilityWrapper" in result


def test_cli_parser_defaults_to_read_only_and_managed_mcp() -> None:
    module = _script_module()
    parser = module.build_parser()

    run_args = parser.parse_args(["run", "--agent-id", "coder", "--task", "hello"])
    mcp_args = parser.parse_args(["mcp", "--project-root", str(PROJECT_ROOT)])

    assert run_args.permission_profile == "read_only"
    assert mcp_args.project_root == PROJECT_ROOT
