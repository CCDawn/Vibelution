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
        "bun run bun:test",
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

    def test_powershell_variable_assignment_routes_to_powershell_on_windows(self, monkeypatch):
        """P0: $p=Join-Path compound statement must not misroute to cmd."""
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)

        cmd = "$p=Join-Path $env:TEMP 'probe.txt'; Set-Content -LiteralPath $p -Value 'x'; Test-Path $p"
        route = shell_tools.classify_shell_command(cmd)

        assert route.route == "powershell"
        assert route.reason == "powershell_cmdlet"
        assert route.final_command.startswith("powershell -NoProfile")

    def test_powershell_env_var_and_dotnet_syntax_detected(self):
        assert shell_tools._is_powershell_command("Write-Output $env:PATH") is True
        assert shell_tools._is_powershell_command("[System.IO.File]::Exists('x')") is True
        assert shell_tools._is_powershell_command("$items = Get-ChildItem; $items.Count") is True

    def test_plain_cmd_commands_not_misclassified_as_powershell(self):
        for cmd in [
            "echo hello",
            "dir /b",
            "git status --short",
            "cd /d C:\\foo",
            "powershell -NoProfile -Command \"Get-ChildItem\"",
        ]:
            assert shell_tools._is_powershell_command(cmd) is False, cmd

    def test_plain_windows_command_routes_to_cmd_on_windows(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)

        route = shell_tools.classify_shell_command("dir")

        assert route.route == "cmd"
        assert route.reason == "windows_default_cmd"
        assert route.final_command == "cmd /c dir"

    def test_plain_git_routes_to_no_console_git_on_windows(self, monkeypatch):
        """cli_tool `git …` must not flash via Git Bash / cmd trampolines."""
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)

        for cmd in (
            "git status --short",
            "git log --oneline -n 5",
            "git rev-parse --abbrev-ref HEAD",
        ):
            route = shell_tools.classify_shell_command(cmd)
            assert route.route == "no_console_git", cmd
            assert route.reason == "windows_no_console_git", cmd
            assert route.final_command == cmd
            assert shell_tools.parse_simple_git_argv(cmd) is not None

    def test_git_with_pipe_does_not_use_no_console_git_route(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)
        # Pipes need a shell; parse_simple_git_argv rejects them.
        assert shell_tools.parse_simple_git_argv("git status | findstr main") is None

    def test_powershell_route_uses_windowstyle_hidden(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)
        route = shell_tools.classify_shell_command("Get-ChildItem tools")
        assert route.route == "powershell"
        assert "-WindowStyle Hidden" in route.final_command

    def test_popen_command_prefers_shell_false_on_windows(self, monkeypatch):
        monkeypatch.setattr(shell_tools, "IS_WINDOWS", True)
        cmd_route = shell_tools.classify_shell_command("dir")
        cmd_line, use_shell = shell_tools._popen_command_for_route(cmd_route, rewritten_command="dir")
        assert use_shell is False
        # 单字符串形态（不经 list2cmdline 转义），显式 cmd.exe 仍是入口。
        assert cmd_line == "cmd.exe /d /s /c dir"

        ps_route = shell_tools.classify_shell_command("Get-ChildItem tools")
        ps_argv, ps_shell = shell_tools._popen_command_for_route(
            ps_route,
            rewritten_command="Get-ChildItem tools",
        )
        assert ps_shell is False
        assert ps_argv[0].lower().startswith("powershell")
        assert "-WindowStyle" in ps_argv
        assert "Hidden" in ps_argv

    def test_shell_failure_cooldown_blocks_second_identical_intent(self):
        """连续 2 次同一失败才拦截；首跑失败只给提示不封死，成功即清零。"""
        shell_tools.reset_shell_failure_cooldown()
        cmd = 'rg -n "pattern|other" path'
        assert shell_tools.shell_failure_cooldown_hit(cmd) == (False, 0)
        assert shell_tools.record_shell_failure(cmd) == 1
        # 首次失败：不拦截，给「修完重跑」留一次机会。
        assert shell_tools.shell_failure_cooldown_hit(cmd) == (False, 1)
        assert shell_tools.record_shell_failure(cmd) == 2
        hit, count = shell_tools.shell_failure_cooldown_hit(cmd)
        assert hit is True
        assert count == 2
        message = shell_tools.shell_failure_cooldown_message(cmd, count)
        assert "工具纪律" in message
        assert "code_symbol_tool" in message
        # 成功执行清零冷却，不永久封死同一命令。
        shell_tools.record_shell_success(cmd)
        assert shell_tools.shell_failure_cooldown_hit(cmd) == (False, 0)
        shell_tools.reset_shell_failure_cooldown()

    def test_shell_failure_detects_warning_exit_and_command_not_found(self):
        assert shell_tools.is_shell_execution_failure(
            "[WARNING | Exit Code: 255]\n[STDERR]\n'Select-Object' 不是内部或外部命令"
        )
        assert shell_tools.is_shell_execution_failure(
            "[WARNING | Exit Code: 1]\n'.venv\\Scripts\\python.exe' 不是内部或外部命令"
        )
        assert not shell_tools.is_shell_execution_failure("ok lines\n1 file matched")

    def test_pure_nonzero_exit_is_normal_semantics_not_failure(self):
        """退出码非零且无错误特征（rg 无命中 / git diff --exit-code / 空输出）不计失败。"""
        assert not shell_tools.is_shell_execution_failure("[WARNING | Exit Code: 1]\n")
        assert not shell_tools.is_shell_execution_failure(
            "[WARNING | Exit Code: 1]\n[命令执行完成，无输出]"
        )
        assert not shell_tools.is_shell_execution_failure(
            "[WARNING | Exit Code: 129]\n[STDOUT]\nsome rows"
        )
        assert not shell_tools.is_shell_execution_failure("[WARNING | Exit Code: 1]\n[STDOUT]\nno matches")

    def test_pytest_red_run_does_not_block_fix_and_rerun(self):
        """回归：首跑红（Exit Code 1）→ 修完重跑不被拦；重跑成功 → 冷却清零。"""
        shell_tools.reset_shell_failure_cooldown()
        cmd = "python -m pytest tests/test_demo.py -q"
        pytest_red = "[EXEC FAILURE | Exit Code: 1]\n[STDOUT]\n1 failed, 2 passed in 0.42s"
        assert shell_tools.is_shell_execution_failure(pytest_red)
        shell_tools.record_shell_failure(cmd, pytest_red)
        # 二跑（修复后的重跑）不被拦。
        assert shell_tools.shell_failure_cooldown_hit(cmd) == (False, 1)
        # 修完代码重跑成功（含退出码非零的正常语义）→ 清零。
        shell_tools.record_shell_success(cmd)
        assert shell_tools.shell_failure_cooldown_hit(cmd) == (False, 0)
        shell_tools.reset_shell_failure_cooldown()

    def test_repeated_traceback_triggers_cooldown(self):
        """回归：同一命令连续相同 traceback 2 次 → 触发冷却。"""
        shell_tools.reset_shell_failure_cooldown()
        cmd = "python scripts/task_brief.py"
        traceback_failure = (
            "[EXEC FAILURE | Exit Code: 1]\n"
            "[STDERR]\nTraceback (most recent call last):\n"
            '  File "scripts/task_brief.py", line 9, in <module>\n'
            "ImportError: cannot import name 'missing'"
        )
        assert shell_tools.is_shell_execution_failure(traceback_failure)
        shell_tools.record_shell_failure(cmd, traceback_failure)
        assert shell_tools.shell_failure_cooldown_hit(cmd) == (False, 1)
        shell_tools.record_shell_failure(cmd, traceback_failure)
        hit, count = shell_tools.shell_failure_cooldown_hit(cmd)
        assert hit is True
        assert count == 2
        shell_tools.reset_shell_failure_cooldown()

    def test_shell_failure_class_blocks_followup_powershell_variants(self):
        """Flash thrash pattern: bare PS under cmd dialect mismatch still shares a class."""
        shell_tools.reset_shell_failure_cooldown()
        first = "Get-Content log.jsonl | Select-Object -First 20"
        second = "Get-ChildItem logs | Select-Object -First 5"
        third = "Get-Process | Where-Object CPU"
        failure = "[WARNING | Exit Code: 255]\n[STDERR]\n'Select-Object' 不是内部或外部命令，也不是可运行的程序"
        assert shell_tools.classify_shell_failure_class(first, failure) == "class:windows_ps_syntax_mismatch"
        # 第一次同类方言失败：只计数，换写法仍可跑一次。
        assert shell_tools.record_shell_failure(first, failure) == 1
        assert shell_tools.shell_failure_cooldown_hit(second) == (False, 1)
        # 第二次同类方言失败：同类变体进入冷却。
        assert shell_tools.record_shell_failure(second, failure) == 2
        hit, count = shell_tools.shell_failure_cooldown_hit(third)
        assert hit is True
        assert count >= 2
        assert "工具纪律" in shell_tools.shell_failure_cooldown_message(third, count)
        shell_tools.reset_shell_failure_cooldown()

    def test_shell_failure_ps_exec_does_not_block_corrected_powershell(self):
        """Quoting/path EXEC FAILURE must not poison later Get-Item/Get-Content under powershell.exe."""
        shell_tools.reset_shell_failure_cooldown()
        first = r'powershell -NoProfile -Command "Get-ChildItem -Path \ $env:APPDATA\" -Directory"'
        second = r'powershell -NoProfile -Command "Get-Item $env:APPDATA"'
        third = r'powershell -NoProfile -Command "Get-Content -Path foo.yaml -Tail 5"'
        failure = (
            "[EXEC FAILURE | Exit Code: 1]\n"
            "[STDERR]\nGet-ChildItem : 路径中有非法字符。\n"
        )
        cls = shell_tools.classify_shell_failure_class(first, failure)
        assert cls.startswith("exact:"), cls
        assert shell_tools.record_shell_failure(first, failure) == 1
        assert shell_tools.shell_failure_cooldown_hit(second) == (False, 0)
        assert shell_tools.shell_failure_cooldown_hit(third) == (False, 0)
        # Identical broken command blocked only after a second consecutive failure.
        assert shell_tools.shell_failure_cooldown_hit(first) == (False, 1)
        assert shell_tools.record_shell_failure(first, failure) == 2
        hit, count = shell_tools.shell_failure_cooldown_hit(first)
        assert hit is True
        assert count == 2
        # 成功重跑清零，不永久封死。
        shell_tools.record_shell_success(first)
        assert shell_tools.shell_failure_cooldown_hit(first) == (False, 0)
        shell_tools.reset_shell_failure_cooldown()

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


