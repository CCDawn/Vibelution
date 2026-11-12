"""tools.shell.allowed_shells wiring tests.

The field was visible on the config panel but the router never consulted it.
These tests lock the family mapping (git_bash counts as bash), the
non-shell route exemption, and the execute-level block.
"""

from __future__ import annotations

import importlib

shell_tools = importlib.import_module("tools.shell_tools")


def test_default_allow_list_passes_powershell(monkeypatch):
    monkeypatch.setattr(shell_tools, "ALLOWED_SHELLS", ["powershell", "cmd", "bash"])
    assert shell_tools._shell_route_blocked("powershell") == ""


def test_bash_family_covers_git_bash(monkeypatch):
    monkeypatch.setattr(shell_tools, "ALLOWED_SHELLS", ["bash"])
    assert shell_tools._shell_route_blocked("bash") == ""
    assert shell_tools._shell_route_blocked("git_bash") == ""


def test_disallowed_route_returns_block_message(monkeypatch):
    monkeypatch.setattr(shell_tools, "ALLOWED_SHELLS", ["powershell"])
    message = shell_tools._shell_route_blocked("cmd")
    assert "[Shell 拦截]" in message
    assert "cmd" in message
    assert "powershell" in message


def test_shell_free_route_is_not_gated(monkeypatch):
    monkeypatch.setattr(shell_tools, "ALLOWED_SHELLS", [])
    assert shell_tools._shell_route_blocked("no_console_git") == ""


def test_empty_allow_list_blocks_every_shell_family(monkeypatch):
    monkeypatch.setattr(shell_tools, "ALLOWED_SHELLS", [])
    for route in ("powershell", "cmd", "bash", "git_bash"):
        assert "[Shell 拦截]" in shell_tools._shell_route_blocked(route)


def test_execute_blocks_route_outside_allow_list(monkeypatch):
    monkeypatch.setattr(shell_tools, "ALLOWED_SHELLS", ["powershell"])
    monkeypatch.setattr(shell_tools, "SAFETY_CHECK_ENABLED", False)
    monkeypatch.setattr(
        shell_tools,
        "classify_shell_command",
        lambda _command: shell_tools.ShellCommandRoute(
            route="cmd",
            final_command="cmd /c exit 0",
            reason="test",
            command="exit 0",
        ),
    )

    result = shell_tools.execute_shell_command("exit 0")

    assert "[Shell 拦截]" in result
    assert "cmd" in result


def test_execute_allows_route_inside_allow_list(monkeypatch):
    monkeypatch.setattr(shell_tools, "ALLOWED_SHELLS", ["cmd"])
    monkeypatch.setattr(shell_tools, "SAFETY_CHECK_ENABLED", False)
    monkeypatch.setattr(
        shell_tools,
        "classify_shell_command",
        lambda _command: shell_tools.ShellCommandRoute(
            route="cmd",
            final_command="cmd /c exit 0",
            reason="test",
            command="exit 0",
        ),
    )

    result = shell_tools.execute_shell_command("exit 0")

    assert "[Shell 拦截]" not in result
