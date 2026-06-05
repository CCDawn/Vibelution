"""
P0 修复回归测试 - shell_tools 命令路由

覆盖三类核心修复：
1. P0-A: 显式 `bash -c "..."` 包装应绕过 Unix marker 拦截
2. P0-B: 补全 LINUX_COMMANDS（rmdir / touch 等），不再落到 cmd /c 把正斜杠路径当 switch
3. 改进的拦截顺序：LINUX_COMMANDS 优先于 marker 检查
"""
from __future__ import annotations

import pytest

from tools import shell_tools


# ---------------------------------------------------------------------------
# P0-A: 显式 bash -c 包装不应被 marker 拦截
# ---------------------------------------------------------------------------

class TestExplicitBashInvocation:
    def test_plain_bash_dash_c_detected(self):
        assert shell_tools._is_explicit_bash_invocation('bash -c "ls | head"') is True

    def test_bash_exe_detected(self):
        assert shell_tools._is_explicit_bash_invocation('bash.exe -c "echo hi"') is True

    def test_absolute_bash_path_detected(self):
        assert shell_tools._is_explicit_bash_invocation('/bin/bash -c "true"') is True
        assert shell_tools._is_explicit_bash_invocation('/usr/bin/bash -c "true"') is True

    def test_quoted_bash_path_detected(self):
        cmd = '"C:\\Program Files\\Git\\bin\\bash.exe" -c "ls"'
        assert shell_tools._is_explicit_bash_invocation(cmd) is True

    def test_naked_pipe_command_not_detected(self):
        # 裸 ls 不算 bash 显式包装
        assert shell_tools._is_explicit_bash_invocation("ls | head -5") is False

    def test_empty_string_safe(self):
        assert shell_tools._is_explicit_bash_invocation("") is False
        assert shell_tools._is_explicit_bash_invocation("   ") is False

    def test_leading_whitespace_tolerated(self):
        assert shell_tools._is_explicit_bash_invocation('   bash -c "x"') is True


# ---------------------------------------------------------------------------
# P0-B: LINUX_COMMANDS 集合补全
# ---------------------------------------------------------------------------

class TestLinuxCommandSet:
    @pytest.mark.parametrize("cmd", [
        "rmdir workspace/memory/test",
        "touch /tmp/foo",
        "stat tools/shell_tools.py",
        "true",
        "false",
        "date",
        "sleep 1",
        "uname -a",
        "hostname",
        "whoami",
        "printenv PATH",
    ])
    def test_newly_added_commands_recognized(self, cmd):
        assert shell_tools._is_linux_command(cmd) is True, (
            f"{cmd!r} 应被识别为 Linux 命令以避免落到 cmd /c"
        )

    def test_rmdir_with_forward_slash_path(self):
        # 这是踩坑现场：rmdir workspace/agents/... 在 cmd /c 下
        # 会把 /agents 当成 switch 报错
        assert shell_tools._is_linux_command(
            "rmdir workspace/agents/agent-20260529-220827/memory"
        ) is True

    def test_powershell_cmdlet_not_misclassified(self):
        # 确保新增命令没误伤 PowerShell 路径
        assert shell_tools._is_linux_command("Get-ChildItem tools") is False
        assert shell_tools._is_powershell_command("Get-ChildItem tools") is True


# ---------------------------------------------------------------------------
# 拦截顺序与 marker 的交互
# ---------------------------------------------------------------------------

class TestMarkerInteraction:
    def test_marker_still_blocks_naked_command(self):
        """裸命令含 Unix marker 仍应被 _has_unix_shell_markers 识别。"""
        assert shell_tools._has_unix_shell_markers("foo 2>/dev/null") is True
        assert shell_tools._has_unix_shell_markers("cat x | head -5") is True

    def test_bash_wrapped_marker_text_still_matches_marker(self):
        """
        _has_unix_shell_markers 本身不感知 bash 包装，
        它只做字符串匹配；隔离责任由 execute_shell_command 路由顺序保证。
        这里固化它的纯函数语义，防止后续误改。
        """
        assert shell_tools._has_unix_shell_markers('bash -c "ls | head -5"') is True


# ---------------------------------------------------------------------------
# 结构化命令路由分类
# ---------------------------------------------------------------------------

