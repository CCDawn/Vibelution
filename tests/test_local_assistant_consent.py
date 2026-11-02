import json
from pathlib import Path
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
    args = {"action": "dispatch_write", "arguments_json": json.dumps({"project_id": "p", "agent_id": "a",
        "dispatch_id": "d", "task": "Implement the agreed requirement"})}
    assert consent.local_approval_policy({}, "personal_assistant_manage_tool", args,
                                        ("always", "destructive"), "request_approval")[0] is None


def test_native_launcher_full_access_still_asks_for_permission_expansion(monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: True)
    args = {"action": "authorization_upgrade", "arguments_json": "{}"}
    requirement, preset = consent.local_approval_policy({}, "personal_assistant_manage_tool", args,
                                                       ("always", "destructive"), "full_access")
    assert requirement == ("always", "destructive")
    assert preset == "request_approval"


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
    assert consent.local_approval_policy({"runtimeToolSource": "launcher_assistant_task:workspace_write"},
        "glob_tool", {"pattern": "*.py", "search_dir": str(tmp_path.parent)}, None, "auto_review") == (
            ("always", "read"), "request_approval")
