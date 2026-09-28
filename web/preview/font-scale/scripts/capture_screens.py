"""预览截图与交互自检 —— python + playwright（无仓库内新依赖，用本机 playwright）。

先自行拉起 vite dev server（端口 5247），对 6 个确定态深链逐个断言 + 截图
（base=14/16/17/18 各一张全页、A/B 对拍一张、dark 一张），再补几条交互流转
（快捷档 / 步进器 / 越界钳制归位），最后关闭。
截图输出到 screenshots/（不入库），同时写 capture-report.json（含断言结果与
console/pageerror 收集；任何 console error 都会让脚本以非零码退出）。

用法：python scripts/capture_screens.py
环境变量：FS_BASE_URL（默认 http://127.0.0.1:5247，设置后不拉起 server）。
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
BASE_URL = os.environ.get("FS_BASE_URL", "http://127.0.0.1:5247")
PAGE_URL = f"{BASE_URL}/preview/font-scale/index.html"
VIEWPORT = {"width": 1512, "height": 945}

# 6 个确定态深链：每个 state 首屏即现目标态。
SHOTS = [
    ("01-base-14", "?base=14", 14, False),
    ("02-base-16", "", 16, False),
    ("03-base-17", "?base=17", 17, False),
    ("04-base-18", "?base=18", 18, False),
    ("05-ab-16-vs-18", "?base=18&mode=ab", 18, False),
    ("06-dark-18", "?base=18&theme=dark", 18, True),
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


def px(value: str) -> float:
    return float(value.replace("px", "").strip())


def assert_probe(page, probe: str, expected_px: float) -> str:
    actual = page.eval_on_selector(
        f'[data-probe="{probe}"]',
        "el => getComputedStyle(el).fontSize",
    )
    if abs(px(actual) - expected_px) > 0.01:
        raise AssertionError(f"probe {probe}: expected {expected_px}px, got {actual}")
    return actual


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    report: dict = {"shots": [], "asserts": [], "consoleErrors": [], "pageErrors": []}

    def note(ok: bool, text: str) -> None:
        report["asserts"].append({"ok": ok, "text": text})
        if not ok:
            raise AssertionError(text)

    server = None
    if "FS_BASE_URL" not in os.environ:
        server = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js",
                "--config",
                "preview/font-scale/vite.config.ts",
            ],
            cwd=str(WEB_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
    try:
        wait_for_server(PAGE_URL)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            page = context.new_page()
            page.set_default_timeout(20000)
            page.on(
                "console",
                lambda msg: report["consoleErrors"].append(msg.text)
                if msg.type == "error"
                else None,
            )
            page.on(
                "pageerror",
                lambda err: report["pageErrors"].append(str(err)),
            )

            for name, query, base, dark in SHOTS:
                page.goto(PAGE_URL + query)
                page.wait_for_selector('[data-probe="settings-label"]')
                root = page.locator("html")

                got_base = root.get_attribute("data-font-base")
                note(got_base == str(base), f"{name}: data-font-base={got_base} (want {base})")

                if name == "05-ab-16-vs-18":
                    # A/B 双栏各自求值：左栏 16（label=15/chat=17）、右栏 18（label=17/chat=19），
                    # 画布/桌宠/终端两侧都固定。assert_probe 只取首个匹配，故 AB 走批量断言。
                    def probe_all(probe: str) -> list:
                        return [
                            px(v)
                            for v in page.eval_on_selector_all(
                                f'[data-probe="{probe}"]',
                                "els => els.map(el => getComputedStyle(el).fontSize)",
                            )
                        ]

                    note(probe_all("settings-label") == [15.0, 17.0],
                         f"{name}: AB settings-label = {probe_all('settings-label')} (want 15/17)")
                    note(probe_all("chat-body") == [17.0, 19.0],
                         f"{name}: AB chat-body = {probe_all('chat-body')} (want 17/19)")
                    canvases = probe_all("canvas-title")
                    note(all(abs(v - 15) < 0.01 for v in canvases) and len(canvases) == 2,
                         f"{name}: AB canvas-title = {canvases} (both 15px)")
                    pets = probe_all("pet-status")
                    note(all(abs(v - 11) < 0.01 for v in pets) and len(pets) == 2,
                         f"{name}: AB pet-status = {pets} (both 11px)")
                    page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=True)
                    report["shots"].append({"name": name, "url": PAGE_URL + query, "base": base})
                    print(f"captured {name}")
                    continue

                # 派生档随基准移动：设置行 label = sm = base−1；聊天正文 = chat = base+1；
                # 阶梯 md 行 = 基准本身。
                note(
                    abs(px(assert_probe(page, "settings-label", base - 1)) - (base - 1)) < 0.01,
                    f"{name}: settings-label = {base - 1}px",
                )
                note(
                    abs(px(assert_probe(page, "chat-body", base + 1)) - (base + 1)) < 0.01,
                    f"{name}: chat-body = {base + 1}px",
                )
                note(
                    abs(px(assert_probe(page, "ladder-md", base)) - base) < 0.01,
                    f"{name}: ladder-md = {base}px",
                )

                # 固定例外纹丝不动：画布标题 15px、桌宠状态 11px、终端 13px。
                note(
                    abs(px(assert_probe(page, "canvas-title", 15)) - 15) < 0.01,
                    f"{name}: canvas-title stays 15px",
                )
                note(
                    abs(px(assert_probe(page, "pet-status", 11)) - 11) < 0.01,
                    f"{name}: pet-status stays 11px",
                )
                note(
                    abs(px(assert_probe(page, "terminal-line", 13)) - 13) < 0.01,
                    f"{name}: terminal-line stays 13px",
                )

                if dark:
                    note(
                        root.get_attribute("data-theme") == "dark",
                        f"{name}: data-theme=dark",
                    )

                page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=True)
                report["shots"].append({"name": name, "url": PAGE_URL + query, "base": base})
                print(f"captured {name}")

            # 交互流转：快捷档 / 步进器 / 越界输入钳制归位。
            page.goto(PAGE_URL)
            page.wait_for_selector('[data-testid="quick-14"]')
            page.click('[data-testid="quick-14"]')
            note(
                page.locator("html").get_attribute("data-font-base") == "14",
                "interaction: quick-14 → base=14",
            )
            page.click('[data-testid="base-stepper-inc"]')
            page.click('[data-testid="base-stepper-inc"]')
            note(
                page.locator("html").get_attribute("data-font-base") == "16",
                "interaction: +2 steps → base=16",
            )
            page.fill('[data-testid="base-stepper-input"]', "99")
            page.press('[data-testid="base-stepper-input"]', "Enter")
            note(
                page.locator("html").get_attribute("data-font-base") == "18",
                "interaction: input 99 clamps to 18",
            )
            page.fill('[data-testid="base-stepper-input"]', "5")
            page.press('[data-testid="base-stepper-input"]', "Enter")
            note(
                page.locator("html").get_attribute("data-font-base") == "14",
                "interaction: input 5 clamps to 14",
            )

            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    report["ok"] = not report["consoleErrors"] and not report["pageErrors"]
    (OUT_DIR / "capture-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if report["consoleErrors"] or report["pageErrors"]:
        print("console/page errors detected:", report["consoleErrors"], report["pageErrors"])
        return 1
    print(f"all asserts passed: {len(report['asserts'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
