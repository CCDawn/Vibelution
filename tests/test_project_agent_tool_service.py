from __future__ import annotations

import importlib.util
import io
from functools import partial
from pathlib import Path
from types import SimpleNamespace

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
    heartbeat_seconds = 10.0

    def __init__(self) -> None:
        self.get_calls = 0

    async def heartbeat_once(self) -> None:
        return None

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


class CompletingFakeBackend(FakeBackend):
    heartbeat_seconds = 10.0

    def __init__(self) -> None:
        super().__init__()
        self.heartbeat_calls = 0

    async def heartbeat_once(self) -> None:
        self.heartbeat_calls += 1

    async def get_task(self, *, task_id: str):
        self.get_calls += 1
        assert task_id == "eat-1"
        return {
            "taskId": task_id,
            "status": "succeeded",
            "shouldPoll": False,
            "resultSummary": "done",
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


def test_run_wrapper_honors_caller_timeout_beyond_legacy_30_second_cap(
    monkeypatch,
) -> None:
    module = _script_module()
    backend = CompletingFakeBackend()
    monotonic_values = iter([0.0, 0.0, 31.0, 32.0])

    monkeypatch.setattr(
        module,
        "time",
        SimpleNamespace(monotonic=lambda: next(monotonic_values, 32.0)),
    )

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(module.anyio, "sleep", no_wait)

    result = anyio.run(
        partial(
            module.run_via_backend,
            backend,
            agent_id="coder",
            agent_code="",
            task="review a bounded change",
            permission_profile="read_only",
            client_request_id="request-longer-than-legacy-cap",
            title="",
            timeout_seconds=60,
        )
    )

    assert result["status"] == "succeeded"
    assert result["resultSummary"] == "done"
    assert backend.get_calls == 1
    assert backend.heartbeat_calls == 1


def test_cli_parser_defaults_to_read_only_and_managed_mcp() -> None:
    module = _script_module()
    parser = module.build_parser()

    run_args = parser.parse_args(["run", "--agent-id", "coder", "--task", "hello"])
    custom_wait_args = parser.parse_args(
        [
            "run",
            "--agent-id",
            "coder",
            "--task",
            "hello",
            "--timeout-seconds",
            "60",
        ]
    )
    mcp_args = parser.parse_args(["mcp", "--project-root", str(PROJECT_ROOT)])

    assert run_args.permission_profile == "read_only"
    assert run_args.timeout_seconds == 10.0
    assert custom_wait_args.timeout_seconds == 60.0
    assert mcp_args.project_root == PROJECT_ROOT


def test_cli_preserves_agent_result_json_on_legacy_windows_stdout(
    monkeypatch,
) -> None:
    module = _script_module()
    output = io.BytesIO()
    legacy_stdout = io.TextIOWrapper(output, encoding="gbk")
    warning = chr(0x26A0)
    monkeypatch.setattr(module.sys, "stdout", legacy_stdout)

    module._print({"resultSummary": f"{warning} review complete"})
    legacy_stdout.flush()

    rendered = output.getvalue().decode("gbk")
    assert "\\u26a0 review complete" in rendered
    assert module.json.loads(rendered)["resultSummary"] == f"{warning} review complete"
