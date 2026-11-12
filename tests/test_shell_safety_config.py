"""Wiring tests for tools.shell.safety_check / dangerous_pattern_check.

The two config fields existed on the panel but never reached execution. These
tests lock the contract:

- both default to on, so today's behaviour is unchanged;
- ``dangerous_pattern_check=False`` skips the blacklist but keeps the whitelist;
- ``safety_check=False`` is the total gate and skips both.
"""

from __future__ import annotations

import pytest

from tools import shell_tools


def test_switches_default_on():
    assert shell_tools.SAFETY_CHECK_ENABLED is True
    assert shell_tools.DANGEROUS_PATTERN_CHECK_ENABLED is True


def test_blacklist_still_blocks_by_default():
    blocked, message = shell_tools._is_command_dangerous("rm -rf /")
    assert blocked is True
    assert "rm -rf /" in message


def test_pattern_check_off_skips_blacklist_but_checks_whitelist(monkeypatch):
    calls = []

    def _whitelist(command):
        calls.append(command)
        return False, ""

    monkeypatch.setattr(shell_tools, "_check_command_whitelist", _whitelist)
    assert shell_tools._is_command_dangerous("rm -rf /", pattern_check=False) == (False, "")
    assert calls == ["rm -rf /"]


def test_config_defaults_read_shell_safety_switches(monkeypatch):
    class _Shell:
        default_timeout = 60
        max_output_length = 10_000
        max_file_size = 1_024
        safety_check = False
        dangerous_pattern_check = False

    class _File:
        editable_extensions: list[str] = []

    class _Security:
        dangerous_commands: list[str] = []
        forbidden_patterns: list[str] = []
        forbidden_delete_patterns: list[str] = []

    class _Cfg:
        shell = _Shell()
        file = _File()
        security = _Security()

    class _Tools:
        shell = _Shell()
        file = _File()

    cfg = _Cfg()
    cfg.tools = _Tools()

    import config

    monkeypatch.setattr(config, "get_config", lambda: cfg)
    defaults = shell_tools._load_config_defaults()
    assert defaults["SAFETY_CHECK"] is False
    assert defaults["DANGEROUS_PATTERN_CHECK"] is False


def test_execution_gate_honours_total_switch(monkeypatch):
    seen = []

    def _dangerous(command, *, pattern_check=True):
        seen.append((command, pattern_check))
        return True, "blocked"

    monkeypatch.setattr(shell_tools, "SAFETY_CHECK_ENABLED", False)
    monkeypatch.setattr(shell_tools, "_is_command_dangerous", _dangerous)

    output = shell_tools.execute_shell_command("echo ok")
    # The dangerous check never ran; the command itself was still attempted.
    assert seen == []
    assert "[安全拦截]" not in output


@pytest.mark.parametrize("command", ["rm -rf /", "shutdown -h now"])
def test_blacklist_covers_destructive_commands(command):
    assert shell_tools._is_command_dangerous(command)[0] is True
