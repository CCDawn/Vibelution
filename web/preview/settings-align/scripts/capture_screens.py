"""预览截图与交互自检 —— python + playwright（无仓库内新依赖，用本机 playwright）。

先自行拉起 vite dev server（端口 5187），对 7 个确定态深链逐个断言 + 截图，
再补几条交互流转（密度切换/模式切换/保存流转/离开确认），最后关闭。
截图输出到 screenshots/（不入库），同时写 capture-report.json（含断言结果与
console/pageerror 收集；任何 console error 都会让脚本以非零码退出）。

用法：python scripts/capture_screens.py
环境变量：SSA_BASE_URL（默认 http://127.0.0.1:5187，设置后不拉起 server）。
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
BASE_URL = os.environ.get("SSA_BASE_URL", "http://127.0.0.1:5187")
PAGE_URL = f"{BASE_URL}/preview/settings-align/index.html"
VIEWPORT = {"width": 1512, "height": 945}

# 7 个确定态深链：每个 state 首屏即现目标态。
STATES = [
    ("01-view-rows", "view-rows", "查看态·行列表（新密度）"),
    ("02-view-cards", "view-cards", "查看态·卡片流（现状密度对比）"),
    ("03-edit-clean", "edit-clean", "编辑态·干净（无变更）"),
    ("04-edit-dirty", "edit-dirty", "编辑态·脏（已生效+待保存徽标+保存条计数）"),
    ("05-json-error", "json-error", "json 实时校验·红边+错误行列定位"),
    ("06-list-invalid", "list-invalid", "list 逐行校验·非法行行号报错"),
    ("07-saved-toast", "saved", "保存流转完成·徽标清除+toast"),
]


def wait_for_server(url: str, timeout_s: float = 90.0) -> None:
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
    if "SSA_BASE_URL" not in os.environ:
        server = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js",
                "--config",
                "preview/settings-align/vite.config.ts",
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
            page.set_default_timeout(15000)
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
                path = OUT_DIR / f"{name}.png"
                page.screenshot(path=str(path), full_page=True)
                report["shots"].append({"file": f"{name}.png", "label": label})
                print(f"[shot] {name}.png — {label}")

            # ---- 逐确定态截图与断言 ----
            for shot_name, state, label in STATES:
                page.goto(f"{PAGE_URL}?state={state}")
                page.wait_for_selector('[data-testid="settings-group"], [data-testid="settings-cards"]')
                if state == "view-rows":
                    check("view-rows: 行列表组卡渲染", page.locator('[data-testid="settings-group"]').count() == 1)
                    check("view-rows: 7 行", page.locator("[data-vui-settings-row]").count() == 7)
                    check("view-rows: 徽标默认无", page.locator("[data-vui-status]").count() == 0)
                    check("view-rows: 保存条计数 0", "0" in page.locator('[data-testid="save-count"]').inner_text())
                elif state == "view-cards":
                    check("view-cards: 卡片流渲染", page.locator('[data-testid="settings-cards"]').count() == 1)
                    check("view-cards: 7 张卡", page.locator("[data-testid='settings-cards'] > div").count() == 7)
                elif state == "edit-clean":
                    check("edit-clean: 控件渲染（checkbox）", page.locator('[data-testid^="control-context_compression.enabled"]').count() >= 1)
                    check("edit-clean: 无待保存", "0" in page.locator('[data-testid="save-count"]').inner_text())
                    check("edit-clean: 保存按钮禁用", page.locator('[data-testid="save-all"]').is_disabled())
                elif state == "edit-dirty":
                    check(
                        "edit-dirty: 即时字段=已生效徽标",
                        page.locator('[data-testid="badge-context_compression.micro_compact_enabled"][data-vui-status="applied"]').count() == 1,
                    )
                    check(
                        "edit-dirty: 草稿字段=待保存徽标",
                        page.locator('[data-testid="badge-context_compression.max_token_limit"][data-vui-status="pending"]').count() == 1,
                    )
                    check("edit-dirty: 保存条计数 1", "1" in page.locator('[data-testid="save-count"]').inner_text())
                elif state == "json-error":
                    check("json-error: 红边 aria-invalid", page.locator('[data-testid^="editor-context_compression.summary_chars"][aria-invalid="true"]').count() == 1)
                    check("json-error: 行内错误含行列", "第" in page.locator('[data-testid="json-status"]').inner_text())
                    check("json-error: 无 ✓ 提示", "✓" not in page.locator('[data-testid="json-status"]').inner_text())
                elif state == "list-invalid":
                    check("list-invalid: 行号错误列表", page.locator('[data-testid="list-errors"] li').count() == 2)
                    check("list-invalid: 文本域标红", page.locator('[data-testid^="editor-context_compression.micro_compact_tool_whitelist"][aria-invalid="true"]').count() == 1)
                    check("list-invalid: 统计含 2 项非法", "2" in page.locator('[data-testid="list-stats"]').inner_text())
                elif state == "saved":
                    check("saved: toast 可见", page.locator('[data-testid="toast"]').count() == 1)
                    check("saved: toast 文案", "已保存到外部配置" in page.locator('[data-testid="toast"]').inner_text())
                    check("saved: 徽标清除", page.locator("[data-vui-status]").count() == 0)
                    check("saved: 保存条计数 0", "0" in page.locator('[data-testid="save-count"]').inner_text())
                shot(shot_name, label)

            # ---- 交互流转（在干净编辑态上操作） ----
            page.goto(f"{PAGE_URL}?state=edit-dirty")
            page.wait_for_selector('[data-testid="settings-group"]')

            # 密度 A/B：行列表 → 卡片流
            page.click('[data-testid="density-cards"]')
            check("交互: 切卡片流", page.locator('[data-testid="settings-cards"]').count() == 1)
            page.click('[data-testid="density-rows"]')
            check("交互: 切回行列表", page.locator('[data-testid="settings-group"]').count() == 1)

            # 模式切换：编辑 → 查看（徽标仍在）
            page.click('[data-testid="mode-view"]')
            check(
                "交互: 查看态徽标保留",
                page.locator('[data-testid="badge-context_compression.micro_compact_enabled"]').count() == 1,
            )
            page.click('[data-testid="mode-edit"]')

            # 保存流转：保存 → 徽标清除 → toast
            page.click('[data-testid="save-all"]')
            page.wait_for_selector('[data-testid="toast"]')
            check("交互: 保存 toast", "已保存到外部配置" in page.locator('[data-testid="toast"]').inner_text())
            check("交互: 保存后徽标清除", page.locator("[data-vui-status]").count() == 0)
            check("交互: 保存后计数 0", "0" in page.locator('[data-testid="save-count"]').inner_text())

            # 离开确认（再造一条草稿：向已保存的阈值填入新值 25000）
            page.fill('[data-testid="editor-context_compression.max_token_limit"]', "25000")
            check("交互: 计数回到 1", "1" in page.locator('[data-testid="save-count"]').inner_text())
            page.click('[data-testid="leave-simulate"]')
            page.wait_for_selector("[role='dialog']")
            check("交互: 离开弹窗三按钮", page.locator("[role='dialog'] button").count() >= 3)
            page.click('[data-testid="leave-stay"]')
            # Radix 关闭有退场动画：等弹窗隐藏/卸载后再断言。
            page.wait_for_selector("[role='dialog']", state="hidden")
            check("交互: 留下后无弹窗", page.locator("[role='dialog']").count() == 0)
            check("交互: 留下后草稿仍在", "1" in page.locator('[data-testid="save-count"]').inner_text())

            # 放弃流转
            page.click('[data-testid="discard-all"]')
            page.wait_for_selector('[data-testid="toast"]:has-text("已放弃")')
            check("交互: 放弃后计数 0", "0" in page.locator('[data-testid="save-count"]').inner_text())

            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except Exception:
                server.kill()

    report_path = OUT_DIR / "capture-report.json"
    # newline="\n"：禁用 Windows CRLF 转换（git diff --check 会把 \r 记为尾随空白）。
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    failed = [a for a in report["asserts"] if not a["ok"]]
    print(f"[report] {report_path} — asserts={len(report['asserts'])} failed={len(failed)}")
    if failed or report["consoleErrors"] or report["pageErrors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
