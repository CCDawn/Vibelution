"""MXC sandbox backend tests: injectable fake executor, no real binary/network.

覆盖面（对应 PoC 事实与任务验收矩阵）：
- 自验证成功 / 失败（workspace 写缺失、出站到达）/ TTL 过期重验。
- 版本锁：非 1.0.x 拒用；二进制缺失拒用。
- 两态策略 JSON：workspace+TEMP readwrite、egress/ingress deny、
  inheritDefaultEnv=false、env 显式含 SYSTEMROOT；降级档不配 deniedPaths、
  PSEC 档配置 workspace/.git deniedPaths。
- 回退因码：mxc_probe_failed / mxc_verify_failed / mxc_spawn_failed /
  mxc_non_ascii_argv，全部回退 SANDBOX_UNVERIFIED fail-closed。
- 中文命令参数走文件传递（cmd/powershell relay，argv 保持 ASCII）。
- 超时/取消杀树；内容门（危险命令/路由拦截/cwd 边界）先于沙箱选择。
- auto_review 审批前提矩阵：MXC 验证通过恢复静默自动批；不可用维持弹卡。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.infrastructure import codex_cli_sandbox
from core.infrastructure.codex_sandbox import mxc as mxc_backend
from core.web.services import agent_directory_service
from core.web.services.session import execution_evidence, tool_approvals


class _CompletedProcess:
    pid = 4242
    returncode = 0

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        return "sandbox ok\n", ""


def _install_runtime(
    monkeypatch,
    *,
    session_id="session-a",
    turn_id="turn-a",
    permission_preset="request_approval",
    sandbox_mode="workspace_write",
):
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
            "agentId": "agent-a",
            "sessionId": session_id,
            "turnId": turn_id,
            "agentConfigSnapshot": {
                "agentId": "agent-a",
                "configRevision": 3,
                "configHash": "config-hash-a",
            },
            "permissionPreset": permission_preset,
            "runtimePermissions": runtime_permissions,
            "toolPolicy": {
                "policyId": "tool-agent-a",
                "allowedTools": ["exec_command", "cli_tool"],
                "preferredTools": [],
                "blockedTools": [],
                "maxCallsPerTurn": 20,
            },
        },
    )


def _make_fake_binary(monkeypatch, tmp_path) -> str:
    """Point LOCALAPPDATA at a fake executor file (contents never executed)."""
    local_app_data = tmp_path / "localappdata"
    executor = local_app_data / "Vibelution" / "sandbox" / "wxc-exec.exe"
    executor.parent.mkdir(parents=True)
    executor.write_bytes(b"fake-executor")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return str(executor)


def _install_fake_availability(
    monkeypatch,
    *,
    ok=True,
    code="",
    tier="appcontainer-dacl",
    telemetry_policy="unset",
    version="1.0.1",
):
    """Fake the version/telemetry/probe/verify pipeline at the seams."""

    def fake_version(_path):
        return version

    monkeypatch.setattr(mxc_backend, "executor_version_string", fake_version)
    monkeypatch.setattr(mxc_backend, "read_telemetry_policy", lambda: telemetry_policy)
    return fake_version


class _FakeExecutor:
    """Simulates wxc-exec.exe semantics at the ``_run_executor`` seam."""

    def __init__(
        self,
        *,
        probe_tier="appcontainer-dacl",
        probe_ok=True,
        write_marker=True,
        egress_arrives=False,
        curl_rc=28,
        version="1.0.1",
        telemetry_policy="unset",
    ):
        self.probe_tier = probe_tier
        self.probe_ok = probe_ok
        self.write_marker = write_marker
        self.egress_arrives = egress_arrives
        self.curl_rc = curl_rc
        self.version = version
        self.telemetry_policy = telemetry_policy
        self.calls: list[list[str]] = []
        self.probes = 0

    def __call__(self, argv, *, timeout_s):
        self.calls.append(list(argv))
        if "--probe" in argv:
            self.probes += 1
            payload = (
                json.dumps({"tier": self.probe_tier}).encode("utf-8")
                if self.probe_ok
                else b"not-json"
            )
            return subprocess.CompletedProcess(argv, 0, payload, b"")
        # Exec run: policy path is argv[1]; inner command after "--".
        policy = json.loads(Path(argv[1]).read_text(encoding="ascii"))
        inner = argv[argv.index("--") + 1 :]
        joined = " ".join(str(item) for item in inner)
        cwd = Path(policy["process"]["cwd"])
        if "curl" in joined and self.egress_arrives:
            return subprocess.CompletedProcess(argv, 0, b"arrived", b"")
        if "curl" in joined:
            return subprocess.CompletedProcess(argv, self.curl_rc, b"", b"")
        if mxc_backend.VERIFY_MARKER_FILENAME in joined and self.write_marker:
            (cwd / mxc_backend.VERIFY_MARKER_FILENAME).write_text(
                "verify-ok", encoding="utf-8"
            )
        return subprocess.CompletedProcess(argv, 0, b"", b"")


@pytest.fixture
def fake_executor(monkeypatch, tmp_path, hermetic_mxc_sandbox):
    """Wire a fake executor into the availability pipeline (and enable MXC)."""

    def _factory(**kwargs):
        _make_fake_binary(monkeypatch, tmp_path)
        monkeypatch.delenv(mxc_backend.MXC_DISABLE_ENV, raising=False)
        executor = _FakeExecutor(**kwargs)
        monkeypatch.setattr(mxc_backend, "executor_version_string", lambda _p: executor.version)
        monkeypatch.setattr(
            mxc_backend, "read_telemetry_policy", lambda: executor.telemetry_policy
        )
        monkeypatch.setattr(mxc_backend, "_run_executor", executor)
        mxc_backend.reset_verification_cache()
        return executor

    return _factory


# ---------------------------------------------------------------- availability


def test_ensure_verified_success_degraded_tier(fake_executor, tmp_path):
    executor = fake_executor()
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is True
    assert availability.tier == "appcontainer-dacl"
    assert availability.code == ""
    assert availability.from_cache is False
    assert executor.probes == 1


def test_ensure_verified_ttl_cache_and_expiry(fake_executor, tmp_path, monkeypatch):
    executor = fake_executor()
    clock = {"now": 1000.0}
    monkeypatch.setattr(mxc_backend.time, "monotonic", lambda: clock["now"])

    first = mxc_backend.ensure_verified(tmp_path)
    assert first.ok is True
    second = mxc_backend.ensure_verified(tmp_path)
    assert second.from_cache is True
    assert executor.probes == 1

    clock["now"] += mxc_backend.VERIFY_TTL_SUCCESS_SECONDS + 1
    third = mxc_backend.ensure_verified(tmp_path)
    assert third.from_cache is False
    assert third.ok is True
    assert executor.probes == 2


def test_ensure_verified_failure_ttl_shorter(fake_executor, tmp_path, monkeypatch):
    executor = fake_executor(probe_ok=False)
    clock = {"now": 1000.0}
    monkeypatch.setattr(mxc_backend.time, "monotonic", lambda: clock["now"])

    first = mxc_backend.ensure_verified(tmp_path)
    assert first.ok is False
    assert first.code == mxc_backend.REASON_PROBE_FAILED
    second = mxc_backend.ensure_verified(tmp_path)
    assert second.from_cache is True
    clock["now"] += mxc_backend.VERIFY_TTL_FAILURE_SECONDS + 1
    third = mxc_backend.ensure_verified(tmp_path)
    assert third.from_cache is False
    assert executor.probes == 2


def test_verify_fails_when_workspace_marker_missing(fake_executor, tmp_path):
    fake_executor(write_marker=False)
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is False
    assert availability.code == mxc_backend.REASON_VERIFY_FAILED
    assert "marker_missing" in availability.detail


def test_verify_fails_when_egress_request_succeeds(fake_executor, tmp_path):
    """A successful sandbox-side request proves egress deny is broken."""
    fake_executor(egress_arrives=True)
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is False
    assert availability.code == mxc_backend.REASON_VERIFY_FAILED
    assert availability.detail == "verify_egress_request_succeeded"


def test_verify_fails_when_curl_absent(fake_executor, tmp_path):
    fake_executor(curl_rc=9009)
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is False
    assert availability.code == mxc_backend.REASON_VERIFY_FAILED
    assert availability.detail.startswith("verify_curl_missing")


def test_version_lock_refuses_non_1_0_x(fake_executor, tmp_path):
    fake_executor(version="1.1.0")
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is False
    assert availability.code == mxc_backend.REASON_VERSION_UNSUPPORTED


def test_missing_binary_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    mxc_backend.reset_verification_cache()
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is False
    assert availability.code == mxc_backend.REASON_UNAVAILABLE


def test_unknown_probe_tier_refused(fake_executor, tmp_path):
    fake_executor(probe_tier="windows-sandbox")
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is False
    assert availability.code == mxc_backend.REASON_PROBE_FAILED
    assert availability.detail.startswith("probe_tier_unknown")


def test_telemetry_policy_observed_not_gating(fake_executor, tmp_path):
    fake_executor(telemetry_policy="blocked")
    availability = mxc_backend.ensure_verified(tmp_path)
    assert availability.ok is True
    assert availability.telemetry_policy == "blocked"


# ---------------------------------------------------------------- policy shape


def _cmd_route(command: str) -> SimpleNamespace:
    return SimpleNamespace(
        route="cmd",
        final_command=f"cmd /c {command}",
        reason="windows_default_cmd",
        command=command,
        error="",
    )


def test_two_state_policy_json_degraded_has_no_deniedpaths(tmp_path):
    workdir = tmp_path / "ws"
    workdir.mkdir()
    child_temp = workdir / ".tmp" / "mxc" / "run-1"
    child_temp.mkdir(parents=True)
    plan = mxc_backend.build_command_plan(
        Path("wxc-exec.exe"),
        _cmd_route("echo hi"),
        workdir=workdir,
        child_temp=child_temp,
        timeout_ms=65000,
        tier=mxc_backend.TIER_APPCONTAINER_DACL,
        base_environment={"PATH": r"C:\Windows", "SYSTEMROOT": r"C:\Windows"},
    )
    assert plan is not None
    policy = json.loads(plan.policy_path.read_text(encoding="ascii"))
    assert policy["version"] == "1.0.0"
    assert policy["containment"] == "processcontainer"
    assert policy["lifecycle"] == {"destroyOnExit": True}
    assert policy["filesystem"]["readwritePaths"] == [str(workdir), str(child_temp)]
    assert "deniedPaths" not in policy["filesystem"]
    assert policy["network"]["egress"] == {"default": "deny"}
    assert policy["network"]["ingress"] == {"default": "deny", "hostLoopback": "deny"}
    assert policy["process"]["cwd"] == str(workdir)
    assert policy["process"]["timeout"] == 65000
    assert policy["process"]["inheritDefaultEnv"] is False
    env_pairs = dict(item.split("=", 1) for item in policy["process"]["env"])
    assert env_pairs["SYSTEMROOT"] == r"C:\Windows"
    assert env_pairs["TEMP"] == str(child_temp)
    assert env_pairs["PYTHONDONTWRITEBYTECODE"] == "1"
    assert plan.spawn_argv[0] == "wxc-exec.exe"
    inner_tail = [str(item) for item in plan.spawn_argv[plan.spawn_argv.index("--") + 1 :]]
    assert inner_tail[0].endswith("cmd.exe")
    assert inner_tail[1:4] == ["/d", "/s", "/c"]
    assert inner_tail[4] == "echo hi"


def test_psec_tier_policy_includes_git_deniedpaths(tmp_path):
    workdir = tmp_path / "ws"
    workdir.mkdir()
    child_temp = workdir / ".tmp" / "mxc" / "run-2"
    child_temp.mkdir(parents=True)
    plan = mxc_backend.build_command_plan(
        Path("wxc-exec.exe"),
        _cmd_route("echo hi"),
        workdir=workdir,
        child_temp=child_temp,
        timeout_ms=65000,
        tier=mxc_backend.TIER_BASECONTAINER,
        base_environment={"PATH": r"C:\Windows"},
    )
    policy = json.loads(plan.policy_path.read_text(encoding="ascii"))
    assert policy["filesystem"]["deniedPaths"] == [str(workdir / ".git")]


def test_spawn_argv_must_stay_ascii(tmp_path):
    """Non-ASCII commands relay through a file; argv itself stays ASCII."""
    workdir = tmp_path / "ws"
    workdir.mkdir()
    child_temp = workdir / ".tmp" / "mxc" / "run-3"
    child_temp.mkdir(parents=True)
    plan = mxc_backend.build_command_plan(
        Path("wxc-exec.exe"),
        _cmd_route("echo 中文内容OK"),
        workdir=workdir,
        child_temp=child_temp,
        timeout_ms=65000,
        tier=mxc_backend.TIER_APPCONTAINER_DACL,
        base_environment={"PATH": r"C:\Windows"},
    )
    assert plan is not None
    assert plan.relay_path is not None
    assert all(str(item).isascii() for item in plan.spawn_argv)
    relay_text = plan.relay_path.read_text(encoding="utf-8")
    assert relay_text.startswith("@echo off")
    assert "@chcp 65001" in relay_text
    assert "中文内容OK" in relay_text
    inner_tail = plan.spawn_argv[plan.spawn_argv.index("--") + 1 :]
    assert inner_tail[-1] == str(plan.relay_path)


def test_powershell_relay_uses_utf8_bom(tmp_path):
    workdir = tmp_path / "ws"
    workdir.mkdir()
    child_temp = workdir / ".tmp" / "mxc" / "run-4"
    child_temp.mkdir(parents=True)
    route = SimpleNamespace(
        route="powershell",
        final_command="powershell -Command Write-Output 中文",
        reason="powershell_cmdlet",
        command="Write-Output 中文",
        error="",
    )
    plan = mxc_backend.build_command_plan(
        Path("wxc-exec.exe"),
        route,
        workdir=workdir,
        child_temp=child_temp,
        timeout_ms=65000,
        tier=mxc_backend.TIER_APPCONTAINER_DACL,
        base_environment={"PATH": r"C:\Windows"},
    )
    assert plan is not None and plan.relay_path is not None
    assert plan.relay_path.read_text(encoding="utf-8-sig") == "Write-Output 中文"
    inner_tail = plan.spawn_argv[plan.spawn_argv.index("--") + 1 :]
    assert "-File" in inner_tail
    assert inner_tail[-1] == str(plan.relay_path)


# ---------------------------------------------------------------- gate + events


@pytest.fixture
def mxc_event_capture(monkeypatch):
    events: list[dict] = []

    def _capture(event_code, **fields):
        events.append({"event": event_code, **fields})

    monkeypatch.setattr(codex_cli_sandbox, "record_tool_process_event", _capture)
    return events


@pytest.fixture
def windows_gate(monkeypatch, tmp_path):
    """Windows host + fake Popen; MXC availability comes from fake_executor."""
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    spawn_record: dict = {}

    def fake_popen(argv, **kwargs):
        spawn_record["argv"] = argv
        spawn_record["kwargs"] = kwargs
        # Capture transient artifacts at spawn time (child temp is cleaned up
        # after the run, by design).
        text_argv = [str(item) for item in argv]
        if "--" in text_argv:
            policy_path = Path(text_argv[1])
            if policy_path.is_file():
                try:
                    spawn_record["policy"] = json.loads(
                        policy_path.read_text(encoding="ascii")
                    )
                except Exception:
                    pass
            for item in text_argv[text_argv.index("--") + 1 :]:
                candidate = Path(item)
                if candidate.suffix.lower() in {".cmd", ".ps1", ".sh"} and candidate.is_file():
                    spawn_record["relayText"] = candidate.read_text(encoding="utf-8", errors="replace")
        return _CompletedProcess()

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", fake_popen)
    return spawn_record


def _expect_mxc_verified(
    monkeypatch, tier="appcontainer-dacl", code="", ok=True, detail="", from_cache=False
):
    def _fake_ensure(workdir=None, **kwargs):
        return mxc_backend.MxcAvailability(
            ok=ok,
            code=code,
            detail=detail,
            tier=tier,
            telemetry_policy="unset",
            from_cache=from_cache,
        )

    monkeypatch.setattr(mxc_backend, "ensure_verified", _fake_ensure)
    monkeypatch.setattr(mxc_backend, "executor_path", lambda: "wxc-exec.exe")


def test_workspace_write_routes_through_mxc(
    monkeypatch, tmp_path, windows_gate, mxc_event_capture, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        "echo hi", cwd=str(workdir)
    )

    assert "sandbox ok" in result
    argv = windows_gate["argv"]
    assert str(argv[0]).endswith("wxc-exec.exe")
    assert "--" in argv
    started_events = [
        event for event in mxc_event_capture if event["event"] == "tool.execution.process_started"
    ]
    assert started_events and started_events[0]["route"].startswith("mxc:")


def test_mxc_policy_json_via_gate_is_two_state(
    monkeypatch, tmp_path, windows_gate, fake_executor
):
    executor = fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    workdir = tmp_path / "ws"
    workdir.mkdir()

    codex_cli_sandbox.execute_codex_sandbox_command("echo hi", cwd=str(workdir))

    policy = windows_gate["policy"]
    assert policy["network"]["egress"] == {"default": "deny"}
    assert policy["filesystem"]["readwritePaths"][0] == str(workdir.resolve())
    assert "deniedPaths" not in policy["filesystem"]
    assert policy["process"]["inheritDefaultEnv"] is False


def test_chinese_command_relayed_via_file_through_gate(
    monkeypatch, tmp_path, windows_gate, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        "echo 中文输出OK", cwd=str(workdir)
    )

    assert "sandbox ok" in result
    argv = windows_gate["argv"]
    assert all(str(item).isascii() for item in argv)
    inner_tail = [str(item) for item in argv[argv.index("--") + 1 :]]
    # `echo …` classifies as a Linux command on Windows but is a native
    # builtin, so the adapter inlines a cmd.exe payload → the relay uses the
    # UTF-8 .cmd carrier (chcp 65001). Pure bash shapes are refused entirely
    # (see test_bash_inner_command_refused).
    assert inner_tail[-1].endswith("mxc-relay.cmd")
    relay_text = windows_gate["relayText"]
    assert "中文输出OK" in relay_text
    assert "@chcp 65001" in relay_text


def test_bash_inner_command_refused(monkeypatch, tmp_path):
    """git-bash shapes are refused: measured STATUS_DLL_INIT_FAILED under MXC."""
    workdir = tmp_path / "ws"
    workdir.mkdir()
    child_temp = workdir / ".tmp" / "mxc" / "run-5"
    child_temp.mkdir(parents=True)
    route = SimpleNamespace(
        route="git_bash",
        final_command="bash -c 'grep -c pattern file.txt'",
        reason="linux_command_on_windows",
        command="grep -c pattern file.txt",
        error="",
    )
    with pytest.raises(mxc_backend.MxcPlanRefused) as exc_info:
        mxc_backend.build_command_plan(
            Path("wxc-exec.exe"),
            route,
            workdir=workdir,
            child_temp=child_temp,
            timeout_ms=65000,
            tier=mxc_backend.TIER_APPCONTAINER_DACL,
            base_environment={"PATH": r"C:\Windows"},
            git_bash_executable=str(tmp_path / "bash.exe"),
        )
    assert exc_info.value.code == "mxc_bash_unavailable"


def test_fallback_probe_failed_records_event_and_stays_fail_closed(
    monkeypatch, tmp_path, windows_gate, mxc_event_capture, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(
        monkeypatch, ok=False, code=mxc_backend.REASON_PROBE_FAILED, detail="probe_output_unparsable"
    )
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        "echo hi", cwd=str(workdir)
    )

    assert codex_cli_sandbox.SANDBOX_UNVERIFIED_BLOCK_CODE in result
    mxc_events = [
        event for event in mxc_event_capture if event["event"] == "tool.execution.mxc_backend"
    ]
    assert any(event.get("code") == "mxc_probe_failed" for event in mxc_events)
    # Pre-MXC chain spawn never ran (no evidence).
    assert "argv" not in windows_gate


def test_fallback_verify_failed_records_event(monkeypatch, tmp_path, windows_gate, mxc_event_capture, fake_executor):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(
        monkeypatch, ok=False, code=mxc_backend.REASON_VERIFY_FAILED, detail="verify_egress_not_denied"
    )
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command("echo hi", cwd=str(workdir))

    assert codex_cli_sandbox.SANDBOX_UNVERIFIED_BLOCK_CODE in result
    mxc_events = [
        event for event in mxc_event_capture if event["event"] == "tool.execution.mxc_backend"
    ]
    assert any(event.get("code") == "mxc_verify_failed" for event in mxc_events)


def test_fallback_spawn_failed_records_event_and_falls_through(
    monkeypatch, tmp_path, windows_gate, mxc_event_capture, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)

    def _explode(plan, **kwargs):
        raise FileNotFoundError("wxc-exec vanished")

    monkeypatch.setattr(codex_cli_sandbox, "_mxc_spawn_process", _explode)
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command("echo hi", cwd=str(workdir))

    assert codex_cli_sandbox.SANDBOX_UNVERIFIED_BLOCK_CODE in result
    mxc_events = [
        event for event in mxc_event_capture if event["event"] == "tool.execution.mxc_backend"
    ]
    assert any(event.get("code") == "mxc_spawn_failed" for event in mxc_events)


def test_fallback_non_ascii_git_argv_records_event(
    monkeypatch, tmp_path, windows_gate, mxc_event_capture, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        "git commit -m 中文说明", cwd=str(workdir)
    )

    assert codex_cli_sandbox.SANDBOX_UNVERIFIED_BLOCK_CODE in result
    mxc_events = [
        event for event in mxc_event_capture if event["event"] == "tool.execution.mxc_backend"
    ]
    assert any(event.get("code") == "mxc_non_ascii_argv" for event in mxc_events)


def test_fallback_bash_command_records_event(
    monkeypatch, tmp_path, windows_gate, mxc_event_capture, fake_executor
):
    """git-bash 形态在 MXC 实测不可初始化 → 拒用并回退证据链（fail-closed）。"""
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )
    monkeypatch.setattr(codex_cli_sandbox, "_mxc_git_bash_for_route", lambda route: "bash.exe")
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        "grep -c pattern file.txt", cwd=str(workdir)
    )

    assert codex_cli_sandbox.SANDBOX_UNVERIFIED_BLOCK_CODE in result
    mxc_events = [
        event for event in mxc_event_capture if event["event"] == "tool.execution.mxc_backend"
    ]
    assert any(event.get("code") == "mxc_bash_unavailable" for event in mxc_events)


def test_content_gates_run_before_mxc_selection(
    monkeypatch, tmp_path, windows_gate, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")

    def _forbidden(workdir=None, **kwargs):
        raise AssertionError("MXC availability must not be consulted before content gates")

    monkeypatch.setattr(mxc_backend, "ensure_verified", _forbidden)
    from tools.shell_tools import workspace_root_override

    agent_workspace = tmp_path / "agent-workspace"
    agent_workspace.mkdir()
    (agent_workspace / ".git").write_text("gitdir: test\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    workdir = agent_workspace

    with workspace_root_override(agent_workspace):
        dangerous = codex_cli_sandbox.execute_codex_sandbox_command(
            "rm -rf something", cwd=str(workdir)
        )
        assert "安全拦截" in dangerous
        assert "argv" not in windows_gate

        outside_result = codex_cli_sandbox.execute_codex_sandbox_command(
            "echo hi", cwd=str(outside)
        )
        assert "CWD_OUTSIDE_SANDBOX" in outside_result or "安全拦截" in outside_result
        assert "argv" not in windows_gate


def test_mxc_timeout_terminates_process_tree(
    monkeypatch, tmp_path, windows_gate, fake_executor, mxc_event_capture
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    workdir = tmp_path / "ws"
    workdir.mkdir()
    terminated: list[int] = []

    class _HangingProcess:
        pid = 5150
        returncode = None

        def poll(self):
            return None

        def communicate(self, timeout=None):
            import time as _time

            _time.sleep(0.05)
            raise subprocess.TimeoutExpired(cmd="mxc", timeout=timeout)

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", lambda argv, **kw: _HangingProcess())
    monkeypatch.setattr(
        codex_cli_sandbox, "_terminate_process_tree", lambda process: terminated.append(process.pid)
    )

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        "ping -n 30 127.0.0.1", timeout=1, cwd=str(workdir)
    )

    assert "[超时]" in result
    assert terminated == [5150]


def test_mxc_cancel_terminates_process_tree(
    monkeypatch, tmp_path, windows_gate, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    workdir = tmp_path / "ws"
    workdir.mkdir()
    terminated: list[int] = []

    class _HangingProcess(_CompletedProcess):
        pid = 6160

        def poll(self):
            return None

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="mxc", timeout=timeout)

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", lambda argv, **kw: _HangingProcess())
    monkeypatch.setattr(
        codex_cli_sandbox, "_terminate_process_tree", lambda process: terminated.append(process.pid)
    )

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        "ping -n 30 127.0.0.1", timeout=30, cwd=str(workdir), _cancel_checker=lambda: "user stop"
    )

    assert "[取消]" in result
    assert terminated == [6160]


def test_mxc_terminal_session_runs_and_cleans_child_temp(
    monkeypatch, tmp_path, windows_gate, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    workdir = tmp_path / "ws"
    workdir.mkdir()
    cleaned: list[Path] = []
    monkeypatch.setattr(
        mxc_backend,
        "cleanup_child_temp",
        lambda child_temp, **kwargs: cleaned.append(Path(child_temp)),
    )

    result = codex_cli_sandbox.start_codex_sandbox_terminal_session(
        "echo hi", cwd=str(workdir)
    )

    assert result["status"] == "completed"
    assert result["exitCode"] == 0
    assert windows_gate["kwargs"].get("stdin") == subprocess.PIPE
    assert cleaned, "child temp cleanup must run after session outcome"


# ---------------------------------------------------------------- approvals


def test_auto_review_silent_auto_approval_restored_when_mxc_verified(
    monkeypatch, tmp_path, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="auto_review")
    _expect_mxc_verified(monkeypatch)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    assert (
        tool_approvals._sandbox_containment_unverified_for_current_runtime() is False
    )
    assert (
        tool_approvals._can_auto_approve(
            permission_preset="auto_review",
            tool_name="cli_tool",
            tool_args={"cmd": "git status"},
            approval="",
            risk="",
        )
        is True
    )


def test_auto_review_still_prompts_when_mxc_unavailable(
    monkeypatch, tmp_path, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="auto_review")
    _expect_mxc_verified(
        monkeypatch, ok=False, code=mxc_backend.REASON_UNAVAILABLE, detail="executor_binary_missing"
    )
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    assert (
        tool_approvals._sandbox_containment_unverified_for_current_runtime() is True
    )
    assert (
        tool_approvals._can_auto_approve(
            permission_preset="auto_review",
            tool_name="cli_tool",
            tool_args={"cmd": "git status"},
            approval="",
            risk="",
        )
        is False
    )


def test_read_only_mode_keeps_fail_closed_even_when_mxc_verified(
    monkeypatch, tmp_path, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="auto_review", sandbox_mode="read_only")
    _expect_mxc_verified(monkeypatch)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    assert codex_cli_sandbox.windows_offline_shell_unverified() is True


def test_workspace_write_gate_passes_when_mxc_verified(
    monkeypatch, tmp_path, fake_executor
):
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="auto_review")
    _expect_mxc_verified(monkeypatch)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    assert codex_cli_sandbox.windows_offline_shell_unverified() is False


def test_request_approval_mint_skipped_when_mxc_verified(
    monkeypatch, tmp_path, fake_executor
):
    """MXC verified: no one-shot evidence is minted (the sandbox is the boundary)."""
    fake_executor()
    _install_runtime(monkeypatch, permission_preset="request_approval")
    _expect_mxc_verified(monkeypatch)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    execution_evidence.reset_execution_evidence_state()

    tool_approvals._mint_command_execution_evidence(
        session_id="session-a",
        turn_id="turn-a",
        call_id="call-a",
        tool_name="cli_tool",
        command_execution_hash="hash-a",
    )
    from core.web.services.session.execution_evidence import (
        verify_and_consume_execution_evidence,
    )

    ok, _reason = verify_and_consume_execution_evidence(
        session_id="session-a",
        turn_id="turn-a",
        command_hash="hash-a",
    )
    assert ok is False  # nothing was minted


def test_danger_full_access_bypasses_mxc(monkeypatch, tmp_path, fake_executor):
    fake_executor()
    _install_runtime(
        monkeypatch, permission_preset="full_access", sandbox_mode="danger_full_access"
    )

    def _forbidden(workdir=None, **kwargs):
        raise AssertionError("danger_full_access must bypass MXC")

    monkeypatch.setattr(mxc_backend, "ensure_verified", _forbidden)
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", lambda argv, **kw: _CompletedProcess())
    workdir = tmp_path / "ws"
    workdir.mkdir()

    result = codex_cli_sandbox.execute_codex_sandbox_command("echo hi", cwd=str(workdir))
    assert "sandbox ok" in result
