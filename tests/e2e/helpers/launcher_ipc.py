"""显式 E2E 桌面 IPC 通道：只操作本测试树，不关闭或聚焦共享壳。

IPC accepted 仅表示请求受理；就绪和关闭仍由 e2e_instance 的 registry/health
核对。拒绝、超时或发现失败直接报错，不重试、不自动改走 native。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.e2e.helpers.desktop_cdp import CREATION_FLAGS, discover_desktop_shell
from tests.e2e.helpers.launcher import LauncherCommandError

OWNER_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_URL = "vibelution-launcher://launcher/launcher"
IPC_TIMEOUT_MS = 30_000
COMMAND_TIMEOUT_SECONDS = 130

# 身份检查与请求在同一次 evaluate 中进行，防止定位后页面已被导航。
_INVOKE = """async ({command, instanceId, hiddenPresentation, timeoutMs}) => {
  let timedOut = false;
  const operation = async () => {
    if (location.href !== 'vibelution-launcher://launcher/launcher')
      throw new Error('E2E requires the Launcher page');
    const bridge = window.vibelutionLauncher;
    const summary = bridge && await bridge.getDesktopShellSummary();
    if (summary?.currentWindow?.role !== 'launcher')
      throw new Error('E2E requires Launcher window identity');
    if (timedOut) throw new Error('Launcher IPC identity timed out; no request');
    return await bridge.launcherInvoke({
      schemaVersion: 1, path: 'branch-instances/' + command,
      init: {method: 'POST', body: {instanceId, hiddenPresentation}}
    });
  };
  let timer;
  try {
    return await Promise.race([operation(), new Promise((_, reject) => {
      timer = setTimeout(() => {
        timedOut = true;
        reject(new Error('Launcher IPC timed out; no retry'));
      }, timeoutMs);
    })]);
  } finally { clearTimeout(timer); }
}"""


def _task_root(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    if root != OWNER_ROOT or not (root / ".git").is_file():
        raise LauncherCommandError(f"IPC 只允许当前测试的任务 worktree: {root}")
    branch = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True, timeout=10, creationflags=CREATION_FLAGS,
    )
    if branch.returncode != 0 or not branch.stdout.strip().startswith("codex/"):
        raise LauncherCommandError(f"IPC 要求 codex/ 任务分支: {root}")
    return root


def _find_launcher_page(browser: Any) -> Any:
    pages = [page for context in browser.contexts for page in context.pages if page.url == LAUNCHER_URL]
    if len(pages) != 1:
        raise LauncherCommandError(f"CDP 必须有唯一 Launcher 页面，实际匹配 {len(pages)} 个")
    return pages[0]


def invoke_instance_command(project_root: str | Path, command: str, *, hidden_presentation: bool = False) -> None:
    if command not in {"start", "stop"}:
        raise LauncherCommandError(f"E2E IPC 不支持命令: {command!r}")
    root = _task_root(project_root)
    # page fixture 已有 Playwright driver 时，另起隐藏客户端避免同步事件循环嵌套。
    # 子进程的整体超时也约束 renderer 不响应、Promise 定时器无法运行的情况。
    argv = [sys.executable, "-m", "tests.e2e.helpers.launcher_ipc", str(root), command]
    if hidden_presentation:
        argv.append("--hidden-presentation")
    try:
        completed = subprocess.run(
            argv, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS, creationflags=CREATION_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise LauncherCommandError("Launcher IPC 整体超时（不重试；实例状态需核对）") from exc
    if completed.returncode != 0:
        raise LauncherCommandError(f"Launcher IPC {command} 失败（不重试）: {completed.stderr[-500:]}")


def _invoke_desktop_command(root: Path, command: str, *, hidden_presentation: bool = False) -> None:
    try:
        from playwright.sync_api import sync_playwright

        discovery = discover_desktop_shell(root)
        endpoint = discovery.get("webSocketDebuggerUrl")
        if not endpoint:
            raise LauncherCommandError("桌面发现结果缺少 webSocketDebuggerUrl")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint, timeout=IPC_TIMEOUT_MS)
            page = _find_launcher_page(browser)
            result = page.evaluate(_INVOKE, {
                "command": command, "instanceId": "worktree:" + str(root).lower(),
                "hiddenPresentation": hidden_presentation, "timeoutMs": IPC_TIMEOUT_MS,
            })
            # sync_playwright 退出只停止本地 driver；不调用共享 browser/page/context.close。
        payload = result.get("payload") if isinstance(result, dict) else None
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(payload, dict) or payload.get("accepted") is not True:
            raise LauncherCommandError(f"Launcher IPC {command} 未受理: {str(result)[:500]}")
    except LauncherCommandError:
        raise
    except Exception as exc:
        raise LauncherCommandError(f"Launcher IPC {command} 失败（不重试）: {str(exc)[:500]}") from exc


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    parser.add_argument("command", choices=["start", "stop"])
    parser.add_argument("--hidden-presentation", action="store_true")
    args = parser.parse_args()
    try:
        _invoke_desktop_command(_task_root(args.project_root), args.command, hidden_presentation=args.hidden_presentation)
    except Exception as exc:
        print(str(exc)[:500], file=sys.stderr)
        sys.exit(1)
