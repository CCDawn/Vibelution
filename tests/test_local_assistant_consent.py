import json
from pathlib import Path
import threading
import time
import pytest

from core.web.services.local_assistant import consent


def test_long_terminal_wait_requires_active_verified_local_task(monkeypatch):
    calls = []
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: calls.append(runtime) or {"taskId": "owned"})
    for source in ("", "external_agent_task:workspace_write", "launcher_assistant_task_forged"):
        assert not consent.local_terminal_wait_allowed({"runtimeToolSource": source})
    assert calls == []
    native = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    assert consent.local_terminal_wait_allowed(native)
    assert calls == [native]
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: None)
    assert not consent.local_terminal_wait_allowed(native)


def test_authenticated_launcher_dispatch_needs_no_second_approval(monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: True)
    monkeypatch.setattr("core.web.services.local_assistant.management_permissions.read",
                        lambda agent_id: {"preset": "auto_review", "revision": 1})
    args = {"action": "dispatch_write", "arguments_json": json.dumps({"project_id": "p", "agent_id": "a",
        "dispatch_id": "d", "task": "Implement the agreed requirement"})}
    assert consent.local_approval_policy({}, "personal_assistant_manage_tool", args,
                                        ("always", "destructive"), "request_approval")[0] is None


def test_full_access_launcher_task_non_redline_runs_silently_but_redlines_still_ask(tmp_path, monkeypatch):
    # 改写说明（原 test_native_launcher_full_access_still_asks_for_permission_expansion）：
    # 原用例验证 launcher 任务钉死 auto_review 时，即使 Agent 配置了 full_access，
    # 权限扩面（authorization_upgrade）也必须询问。任务档改为跟随 Agent 配置
    # （方案 A）后语义变为两半：full_access 任务的非红线调用静默放行；
    # 红线标签（permission_management 等）仍必须询问。
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    assert consent.local_approval_policy(runtime, "exec_command",
        {"cmd": "python scripts/local_setup.py", "cwd": str(tmp_path)},
        ("on_request", "execute"), "full_access") == (None, "full_access")
    assert consent.local_approval_policy(runtime, "agent_update_tool", {},
        ("always", "destructive"), "full_access") == (("always", "destructive"), "request_approval")


def test_registered_local_task_runs_tests_but_asks_before_push(tmp_path, monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    ordinary = consent.local_approval_policy(runtime, "exec_command", {"cmd": "python -m unittest discover", "cwd": str(tmp_path)},
                                             ("on_request", "execute"), "auto_review")
    dangerous = consent.local_approval_policy(runtime, "exec_command", {"cmd": "git push origin main", "cwd": str(tmp_path)},
                                              ("on_request", "execute"), "auto_review")
    assert ordinary[0] is None
    assert dangerous == (("always", "execute"), "request_approval")


def test_forged_local_source_cannot_use_auto_review(monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: None)
    assert consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
        "exec_command", {"cmd": "python -m unittest"}, ("on_request", "execute"), "auto_review") == (
            ("always", "execute"), "request_approval")


def test_third_party_and_ordinary_session_policy_remain_unchanged(monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    for source in ("", "external_agent_task:workspace_write"):
        assert consent.local_approval_policy({"runtimeToolSource": source}, "exec_command",
            {"cmd": "python -m unittest"}, ("always", "execute"), "request_approval") == (
                ("always", "execute"), "request_approval")


@pytest.mark.parametrize("command", [
    "python -m pytest --basetemp=C:/outside",
    "npm run test --prefix=C:/outside",
    "npm run test --script-shell=C:/outside/evil.exe",
    "git grep --no-index token C:/outside/file.txt",
    "git grep -nOpython test",
])
def test_high_risk_argument_paths_keep_confirmation_at_final_gate(tmp_path, monkeypatch, command):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    assert consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
        "exec_command", {"cmd": command, "cwd": str(tmp_path)}, ("on_request", "execute"), "auto_review") == (
            ("always", "execute"), "request_approval")


def test_local_readonly_discovery_does_not_acquire_a_new_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    assert consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
        "glob_tool", {"pattern": "*.py"}, None, "auto_review") == (None, "auto_review")
    assert consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
        "read_file_tool", {"file_path": "a.py"}, ("on_request", "read"), "auto_review") == (None, "auto_review")
    # 任务档跟随配置后（方案 B），工作区外的只读发现仍询问，但降为普通审批卡：
    # 不再 always 钉死，信任按钮（acceptForSessionTool）在卡上可用。
    assert consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
        "glob_tool", {"pattern": "*.py", "search_dir": str(tmp_path.parent)}, None, "auto_review") == (
            ("on_request", "read"), "auto_review")


@pytest.fixture()
def _clean_approval_state():
    from core.web.services.session import execution_evidence, tool_approvals

    tool_approvals.reset_tool_approval_state(clear_durable=False)
    execution_evidence.reset_execution_evidence_state()
    yield
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    execution_evidence.reset_execution_evidence_state()


