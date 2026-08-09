from __future__ import annotations

from pathlib import Path

import anyio


def _script_module():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "project_agent_tool.py"
    spec = importlib.util.spec_from_file_location("project_agent_tool_self_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HealthyBackend:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def diagnostics(self):
        return {
            "status": "healthy",
            "apiProtocolVersion": "1.0",
            "serverVersion": "0.3.1",
            "projectRoot": str(self.root.resolve()),
            "runtimeSourceRevision": "abc123",
            "enabled": True,
        }


def _project(tmp_path: Path, *, gateway_status: str) -> Path:
    (tmp_path / "docs" / "agents").mkdir(parents=True)
    (tmp_path / "docs" / "agents" / "mcp-managed-agent-gateway.md").write_text(
        "\n".join(
            [
                "# Guide",
                f"> **Gateway Status:** `{gateway_status}`",
                "> **Guide Version:** `0.3.3`",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (tmp_path / ".git" / "refs" / "heads" / "main").write_text(
        "abc123\n", encoding="utf-8"
    )
    return tmp_path


def test_self_check_reports_machine_readable_ready_contract(tmp_path) -> None:
    module = _script_module()
    root = _project(tmp_path, gateway_status="DEPLOYABLE")
    backend = HealthyBackend(root)

    result = anyio.run(
        module.build_self_check,
        root,
        backend,
        root / ".venv" / "Scripts" / "python.exe",
        "2.0.0",
    )

    assert result["status"] == "ready"
    assert result["deployable"] is True
    assert result["sourceRevision"] == "abc123"
    assert result["backend"] == "healthy"
    assert result["protocolEras"] == ["legacy", "modern"]
    assert result["tasksExtension"] == "not_available_in_mcp_sdk_2.0.0"
    assert len(result["tools"]) == 5


def test_self_check_fails_closed_when_guide_is_not_deployable(tmp_path) -> None:
    module = _script_module()
    root = _project(tmp_path, gateway_status="DEVELOPMENT_ONLY")

    result = anyio.run(
        module.build_self_check,
        root,
        HealthyBackend(root),
        root / ".venv" / "Scripts" / "python.exe",
        "2.0.0",
    )

    assert result["status"] == "not_ready"
    assert result["deployable"] is False
    assert "guide_status" in result["failedChecks"]


def test_self_check_fails_closed_when_backend_server_version_differs(tmp_path) -> None:
    module = _script_module()
    root = _project(tmp_path, gateway_status="DEPLOYABLE")
    backend = HealthyBackend(root)

    async def mismatched_diagnostics():
        payload = await HealthyBackend(root).diagnostics()
        payload["serverVersion"] = "0.2.0"
        return payload

    backend.diagnostics = mismatched_diagnostics
    result = anyio.run(
        module.build_self_check,
        root,
        backend,
        root / ".venv" / "Scripts" / "python.exe",
        "2.0.0",
    )

    assert result["deployable"] is False
    assert "server_version" in result["failedChecks"]


def test_parser_exposes_stable_self_check_json_entry() -> None:
    module = _script_module()
    args = module.build_parser().parse_args(
        ["self-check", "--project-root", "C:/repo", "--json"]
    )

    assert args.command == "self-check"
    assert args.json is True
