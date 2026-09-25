"""共享桌面壳 CDP 发现与分支工作台窗口定位（只读连接，不断壳）。

流程对齐 docs/guides/desktop-debugging.md：
1. ``python scripts/desktop_debug.py --project "<worktree>"`` 发现共享壳的
   httpEndpoint / webSocketDebuggerUrl / 实时 targets；
2. Playwright ``connect_over_cdp`` 连接后遍历 contexts/pages，用
   ``window.vibelutionLauncher.getDesktopShellSummary().currentWindow`` 判定窗口身份；
3. 按「页面 URL 端口 == 实例端口」+ ``role == "branch-workbench"`` 选中分支工作台页。

红线：不 ``bringToFront``、不对共享壳发 ``Browser.close``；
``connect_over_cdp`` 连接对象的 ``close()`` 只断开客户端连接。
playwright 在函数内导入，保证默认车道 import 本模块不依赖 playwright。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from tests.e2e.helpers.instance_registry import InstanceRegistryError

DEBUG_SCRIPT_RELPATH = Path("scripts") / "desktop_debug.py"
CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def discover_desktop_shell(worktree_root: Path) -> dict[str, Any]:
    """运行仓库自带的发现脚本，返回其 JSON 输出（含 webSocketDebuggerUrl/targets）。"""
    script = Path(worktree_root) / DEBUG_SCRIPT_RELPATH
    if not script.is_file():
        raise InstanceRegistryError(f"CDP 发现脚本不存在: {script}")
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--project", str(worktree_root)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=CREATION_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstanceRegistryError(f"CDP 发现超时: {script}") from exc
    if completed.returncode != 0:
        raise InstanceRegistryError(
            f"CDP 发现失败（exit={completed.returncode}）: {script}\n"
            f"stdout: {(completed.stdout or '')[-400:]!r}\nstderr: {(completed.stderr or '')[-400:]!r}"
        )
    try:
        return json.loads(completed.stdout)
    except ValueError as exc:
        raise InstanceRegistryError(
            f"CDP 发现输出非 JSON: {completed.stdout[:200]!r}"
        ) from exc


def _url_port(url: str) -> int | None:
    try:
        from urllib.parse import urlparse

        port = urlparse(url).port
        return int(port) if port is not None else None
    except ValueError:
        return None


def _page_identity(page: Any) -> dict[str, Any]:
    """读取页面身份；无 vibelutionLauncher bridge 的页面返回空身份。"""
    try:
        summary = page.evaluate(
            "async () => window.vibelutionLauncher"
            " ? await window.vibelutionLauncher.getDesktopShellSummary()"
            " : null"
        )
    except Exception:
        return {}
    current = (summary or {}).get("currentWindow") or {}
    return {"currentWindow": current}


def find_branch_workbench_page(browser: Any, instance_port: int, instance_id: str) -> tuple[Any, list[dict[str, Any]]]:
    """在 CDP 连接里定位分支工作台页；返回 (page, 全部页面身份数据)。

    优先「端口匹配 + bridge 角色 branch-workbench」；实测（2026-09-25）共享壳对
    分支窗口 origin（http://127.0.0.1:<branch-port>）拒绝 getDesktopShellSummary
    的 IPC（"blocked ipc sender origin"），currentWindow 不可得，此时按
    「页面 URL 端口 == 实例端口」回退判定——实例端口与 worktree 一一对应，
    且 launcher 窗口是 vibelution-launcher:// origin 不会误配。
    """
    candidates: list[dict[str, Any]] = []
    port_match: Any = None
    for context in browser.contexts:
        for page in context.pages:
            identity = _page_identity(page)
            current = identity.get("currentWindow") or {}
            candidates.append({"url": page.url, "currentWindow": current})
            if _url_port(page.url) != instance_port:
                continue
            if current.get("role") == "branch-workbench":
                if instance_id and current.get("instanceId") not in (None, instance_id):
                    continue
                return page, candidates
            if port_match is None:
                port_match = page
    if port_match is not None:
        return port_match, candidates
    listing = "\n".join(
        f"  url={item['url']!r} window={item['currentWindow']}" for item in candidates
    )
    raise InstanceRegistryError(
        f"CDP targets 中没有端口 {instance_port} 的 branch-workbench 页面。实际页面:\n{listing}"
    )


@contextmanager
def cdp_branch_page(worktree_root: Path, instance_port: int, instance_id: str) -> Iterator[dict[str, Any]]:
    """连接共享壳并产出分支工作台页；退出时仅断开客户端连接。"""
    from playwright.sync_api import sync_playwright

    discovery = discover_desktop_shell(worktree_root)
    ws_url = discovery.get("webSocketDebuggerUrl")
    if not ws_url:
        raise InstanceRegistryError(f"CDP 发现结果缺少 webSocketDebuggerUrl: {json.dumps(discovery)[:400]}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(ws_url)
        try:
            page, candidates = find_branch_workbench_page(browser, instance_port, instance_id)
            yield {"page": page, "discovery": discovery, "candidates": candidates}
        finally:
            # 官方约定：远程连接调用 close() 仅断开客户端，不发送 CDP Browser.close。
            browser.close()