def _windows_unverified_sandbox(monkeypatch):
    from core.infrastructure import codex_cli_sandbox

    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")


def test_full_access_launcher_task_runs_without_prompt_and_mints_evidence(tmp_path, monkeypatch, _clean_approval_state):
    """方案 A 端到端：consent 免卡判定 → full_access 短路放行 → 一次性执行证据已签发。

    consent 层对已验证任务的 full_access 非红线调用返回免卡；当 full_access
    调用仍到达审批层时（如其他运行时来源），短路路径必须与 grant/auto_approved
    同口径签发一次性证据，否则 Windows 未验证沙箱门 fail-closed 形成无出口死路。
    """
    _windows_unverified_sandbox(monkeypatch)
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    command = "python scripts/local_setup.py"
    assert consent.local_approval_policy(runtime, "exec_command",
        {"cmd": command, "cwd": str(tmp_path)}, ("on_request", "execute"), "full_access") == (None, "full_access")
    from core.web.services.session import execution_evidence, tool_approvals

    outcome = tool_approvals.authorize_or_wait(
        session_id="session-a", turn_id="turn-a", agent_id="agent-a", call_id="call-full-access",
        tool_name="exec_command", tool_args={"cmd": command},
        approval="on_request", risk="execute", decision_fingerprint="decision-a",
        config_revision=3, config_hash="config-hash-a",
        permission_preset="full_access", timeout_seconds=0.2,
    )
    assert outcome.allowed is True
    assert outcome.code == "full_access_auto_approved"
    assert not tool_approvals.list_tool_approval_requests("session-a", status="pending")
    assert execution_evidence.peek_execution_evidence(
        session_id="session-a", turn_id="turn-a",
        command_hash=execution_evidence.command_execution_hash(command),
    ) != {}


def test_auto_review_launcher_read_card_offers_session_trust(tmp_path, monkeypatch, _clean_approval_state):
    """方案 B 生效证据：auto_review 任务的非红线卡是普通审批卡，含 acceptForSessionTool。"""
    _windows_unverified_sandbox(monkeypatch)
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    outside = str(tmp_path.parent / "notes.md")
    requirement, preset = consent.local_approval_policy(runtime, "read_file_tool",
        {"file_path": outside}, ("on_request", "read"), "auto_review")
    assert (requirement, preset) == (("on_request", "read"), "auto_review")
    from core.web.services.session import tool_approvals

    box = {}

    def run():
        box["outcome"] = tool_approvals.authorize_or_wait(
            session_id="session-a", turn_id="turn-a", agent_id="agent-a", call_id="call-trust",
            tool_name="read_file_tool", tool_args={"file_path": outside},
            approval="on_request", risk="read", decision_fingerprint="decision-a",
            config_revision=3, config_hash="config-hash-a",
            permission_preset="auto_review", timeout_seconds=2.0,
        )

    worker = threading.Thread(target=run)
    worker.start()
    pending = []
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        pending = tool_approvals.list_tool_approval_requests("session-a", status="pending")
        if pending:
            break
        time.sleep(0.01)
    assert pending, "auto_review launcher read outside workspace must still ask"
    assert "acceptForSessionTool" in pending[0]["availableDecisions"]
    tool_approvals.resolve_tool_approval_request("session-a", pending[0]["requestId"], decision="cancel")
    worker.join(timeout=2)


def test_trusted_session_grant_covers_same_command_family(monkeypatch, _clean_approval_state):
    """信任按钮建立会话授权后，同命令族后续调用免卡（_session_grant_scope 家族粒度）。"""
    _windows_unverified_sandbox(monkeypatch)
    from core.web.services.session import tool_approvals

    def authorize(call_id, cmd):
        return tool_approvals.authorize_or_wait(
            session_id="session-a", turn_id="turn-a", agent_id="agent-a", call_id=call_id,
            tool_name="exec_command", tool_args={"cmd": cmd},
            approval="on_request", risk="execute", decision_fingerprint="decision-a",
            config_revision=3, config_hash="config-hash-a",
            permission_preset="auto_review", timeout_seconds=2.0,
        )

    box = {}

    def run():
        box["outcome"] = authorize("call-grant", "pytest -q")

    worker = threading.Thread(target=run)
    worker.start()
    pending = []
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        pending = tool_approvals.list_tool_approval_requests("session-a", status="pending")
        if pending:
            break
        time.sleep(0.01)
    assert pending, "first call in the family must publish an approval request"
    assert pending[0]["sessionGrantScope"] == {"kind": "shell_command_family", "family": "pytest"}
    resolved = tool_approvals.resolve_tool_approval_request(
        "session-a", pending[0]["requestId"], decision="acceptForSessionTool")
    assert resolved["status"] == "accepted_for_session_tool"
    worker.join(timeout=2)

    outcome = authorize("call-next", "pytest -q tests/test_x.py")
    assert outcome.allowed is True
    assert outcome.code == "approved_for_session"
    assert not tool_approvals.list_tool_approval_requests("session-a", status="pending")