# ---------------------------------------------------------------------------
# cmd 路由单字符串 + 外层引号对（venv python 改写回归）
# ---------------------------------------------------------------------------

class TestCmdRouteQuoting:
    """argv 列表形态会让 list2cmdline 转义命令自带引号（\"...），cmd 再把引号
    烤进可执行文件名（实弹：venv python 改写后 '不是内部或外部命令'）。
    cmd 路由必须走单字符串 shell=False，并以引号开头的命令补一层外引号对。
    """

    def _route(self):
        return shell_tools.ShellCommandRoute(
            route="cmd", final_command="x", reason="default", command="python -m pytest t.py"
        )

    def test_plain_command_uses_single_string_not_argv_list(self):
        cmd, shell = shell_tools._popen_command_for_route(
            self._route(), rewritten_command="python -m pytest t.py"
        )
        assert shell is False
        assert isinstance(cmd, str)
        assert cmd == "cmd.exe /d /s /c python -m pytest t.py"

    def test_leading_quoted_executable_gets_one_outer_quote_pair(self):
        quoted = '"C:\repo\.venv\Scripts\python.exe" -m pytest t.py'
        cmd, shell = shell_tools._popen_command_for_route(
            self._route(), rewritten_command=quoted
        )
        assert shell is False
        assert cmd == f'cmd.exe /d /s /c "{quoted}"'

    @pytest.mark.skipif(not shell_tools.IS_WINDOWS, reason="Windows cmd quoting")
    def test_quoted_venv_python_actually_executes(self):
        import subprocess

        venv_python = shell_tools._get_project_python_executable()
        if not venv_python.exists():
            pytest.skip("project venv interpreter not present")
        quoted = f'"{venv_python}" --version'
        cmd, shell = shell_tools._popen_command_for_route(
            self._route(), rewritten_command=quoted
        )
        proc = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=60,
            **shell_tools._subprocess_no_window_kwargs(),
        )
        assert proc.returncode == 0, proc.stderr
        assert "Python" in (proc.stdout or "")