class TestShellCommandClassifier:
    def test_explicit_bash_routes_to_bash_on_windows(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)

        route = shell_tools.classify_shell_command('bash -c "ls | head"')

        assert route.route == "bash"
        assert route.reason == "explicit_bash_invocation"
        assert route.final_command == 'bash -c "ls | head"'
        assert not route.blocked

    def test_linux_command_routes_to_git_bash_on_windows(self, monkeypatch, tmp_path):
        bash = tmp_path / "bash.exe"
        bash.write_text("", encoding="utf-8")
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)
        monkeypatch.setattr(shell_tools, "_find_git_bash", lambda: str(bash))

        route = shell_tools.classify_shell_command("rmdir workspace/memory/test")

        assert route.route == "git_bash"
        assert route.reason == "linux_command_on_windows"
        assert str(bash) in route.final_command
        assert "rmdir workspace/memory/test" in route.final_command

    def test_linux_command_without_git_bash_is_blocked_on_windows(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)
        monkeypatch.setattr(shell_tools, "_find_git_bash", lambda: "")

        route = shell_tools.classify_shell_command("touch /tmp/foo")

        assert route.route == "blocked"
        assert route.reason == "git_bash_missing"
        assert route.blocked
        assert "未找到 Git Bash" in route.error

    def test_unix_marker_is_blocked_on_windows(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)

        route = shell_tools.classify_shell_command("python -m pytest tests -q 2>/dev/null | tail -5")

        assert route.route == "blocked"
        assert route.reason == "unix_shell_marker_on_windows"
        assert "Unix shell 片段" in route.error

    def test_powershell_cmdlet_routes_to_powershell_on_windows(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)

        route = shell_tools.classify_shell_command("Get-ChildItem tools")

        assert route.route == "powershell"
        assert route.reason == "powershell_cmdlet"
        assert route.final_command.startswith("powershell -NoProfile")

    def test_plain_windows_command_routes_to_cmd_on_windows(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)

        route = shell_tools.classify_shell_command("dir")

        assert route.route == "cmd"
        assert route.reason == "windows_default_cmd"
        assert route.final_command == "cmd /c dir"

    def test_windows_command_is_blocked_on_unix(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", False)
        monkeypatch.setattr(shell_tools, "CURRENT_SYSTEM", "linux")

        route = shell_tools.classify_shell_command("dir")

        assert route.route == "blocked"
        assert route.reason == "windows_command_on_unix"
        assert "Windows 特有命令" in route.error


# ---------------------------------------------------------------------------
# 端到端路由（只在 Windows 上验证；其他平台跳过）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not shell_tools.IS_WINDOWS, reason="仅 Windows 路由有 P0 修复")
class TestWindowsRouting:
    def test_bash_dash_c_does_not_return_marker_rejection(self):
        """
        P0-A 端到端：bash -c "..." 不应再返回 [跨平台警告] Unix shell 片段。
        我们不要求命令真的执行成功（Git Bash 可能未安装），
        只要求路由不再卡在 marker 拦截。
        """
        out = shell_tools.execute_shell_command('bash -c "echo hello"', timeout=10)
        assert "Unix shell 片段" not in out, (
            f"bash -c 不应触发 Unix marker 拦截，但收到:\n{out}"
        )

    def test_rmdir_forward_slash_not_routed_to_cmd_switch_error(self):
        """
        P0-B 端到端：rmdir 带正斜杠路径不应再因 cmd /c 路由报
        'Invalid switch' 之类的 cmd 解析错误。
        目录可以不存在；我们只检查不再有 cmd 的 switch 报错。
        """
        out = shell_tools.execute_shell_command(
            "rmdir workspace/memory/__nonexistent_p0_probe__", timeout=10
        )
        assert "Invalid switch" not in out, (
            f"rmdir 不应被 cmd /c 解析为 switch 错误，但收到:\n{out}"
        )

    def test_naked_unix_marker_still_rejected(self):
        """裸命令含 marker 仍应拦截，并提示新的 bash -c 逃生口。"""
        out = shell_tools.execute_shell_command("foo 2>/dev/null", timeout=10)
        assert "跨平台警告" in out
        assert "bash -c" in out, "拦截提示应包含 bash -c 逃生口"
