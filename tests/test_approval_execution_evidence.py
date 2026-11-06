"""「审批即证据」：Windows 审批死路修复 Phase 1 的行为契约测试。

覆盖面：
- request_approval 档（Windows 未验证沙箱）：显式批准后命令真实执行；
  拒绝/超时仍拦且无凭据签发。
- auto_review 档：Windows 下 cli_tool/exec_command/write_stdin 不再静默自动批，
  创建 pending 审批；非 Windows 平台静默自动批行为回归不变。
- 凭据伪造面：无凭据/过期/命令哈希不匹配/跨会话/跨回合/重放 → 全部
  SANDBOX_UNVERIFIED fail-closed。
- 内容门先于凭据放行：危险命令/路由拦截即使有凭据也拦，且凭据不被消费。
- Key_Tools 失败冷却对 SANDBOX_UNVERIFIED 环境拒绝不计数。
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from core.authorization import tool_authorization_service
from core.infrastructure import codex_cli_sandbox
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service
from core.web.services.session import execution_evidence, tool_approvals
from tools.shell_tools import reset_shell_failure_cooldown, shell_failure_cooldown_hit


class _CompletedProcess:
    pid = 4242
    returncode = 0

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        return "sandbox ok\n", ""


@pytest.fixture(autouse=True)
def _clean_approval_and_evidence_state():
    tool_authorization_service.clear_execution_authorization()
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    execution_evidence.reset_execution_evidence_state()
    reset_shell_failure_cooldown()
    yield
    tool_authorization_service.clear_execution_authorization()
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    execution_evidence.reset_execution_evidence_state()
    reset_shell_failure_cooldown()


def _install_runtime(
    monkeypatch,
    *,
    session_id="session-a",
    turn_id="turn-a",
    permission_preset="request_approval",
    config_revision=3,
    config_hash="config-hash-a",
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
                "configRevision": config_revision,
                "configHash": config_hash,
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


def _windows_sandbox_gate(monkeypatch, tmp_path, *, spawn_record=None):
    """Windows 未验证沙箱 + 可控 spawn 的真实沙箱门。"""

    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )

    def fake_popen(argv, **kwargs):
        if spawn_record is not None:
            spawn_record["argv"] = argv
        return _CompletedProcess()

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", fake_popen)
    return str(tmp_path)


def _install_requirement(*requirements):
    tool_authorization_service.install_execution_authorization(
        SimpleNamespace(
            decision=SimpleNamespace(
                agent_id="agent-a",
                turn_id="turn-a",
                decision_fingerprint="decision-a",
                executable_tools=tuple(item[0] for item in requirements),
                approval_requirements=tuple(requirements),
            )
        )
    )


def _wait_for_pending(session_id="session-a"):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        pending = tool_approvals.list_tool_approval_requests(session_id, status="pending")
        if pending:
            return pending[0]
        time.sleep(0.01)
    raise AssertionError("tool approval request was not published")


def _resolve(session_id, request, decision):
    tool_approvals.resolve_tool_approval_request(session_id, request["requestId"], decision=decision)


def _sandbox_command_result(cmd, cwd):
    return codex_cli_sandbox.execute_codex_sandbox_command(cmd, cwd=cwd)


def _execute_with_authorization(requirement, tool_name, tool_args, impl, box, call_id):
    """Run executor.execute in a worker thread with its turn authorization bound.

    安装授权上下文的 contextvar 不跨线程：必须与执行同线程 install（与
    test_tool_approval_flow 的既有模式一致）。
    """

    def run():
        _install_requirement(requirement)
        executor = ToolExecutor()
        executor.register_tool(tool_name, impl)
        box.setdefault("value", executor.execute(tool_name, tool_args, tool_call_id=call_id))

    worker = threading.Thread(target=run)
    worker.start()
    return worker


# ── request_approval 档：批准即放行，拒绝/超时无凭据 ─────────────────────────


def test_request_approval_windows_approved_command_executes(monkeypatch, tmp_path):
    _install_runtime(monkeypatch, permission_preset="request_approval")
    cwd = _windows_sandbox_gate(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    box = {}
    worker = _execute_with_authorization(
        ("exec_command", "on_request", "execute"),
        "exec_command",
        {"cmd": "echo approved"},
        lambda **kwargs: _sandbox_command_result(kwargs.get("cmd", ""), cwd),
        box,
        "call-1",
    )
    request = _wait_for_pending()
    assert request["toolName"] == "exec_command"
    _resolve("session-a", request, "accept")
    worker.join(timeout=5)

    result, action = box["value"]
    assert result == "sandbox ok"
    assert action is None
    assert spawn["argv"], "approved command must actually spawn"

    # 凭据一次性：批准已消费，同命令再次直连沙箱门必须 fail-closed。
    replay = codex_cli_sandbox.execute_codex_sandbox_command("echo approved", cwd=cwd)
    assert "SANDBOX_UNVERIFIED" in replay


def test_request_approval_windows_declined_command_stays_blocked(monkeypatch, tmp_path):
    _install_runtime(monkeypatch, permission_preset="request_approval")
    cwd = _windows_sandbox_gate(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    box = {}
    worker = _execute_with_authorization(
        ("exec_command", "on_request", "execute"),
        "exec_command",
        {"cmd": "echo declined"},
        lambda **kwargs: _sandbox_command_result(kwargs.get("cmd", ""), cwd),
        box,
        "call-1",
    )
    request = _wait_for_pending()
    _resolve("session-a", request, "decline")
    worker.join(timeout=5)

    result, _action = box["value"]
    # 拒绝在审批层生效：调用被拒、工具实现根本不执行。
    assert "用户拒绝" in result
    assert not spawn, "declined command must not spawn"
    # 拒绝路径绝不签发凭据；同命令后续任何直连尝试都被沙箱门拦下。
    assert execution_evidence.peek_execution_evidence(
        session_id="session-a",
        turn_id="turn-a",
        command_hash=execution_evidence.command_execution_hash("echo declined"),
    ) == {}
    assert "SANDBOX_UNVERIFIED" in codex_cli_sandbox.execute_codex_sandbox_command(
        "echo declined", cwd=cwd
    )


def test_request_approval_windows_timeout_stays_blocked_without_evidence(monkeypatch, tmp_path):
    _install_runtime(monkeypatch, permission_preset="request_approval")
    cwd = _windows_sandbox_gate(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    box = {}

    def run():
        box["value"] = tool_approvals.authorize_or_wait(
            session_id="session-a",
            turn_id="turn-a",
            agent_id="agent-a",
            call_id="call-timeout",
            tool_name="exec_command",
            tool_args={"cmd": "echo timeout"},
            approval="on_request",
            risk="execute",
            decision_fingerprint="decision-a",
            config_revision=3,
            config_hash="config-hash-a",
            permission_preset="request_approval",
            timeout_seconds=0.2,
        )

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(timeout=5)
    outcome = box["value"]
    assert outcome.allowed is False
    assert outcome.code == "approval_timeout"
    assert not spawn
    assert execution_evidence.peek_execution_evidence(
        session_id="session-a",
        turn_id="turn-a",
        command_hash=execution_evidence.command_execution_hash("echo timeout"),
    ) == {}
    assert "SANDBOX_UNVERIFIED" in codex_cli_sandbox.execute_codex_sandbox_command(
        "echo timeout", cwd=cwd
    )


def test_accept_for_session_grant_mints_evidence_for_repeat_calls(monkeypatch, tmp_path):
    _install_runtime(monkeypatch, permission_preset="request_approval")
    cwd = _windows_sandbox_gate(monkeypatch, tmp_path)
    impl = lambda **kwargs: _sandbox_command_result(kwargs.get("cmd", ""), cwd)  # noqa: E731
    box = {}
    worker = _execute_with_authorization(
        ("exec_command", "on_request", "execute"),
        "exec_command",
        {"cmd": "echo granted"},
        impl,
        box,
        "call-1",
    )
    request = _wait_for_pending()
    _resolve("session-a", request, "acceptForSession")
    worker.join(timeout=5)
    result, _ = box["value"]
    assert result == "sandbox ok"

    # 同参数重发命中会话授权短路（approved_for_session），仍需签发一次性凭据。
    box2 = {}
    worker2 = _execute_with_authorization(
        ("exec_command", "on_request", "execute"),
        "exec_command",
        {"cmd": "echo granted"},
        impl,
        box2,
        "call-2",
    )
    worker2.join(timeout=5)
    result2, _ = box2["value"]
    assert result2 == "sandbox ok"
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []


# ── auto_review 档：Windows 不再静默自动批；非 Windows 回归不变 ──────────────


def test_auto_review_windows_prompts_instead_of_silent_auto_approval(monkeypatch, tmp_path):
    _install_runtime(monkeypatch, permission_preset="auto_review")
    cwd = _windows_sandbox_gate(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    box = {}
    worker = _execute_with_authorization(
        ("exec_command", "on_request", "execute"),
        "exec_command",
        {"cmd": "echo auto"},
        lambda **kwargs: _sandbox_command_result(kwargs.get("cmd", ""), cwd),
        box,
        "call-1",
    )
    request = _wait_for_pending()
    assert request["toolName"] == "exec_command"
    assert request["permissionPreset"] == "auto_review"
    assert not spawn, "must not silently execute before an operator decision"
    _resolve("session-a", request, "accept")
    worker.join(timeout=5)
    result, _ = box["value"]
    assert result == "sandbox ok"


def test_auto_review_windows_write_stdin_also_prompts(monkeypatch):
    _install_runtime(monkeypatch, permission_preset="auto_review")
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    assert (
        tool_approvals._can_auto_approve(
            permission_preset="auto_review",
            tool_name="write_stdin",
            tool_args={"session_id": "sandbox-x", "chars": "y"},
            approval="on_request",
            risk="execute",
        )
        is False
    )


def test_auto_review_non_windows_still_auto_approves(monkeypatch):
    _install_runtime(monkeypatch, permission_preset="auto_review")
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "linux")
    assert (
        tool_approvals._can_auto_approve(
            permission_preset="auto_review",
            tool_name="exec_command",
            tool_args={"cmd": "echo hi"},
            approval="on_request",
            risk="execute",
        )
        is True
    )


# ── 凭据伪造面：全部 fail-closed ──────────────────────────────────────────────


def _gate_blocked(monkeypatch, tmp_path, *, spawn_record=None) -> str:
    cwd = _windows_sandbox_gate(monkeypatch, tmp_path, spawn_record=spawn_record)
    return cwd


def test_gate_rejects_missing_or_invalid_runtime_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a"},
    )
    cwd = _gate_blocked(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: (_ for _ in ()).throw(AssertionError("must not resolve Codex")),
    )
    result = codex_cli_sandbox.execute_codex_sandbox_command("echo hi", cwd=cwd)
    assert "SANDBOX_UNVERIFIED" in result
    assert not spawn


def test_gate_rejects_expired_evidence(monkeypatch, tmp_path):
    _install_runtime(monkeypatch)
    cwd = _gate_blocked(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    execution_evidence.record_execution_evidence(
        session_id="session-a",
        turn_id="turn-a",
        command_hash=execution_evidence.command_execution_hash("echo stale"),
        ttl_seconds=0.05,
    )
    time.sleep(0.15)
    result = codex_cli_sandbox.execute_codex_sandbox_command("echo stale", cwd=cwd)
    assert "SANDBOX_UNVERIFIED" in result
    assert not spawn


def test_gate_rejects_command_hash_mismatch(monkeypatch, tmp_path):
    _install_runtime(monkeypatch)
    cwd = _gate_blocked(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    execution_evidence.record_execution_evidence(
        session_id="session-a",
        turn_id="turn-a",
        command_hash=execution_evidence.command_execution_hash("echo other-command"),
    )
    result = codex_cli_sandbox.execute_codex_sandbox_command("echo approved-command", cwd=cwd)
    assert "SANDBOX_UNVERIFIED" in result
    assert not spawn


def test_gate_rejects_cross_session_and_cross_turn_evidence(monkeypatch, tmp_path):
    _install_runtime(monkeypatch, session_id="session-b", turn_id="turn-b")
    cwd = _gate_blocked(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    command_hash = execution_evidence.command_execution_hash("echo bounded")
    execution_evidence.record_execution_evidence(
        session_id="session-a", turn_id="turn-a", command_hash=command_hash
    )
    result = codex_cli_sandbox.execute_codex_sandbox_command("echo bounded", cwd=cwd)
    assert "SANDBOX_UNVERIFIED" in result
    assert not spawn

    # 跨回合：同会话、不同 turn。
    _install_runtime(monkeypatch, session_id="session-a", turn_id="turn-z")
    result = codex_cli_sandbox.execute_codex_sandbox_command("echo bounded", cwd=cwd)
    assert "SANDBOX_UNVERIFIED" in result
    assert not spawn


def test_gate_rejects_replayed_evidence(monkeypatch, tmp_path):
    _install_runtime(monkeypatch)
    cwd = _gate_blocked(monkeypatch, tmp_path, spawn_record=(spawn := {}))
    execution_evidence.record_execution_evidence(
        session_id="session-a",
        turn_id="turn-a",
        command_hash=execution_evidence.command_execution_hash("echo once"),
    )
    first = codex_cli_sandbox.execute_codex_sandbox_command("echo once", cwd=cwd)
    assert first == "sandbox ok"
    assert spawn
    second = codex_cli_sandbox.execute_codex_sandbox_command("echo once", cwd=cwd)
    assert "SANDBOX_UNVERIFIED" in second


# ── 内容门先于凭据放行，凭据不被消费 ─────────────────────────────────────────


def test_content_gates_still_block_despite_valid_evidence(monkeypatch, tmp_path):
    _install_runtime(monkeypatch)
    cwd = _gate_blocked(monkeypatch, tmp_path)
    command_hash = execution_evidence.command_execution_hash("echo safe-after-danger")
    execution_evidence.record_execution_evidence(
        session_id="session-a", turn_id="turn-a", command_hash=command_hash
    )

    dangerous = codex_cli_sandbox.execute_codex_sandbox_command(
        "echo unsafe && rm -rf /", cwd=cwd
    )
    assert "SANDBOX_UNVERIFIED" not in dangerous
    assert ("DANGEROUS_COMMAND" in dangerous) or ("安全拦截" in dangerous)

    # 内容门拦截不消费凭据：随后的同凭据合法命令仍然放行。
    ok = codex_cli_sandbox.execute_codex_sandbox_command("echo safe-after-danger", cwd=cwd)
    assert ok == "sandbox ok"


# ── Key_Tools 失败冷却豁免 ────────────────────────────────────────────────────


def test_cli_tool_sandbox_unverified_block_not_counted_as_shell_failure(monkeypatch):
    from tools.Key_Tools import create_key_tools

    block_text = (
        "[安全拦截 | SANDBOX_UNVERIFIED] Windows 原生 Codex 离线 shell 隔离未通过"
        "运行时验证；本次调用没有有效凭据。命令未执行。"
    )
    monkeypatch.setattr(
        codex_cli_sandbox,
        "execute_codex_sandbox_command",
        lambda *args, **kwargs: block_text,
    )
    cli_tool = next(tool for tool in create_key_tools() if tool.name == "cli_tool")
    result = cli_tool.func(command="echo blocked-intent")
    assert "SANDBOX_UNVERIFIED" in result
    cooled, count = shell_failure_cooldown_hit("echo blocked-intent")
    assert cooled is False
    assert count == 0

    # 对照组：真实执行失败仍计入冷却。
    monkeypatch.setattr(
        codex_cli_sandbox,
        "execute_codex_sandbox_command",
        lambda *args, **kwargs: "[EXEC FAILURE | Exit Code: 1] boom",
    )
    cli_tool.func(command="echo real-failure")
    _cooled, count = shell_failure_cooldown_hit("echo real-failure")
    assert count >= 1


def test_exec_command_sandbox_unverified_block_not_counted_as_shell_failure(monkeypatch):
    from tools.Key_Tools import create_key_tools

    monkeypatch.setattr(
        codex_cli_sandbox,
        "start_codex_sandbox_terminal_session",
        lambda *args, **kwargs: {
            "status": "failed",
            "code": "SANDBOX_UNVERIFIED",
            "message": "no evidence",
            "failureClass": "sandbox_unverified",
        },
    )
    exec_command = next(tool for tool in create_key_tools() if tool.name == "exec_command")
    result = json.loads(exec_command.func(cmd="echo blocked-intent"))
    assert result["code"] == "SANDBOX_UNVERIFIED"
    _cooled, count = shell_failure_cooldown_hit("echo blocked-intent")
    assert count == 0

    # 对照组：真实启动失败仍计入冷却。
    monkeypatch.setattr(
        codex_cli_sandbox,
        "start_codex_sandbox_terminal_session",
        lambda *args, **kwargs: {
            "status": "failed",
            "code": "SANDBOX_START_FAILED",
            "message": "sandbox start failed",
        },
    )
    exec_command.func(cmd="echo real-failure")
    _cooled, count = shell_failure_cooldown_hit("echo real-failure")
    assert count >= 1
