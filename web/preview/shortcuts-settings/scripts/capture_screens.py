"""预览截图与交互自检 —— python + playwright（无仓库内新依赖，用本机 playwright）。

先自行拉起 vite dev server（端口 5198），跑完交互断言 + 截图后关闭。
截图输出到 screenshots/，同时写 capture-report.json（含交互断言结果与
console/pageerror 收集；任何 console error 都会让脚本以非零码退出）。

用法：python scripts/capture_screens.py
环境变量：SSP_BASE_URL（默认 http://127.0.0.1:5198，设置后不拉起 server）。
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PREVIEW_DIR = HERE.parent
WEB_ROOT = PREVIEW_DIR.parents[1]
OUT_DIR = PREVIEW_DIR / "screenshots"
BASE_URL = os.environ.get("SSP_BASE_URL", "http://127.0.0.1:5198")
PAGE_URL = f"{BASE_URL}/preview/shortcuts-settings/index.html"
VIEWPORT = {"width": 1512, "height": 945}


def wait_for_server(url: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    raise RuntimeError(f"dev server not reachable: {url}")


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    report: dict = {"shots": [], "asserts": [], "consoleErrors": [], "pageErrors": []}
    server = None
    if "SSP_BASE_URL" not in os.environ:
        server = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js",
                "--config",
                "preview/shortcuts-settings/vite.config.ts",
            ],
            cwd=str(WEB_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
    try:
        wait_for_server(PAGE_URL)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT)
            page = context.new_page()
            page.on(
                "console",
                lambda msg: report["consoleErrors"].append(msg.text) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda err: report["pageErrors"].append(str(err)))

            def check(name: str, ok: bool) -> None:
                report["asserts"].append({"name": name, "ok": bool(ok)})
                if not ok:
                    print(f"[assert-fail] {name}")

            def shot(name: str, label: str) -> None:
                path = OUT_DIR / name
                page.screenshot(path=str(path), full_page=False)
                report["shots"].append({"file": name, "label": label})
                print(f"[shot] {name} — {label}")

            # 1) 默认清单：命令行 + 当前绑定 kbd + 状态徽章 + 修改/清除操作。
            page.goto(PAGE_URL, wait_until="networkidle")
            check("rows rendered", page.locator('[data-testid="shortcut-row-openCommandPalette"]').count() == 1)
            check("kbd rendered", page.locator('[data-testid="binding-kbd"]').count() >= 2)
            shot("01-settings-list.png", "快捷键设置清单（默认绑定 + 操作）")

            # 2) 修改 → 录制态：录制条出现，修饰键 pending 提示。
            page.click('[data-testid="modify-openCommandPalette"]')
            page.wait_for_selector('[data-testid="recording-strip"]')
            page.keyboard.press("Shift")  # 纯修饰键 → pending，不落绑定
            page.wait_for_timeout(120)
            check(
                "pending hint shown",
                "等待完整组合" in page.locator('[data-testid="recording-strip"]').inner_text(),
            )
            shot("02-recording.png", "录制新绑定态（修饰键等待提示）")

            # 3) 录制到被占用组合 → 占用冲突拒绝（含物理归一判定详情）。
            #    命令自身的现有绑定不构成冲突（覆盖=整组替换），故对会话搜索录
            #    命令面板已占用的 Ctrl+K。Esc 先取消上一段录制。
            page.keyboard.press("Escape")
            page.wait_for_timeout(120)
            page.click('[data-testid="modify-openSessionSearch"]')
            page.wait_for_selector('[data-testid="recording-strip"]')
            page.keyboard.press("Control+k")
            page.wait_for_selector('[data-testid="banner"]')
            banner = page.locator('[data-testid="banner"]').inner_text()
            check("occupied rejected", "已被「打开命令面板」占用" in banner)
            check("canonical detail shown", "物理归一判定" in banner)
            shot("03-conflict-occupied.png", "录制命中占用冲突（归一判定详情）")

            # 4) 保留键拒绝：Enter（对话框确认键）录到会话搜索。
            page.click('[data-testid="banner"] button:has-text("关闭")')
            page.click('[data-testid="modify-openSessionSearch"]')
            page.wait_for_selector('[data-testid="recording-strip"]')
            page.keyboard.press("Enter")
            page.wait_for_selector('[data-testid="banner"]')
            banner = page.locator('[data-testid="banner"]').inner_text()
            check("reserved rejected", "保留键" in banner and "Enter" in banner)
            shot("04-reserved-enter.png", "保留键拒绝（Enter）")

            # 5) 清除语义：显式空数组 → 「未设置」+ 已清除徽章；reload 后仍生效（持久化）。
            page.click('[data-testid="banner"] button:has-text("关闭")')
            page.click('[data-testid="clear-openCommandPalette"]')
            page.wait_for_selector('[data-testid="unset-chip"]')
            stored = page.evaluate("localStorage.getItem('vibelution.shortcuts.overrides')")
            check("empty-array persisted", stored is not None and '"openCommandPalette":[]' in stored.replace(" ", ""))
            check(
                "override json shown",
                '"openCommandPalette": []' in page.locator('[data-testid="overrides-json"]').inner_text(),
            )
            shot("05-cleared-unset.png", "显式空数组清除（未设置 + 持久化 JSON）")
            page.reload(wait_until="networkidle")
            page.wait_for_selector('[data-testid="unset-chip"]')
            check("cleared survives reload", True)

            # 6) 恢复全部默认：覆盖清空 + localStorage 键移除。
            page.click('[data-testid="reset-all"]')
            page.wait_for_timeout(120)
            stored = page.evaluate("localStorage.getItem('vibelution.shortcuts.overrides')")
            check("storage key removed", stored is None)
            check("kbd back to default", page.locator('[data-testid="binding-kbd"]').count() >= 2)
            shot("06-reset-all-default.png", "恢复全部默认（覆盖清空）")

            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    (OUT_DIR / "capture-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    failed = [a for a in report["asserts"] if not a["ok"]]
    failed += report["consoleErrors"] + report["pageErrors"]
    print(
        f"[done] shots={len(report['shots'])} asserts={len(report['asserts'])}"
        f" failed={len(failed)} consoleErrors={len(report['consoleErrors'])}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
