"""通过官方 Launcher 起停分支实例（默认原生进程，显式可选桌面 IPC）。

命令形态：``VibelutionLauncher.exe --project "<worktree>" start|stop``。
native 通道只等待并读取原生 Launcher 自身的退码（对应
docs/guides/launcher-branch-development.md 中 .NET Process 的等价物），
子进程一律 ``CREATE_NO_WINDOW``，禁止 taskkill / 裸 shell。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.e2e.helpers.instance_registry import launcher_log_dir_hint

LAUNCHER_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Vibelution" / "Launcher" / "VibelutionLauncher.exe"

# Native start owns a 900s bridge deadline (810s settlement + retry/margin).
# Let it report its own failure before the test client cancels the command.
START_TIMEOUT_SECONDS = 915.0
LAUNCH_TIMEOUT_SECONDS = 300.0

# 测试基础设施同样遵守产品无控制台红线：所有子进程隐藏窗口。
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class LauncherCommandError(RuntimeError):
    """Launcher 命令失败、被拒绝或执行超时。"""


def _e2e_mode() -> str:
    return os.environ.get("VIBELUTION_E2E_MODE", "headless").strip().lower()


def _run_instance_command(
    project_root: str | os.PathLike[str], command: str, *, hidden_presentation: bool = False,
) -> None:
    transport = os.environ.get("VIBELUTION_E2E_LAUNCHER_TRANSPORT", "native").strip().lower()
    if transport == "desktop_ipc":
        from tests.e2e.helpers.launcher_ipc import invoke_instance_command

        invoke_instance_command(project_root, command, hidden_presentation=hidden_presentation)
        return
    if transport != "native":
        raise LauncherCommandError(f"未知 E2E Launcher transport: {transport!r}（native|desktop_ipc）")
    completed = run_launcher_command(
        project_root, command, hidden_presentation=hidden_presentation,
        timeout_seconds=START_TIMEOUT_SECONDS if command == "start" else LAUNCH_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise LauncherCommandError(_failure(command, project_root, completed))


def run_launcher_command(
    project_root: str | os.PathLike[str],
    command: str,
    *,
    timeout_seconds: float = LAUNCH_TIMEOUT_SECONDS,
    hidden_presentation: bool = False,
) -> subprocess.CompletedProcess[str]:
    """执行一条 Launcher 生命周期命令并原样返回 CompletedProcess。

    ``hidden_presentation=True`` 追加 ``--hidden-presentation``：共享壳加载
    分支工作台窗口但不 show/focus（窗口存在、renderer 存活，注册表照常观察）。
    """
    if not LAUNCHER_EXE.is_file():
        raise LauncherCommandError(f"Launcher 可执行文件不存在: {LAUNCHER_EXE}")
    argv = [str(LAUNCHER_EXE), "--project", str(project_root), command]
    if hidden_presentation:
        argv.append("--hidden-presentation")
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=_CREATION_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise LauncherCommandError(
            f"Launcher {command} 超时（{timeout_seconds:.0f}s）：project={project_root}\n"
            f"launcher 日志目录线索: {launcher_log_dir_hint(project_root)}"
        ) from exc
    return completed


def start_instance(
    project_root: str | os.PathLike[str],
    *,
    hidden_presentation: bool | None = None,
) -> None:
    """启动分支实例；headless 车道默认隐藏呈现，避免 e2e 抢用户桌面焦点。

    按模式分流：``VIBELUTION_E2E_MODE=cdp`` 是人工/CDP 调试车道，默认保持
    弹出真实窗口便于肉眼观察（显式传 ``hidden_presentation`` 可覆盖；隐藏
    窗口 renderer 仍存活，CDP 亦能连接）。
    """
    if hidden_presentation is None:
        hidden_presentation = _e2e_mode() != "cdp"
    _run_instance_command(project_root, "start", hidden_presentation=hidden_presentation)


def stop_instance(project_root: str | os.PathLike[str]) -> None:
    _run_instance_command(project_root, "stop")


def _failure(command: str, project_root: str | os.PathLike[str], completed: subprocess.CompletedProcess[str]) -> str:
    stdout_tail = (completed.stdout or "").strip()[-500:]
    stderr_tail = (completed.stderr or "").strip()[-500:]
    return (
        f"Launcher {command} 退出码 {completed.returncode}：project={project_root}\n"
        f"stdout tail: {stdout_tail!r}\nstderr tail: {stderr_tail!r}\n"
        f"launcher 日志目录线索: {launcher_log_dir_hint(project_root)}"
    )
