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
    with pytest.raises(consent.LocalTaskScopeError):
        consent.local_terminal_wait_allowed(native)


def test_authenticated_launcher_dispatch_needs_no_second_approval(monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: True)
    monkeypatch.setattr("core.web.services.local_assistant.management_permissions.read",
                        lambda agent_id: {"preset": "auto_review", "revision": 1})
    args = {"action": "dispatch_write", "arguments_json": json.dumps({"project_id": "p", "agent_id": "a",
        "dispatch_id": "d", "task": "Implement the agreed requirement"})}
    assert consent.local_approval_policy({}, "personal_assistant_manage_tool", args,
                                        ("always", "destructive"), "request_approval")[0] is None


def test_full_access_worker_cannot_extend_its_dispatched_task_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    assert consent.local_approval_policy(runtime, "exec_command",
        {"cmd": "python scripts/local_setup.py", "cwd": str(tmp_path)},
        ("on_request", "execute"), "full_access") == (("always", "execute"), "request_approval")
    assert consent.local_approval_policy(runtime, "exec_command",
        {"cmd": "python -m unittest discover", "cwd": str(tmp_path)},
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
    with pytest.raises(consent.LocalTaskScopeError):
        consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
            "exec_command", {"cmd": "python -m unittest"}, ("on_request", "execute"), "auto_review")


def test_third_party_and_ordinary_session_policy_remain_unchanged(monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    for source in ("", "external_agent_task:workspace_write"):
        assert consent.local_approval_policy({"runtimeToolSource": source}, "exec_command",
            {"cmd": "python -m unittest"}, ("always", "execute"), "request_approval") == (
                ("always", "execute"), "request_approval")


def test_local_reuse_evidence_is_only_preapproved_for_an_active_workspace_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    task = {"workspace": tmp_path, "profile": "workspace_write"}
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: task)
    tool = "record_local_reuse_evidence_tool"
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    assert consent.local_approval_policy(runtime, tool, {}, ("on_request", "write"), "auto_review") == (
        None, "auto_review")
    for source in ("", "external_agent_task:workspace_write", "launcher_assistant_task:read_only"):
        with pytest.raises(consent.LocalTaskScopeError):
            consent.local_approval_policy({"runtimeToolSource": source}, tool, {}, None, "full_access")
    task["profile"] = "read_only"
    with pytest.raises(consent.LocalTaskScopeError):
        consent.local_approval_policy(runtime, tool, {}, None, "full_access")


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


@pytest.mark.parametrize(("tool_name", "arguments"), [
    ("read_file_tool", {"file_path": " ../secrets.txt "}),
    ("read_file_tool", {"file_path": ".git"}),
    ("write_file_tool", {"file_path": "workspace/../outside.py"}),
    ("apply_diff_edit_tool", {"file_path": "../outside.py"}),
    ("apply_patch_tool", {"patch_text": "*** Begin Patch\n*** Delete File: ../outside.py\n*** End Patch"}),
    ("glob_tool", {"pattern": "../*.txt"}),
    ("glob_tool", {"pattern": "*.txt", "search_dir": ".."}),
    ("grep_search_tool", {"search_dir": ".."}),
    ("exec_command", {"cmd": "git status", "cwd": ".."}),
    ("cli_tool", {"command": "git status", "cwd": ".."}),
])
def test_workspace_paths_are_denied_without_an_approval_override(tmp_path, monkeypatch, tool_name, arguments):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path})
    with pytest.raises(consent.LocalTaskScopeError, match="超出"):
        consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
                                      tool_name, arguments, ("on_request", "execute"), "full_access")


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


def test_ordinary_full_access_session_still_mints_execution_evidence(monkeypatch, _clean_approval_state):
    _windows_unverified_sandbox(monkeypatch)
    command = "python scripts/local_setup.py"
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


def test_full_access_launcher_task_requires_native_approval_for_network_install(tmp_path, monkeypatch, _clean_approval_state):
    _windows_unverified_sandbox(monkeypatch)
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {"workspace": tmp_path, "profile": "workspace_write"})
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    args = {"cmd": "python -m pip install requests", "cwd": str(tmp_path)}
    requirement, preset = consent.local_approval_policy(runtime, "exec_command",
        args, ("on_request", "execute"), "full_access")
    assert (requirement, preset) == (("always", "execute"), "request_approval")
    from core.web.services.session import tool_approvals

    box = {}

    def run():
        box["outcome"] = tool_approvals.authorize_or_wait(
            session_id="session-a", turn_id="turn-a", agent_id="agent-a", call_id="call-trust",
            tool_name="exec_command", tool_args=args,
            approval=requirement[0], risk=requirement[1], decision_fingerprint="decision-a",
            config_revision=3, config_hash="config-hash-a", permission_preset=preset, timeout_seconds=2.0,
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
    assert pending, "dependency installation must ask even when the worker has full_access"
    assert "acceptForSessionTool" not in pending[0]["availableDecisions"]
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
