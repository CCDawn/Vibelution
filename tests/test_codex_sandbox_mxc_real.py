"""Local-only real-binary MXC validation (skipped without wxc-exec.exe).

真实验证：本机 ``%LOCALAPPDATA%\\Vibelution\\sandbox\\wxc-exec.exe``（PoC
校验过的 1.0.1，SHA256
090f5d1f7bb93104ab08dcd4e8034ef954aeeefcdaf6658dde5f7dff4cfc12f3a）在位时
运行真实 probe/自验证/执行链路；二进制缺失或非 Windows 环境自动跳过，
CI 与无 MXC 机器不受影响。所有出站探测只指向宿主 loopback listener，
不依赖外部网络。
"""

from __future__ import annotations

import pytest

from core.infrastructure import codex_cli_sandbox
from core.infrastructure.codex_sandbox import mxc as mxc_backend
from core.web.services import agent_directory_service
from tools.shell_tools import workspace_root_override


def _real_executor_present() -> bool:
    return mxc_backend.executor_path() is not None


pytestmark = [
    pytest.mark.skipif(
        not _real_executor_present(),
        reason="local-only: %LOCALAPPDATA%\\Vibelution\\sandbox\\wxc-exec.exe 不存在",
    ),
]


@pytest.fixture
def real_mxc_enabled(monkeypatch, hermetic_mxc_sandbox):
    """Re-enable MXC for the real-binary validation (tests opt in explicitly)."""
    monkeypatch.delenv(mxc_backend.MXC_DISABLE_ENV, raising=False)
    mxc_backend.reset_verification_cache()
    yield
    mxc_backend.reset_verification_cache()


def _install_runtime(monkeypatch, *, permission_preset="request_approval", sandbox_mode="workspace_write"):
    runtime_permissions = {
        "preset": permission_preset,
        "sandboxMode": sandbox_mode,
        "approvalPolicy": "on_request",
        "approvalsReviewer": "user",
    }
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-real",
            "sessionId": "session-real",
            "turnId": "turn-real",
            "agentConfigSnapshot": {
                "agentId": "agent-real",
                "configRevision": 1,
                "configHash": "config-hash-real",
            },
            "permissionPreset": permission_preset,
            "runtimePermissions": runtime_permissions,
            "toolPolicy": {
                "policyId": "tool-agent-real",
                "allowedTools": ["exec_command", "cli_tool"],
                "preferredTools": [],
                "blockedTools": [],
                "maxCallsPerTurn": 20,
            },
        },
    )


def _make_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / ".git").write_text("gitdir: real\n", encoding="utf-8")
    return workspace


def test_real_probe_and_self_verify(real_mxc_enabled, monkeypatch, tmp_path):
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    availability = mxc_backend.ensure_verified(workspace)

    assert availability.ok is True, f"real self-verify failed: {availability.code} {availability.detail}"
    assert availability.tier in {mxc_backend.TIER_BASECONTAINER, mxc_backend.TIER_APPCONTAINER_DACL}
    assert availability.telemetry_policy in {"blocked", "allowed", "unset"}
    assert availability.detail.startswith("version=1.0.")


def test_real_execute_echo_via_mxc(real_mxc_enabled, monkeypatch, tmp_path):
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_runtime(monkeypatch)

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            "echo mxc-real-ok", cwd=str(workspace)
        )

    assert "SANDBOX_UNVERIFIED" not in result
    assert "mxc-real-ok" in result


def test_real_chinese_echo_relayed_via_file(real_mxc_enabled, monkeypatch, tmp_path):
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_runtime(monkeypatch)

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            "echo 中文真实OK", cwd=str(workspace)
        )

    assert "SANDBOX_UNVERIFIED" not in result
    assert "中文真实OK" in result, f"relay mojibake suspected: {result[:300]}"


def test_real_timeout_kills_executor_tree(real_mxc_enabled, monkeypatch, tmp_path):
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_runtime(monkeypatch)
    # cmd builtin loop: ICMP/console apps (ping/powershell/bash) are blocked or
    # win32k-gated in the sandbox, so the busy loop is the deterministic
    # long-runner here.
    loop_command = "for /l %i in (1,1,9000000) do @set /a x=%i"

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            loop_command, timeout=2, cwd=str(workspace)
        )

    assert "[超时]" in result


def test_real_bash_command_falls_back_to_fail_closed(real_mxc_enabled, monkeypatch, tmp_path):
    """git-bash 形态实测不可初始化 → 拒用并回退 SANDBOX_UNVERIFIED（无证据不执行）。"""
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_runtime(monkeypatch)

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            "grep -c pattern file.txt", cwd=str(workspace)
        )

    assert codex_cli_sandbox.SANDBOX_UNVERIFIED_BLOCK_CODE in result
