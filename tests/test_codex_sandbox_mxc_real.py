"""Local-only real-binary MXC validation (skipped without wxc-exec.exe).

真实验证：本机 ``%LOCALAPPDATA%\\Vibelution\\sandbox\\wxc-exec.exe``（PoC
校验过的 1.0.1，SHA256
090f5d1f7bb93104ab08dcd4e8034ef954aeefcdaf6658dde5f7dff4cfc12f3a）在位时
运行真实 probe/自验证/执行链路；二进制缺失或非 Windows 环境自动跳过，
CI 与无 MXC 机器不受影响。所有出站探测只指向宿主 loopback listener 与
本地假上游，不依赖外部网络。
"""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.infrastructure import codex_cli_sandbox
from core.infrastructure.codex_sandbox import loopback_relay, mxc as mxc_backend
from core.web.services import agent_directory_service
from tools.shell_tools import workspace_root_override

EXECUTOR_SHA256_PIN = (
    "090f5d1f7bb93104ab08dcd4e8034ef954aeefcdaf6658dde5f7dff4cfc12f3a"
)


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


class _FakeOnlineUpstreamHandler(BaseHTTPRequestHandler):
    """Deterministic local fake upstream served over plain HTTP."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - stdlib API
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/ok":
            body = b"fake-upstream-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b"not-found"
        self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FakeOnlineUpstream:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOnlineUpstreamHandler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def online_relay(monkeypatch, hermetic_mxc_sandbox):
    """Fresh loopback relay + local fake upstream for real online-tier runs.

    连接设置（明文上游 + connect override）只在单例首启生效，因此先
    stop_relay() 保证本套件的 relay 配置确定；套件结束时一并清理。
    """
    loopback_relay.stop_relay()
    upstream = _FakeOnlineUpstream()
    upstream.start()
    handle = loopback_relay.get_or_start_relay(
        {"fakeapi": "fakeupstream.test"},
        upstream_tls=False,
        connect_overrides={"fakeupstream.test": ("127.0.0.1", upstream.port)},
    )
    yield handle
    loopback_relay.stop_relay()
    upstream.stop()


def _ensure_online_available(tmp_path) -> "mxc_backend.MxcAvailability":
    """Online verdict with skip-on-incompatible-host semantics (TTL-cached)."""
    availability = mxc_backend.ensure_verified(
        tmp_path, network_profile=mxc_backend.NETWORK_PROFILE_LOOPBACK_RELAY
    )
    if not availability.ok:
        pytest.skip(
            f"online tier unavailable on this host: "
            f"{availability.code} {availability.detail}"
        )
    assert availability.network_profile == mxc_backend.NETWORK_PROFILE_LOOPBACK_RELAY
    assert availability.tier == mxc_backend.TIER_BASECONTAINER
    return availability


def _install_online_runtime(monkeypatch):
    _install_runtime(monkeypatch, sandbox_mode="workspace_write_online")


def _sandbox_curl() -> str:
    """Absolute curl path: direct-executable argv shape inside the sandbox.

    cmd->curl 子进程形态在本机 MXC UI 隔离下实测 0xC0000142（offline 档同
    样复现，既有边界，与本任务无关）；只有 executor 直接 spawn 的 curl.exe
    （绝对路径直连 argv 形态）能初始化，因此 curl 用例统一走该形态。
    """
    import os

    curl = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "curl.exe"
    assert curl.is_file(), f"curl.exe missing at {curl}"
    return str(curl)


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


# ---------------------------------------------------------------- online tier (real)


def test_real_online_self_verify(online_relay, real_mxc_enabled, monkeypatch, tmp_path):
    """真实 wxc-exec 在线档验证：basecontainer 档 + 回环探测 + 非回环出站必拒。"""
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    availability = _ensure_online_available(tmp_path)

    assert availability.relay_port == online_relay.port
    assert availability.detail.startswith("version=1.0.")


def test_real_online_curl_relay_probe_from_sandbox(
    online_relay, real_mxc_enabled, monkeypatch, tmp_path
):
    """沙盒内 curl 回环中继 probe 必须拿到 200 "ok"（ingress hostLoopback allow 生效）。"""
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_online_runtime(monkeypatch)
    _ensure_online_available(tmp_path)

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            f"{_sandbox_curl()} -s http://127.0.0.1:{online_relay.port}/__relay_probe",
            timeout=30,
            cwd=str(workspace),
        )

    assert "SANDBOX_UNVERIFIED" not in result
    assert result.strip().endswith("ok"), f"relay probe output unexpected: {result[:300]}"


def test_real_online_route_through_relay_to_fake_upstream(
    online_relay, real_mxc_enabled, monkeypatch, tmp_path
):
    """端到端：沙盒 curl → 回环中继 → 宿主假上游，返回上游响应体。"""
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_online_runtime(monkeypatch)
    _ensure_online_available(tmp_path)

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            f"{_sandbox_curl()} -s http://127.0.0.1:{online_relay.port}/fakeapi/ok",
            timeout=30,
            cwd=str(workspace),
        )

    assert "SANDBOX_UNVERIFIED" not in result
    assert "fake-upstream-ok" in result, f"upstream route output unexpected: {result[:300]}"


def test_real_online_nonloopback_egress_denied(
    online_relay, real_mxc_enabled, monkeypatch, tmp_path
):
    """在线档下非回环出站仍被 egress deny 拒绝（curl 非零退出）。"""
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_online_runtime(monkeypatch)
    _ensure_online_available(tmp_path)

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            f"{_sandbox_curl()} -s -o NUL --connect-timeout 2 --max-time 6 http://93.184.216.34/",
            timeout=30,
            cwd=str(workspace),
        )

    assert "SANDBOX_UNVERIFIED" not in result
    assert re.search(r"Exit Code: [1-9]", result), (
        f"non-loopback egress unexpectedly succeeded: {result[:300]}"
    )


def test_real_online_deniedpaths_git_write_refused(
    online_relay, real_mxc_enabled, monkeypatch, tmp_path
):
    """basecontainer 在线档同样强制 deniedPaths：.git 越权写被拒且零落盘。

    `.git` 以目录形态存在（含 HEAD），确保写失败是策略拒绝而不是路径不存在。
    """
    workspace = _make_workspace(tmp_path)
    # Replace the .git root marker file with a real directory so the policy
    # denial (not "path not found") is what refuses the write.
    (workspace / ".git").unlink()
    git_dir = workspace / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    _install_online_runtime(monkeypatch)
    _ensure_online_available(tmp_path)
    probe_file = git_dir / "mxc-online-probe.txt"

    with workspace_root_override(workspace):
        result = codex_cli_sandbox.execute_codex_sandbox_command(
            'cmd /d /s /c "echo blocked> .git\\mxc-online-probe.txt"',
            timeout=30,
            cwd=str(workspace),
        )

    assert not probe_file.exists(), "deniedPaths must keep the .git write off disk"
    assert re.search(r"Exit Code: [1-9]", result) or "拒绝访问" in result or "denied" in result.lower(), (
        f".git write unexpectedly succeeded: {result[:300]}"
    )


def test_real_online_degraded_tier_would_refuse(
    online_relay, real_mxc_enabled, monkeypatch, tmp_path
):
    """降级档请求在线档 → 明确拒绝 reason，不降级不静默（cache-key 隔离验证）。"""
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    availability = mxc_backend.ensure_verified(workspace)

    if availability.tier != mxc_backend.TIER_BASECONTAINER:
        online = mxc_backend.ensure_verified(
            workspace, network_profile=mxc_backend.NETWORK_PROFILE_LOOPBACK_RELAY
        )
        assert online.ok is False
        assert online.code == "online_profile_requires_basecontainer"
    else:
        # Host is basecontainer (expected on 26200.9711): the degraded-tier
        # refusal branch is covered by the unit suite; nothing to prove here.
        pytest.skip("host is basecontainer; degraded-tier refusal covered by unit tests")
