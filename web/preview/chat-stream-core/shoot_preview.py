"""Screenshots for the isolated chat-stream-core preview (Wave 1b).

Run from the system Python that has playwright installed:
  python shoot_preview.py

Targets the vite dev server on http://localhost:5199 and saves PNGs into
docs/screenshots/ next to this script's preview directory.
"""
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:5199/"


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: errors.append(msg.text) if msg.type == "error" else None,
        )

        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector("text=A · 现状复刻", timeout=15000)
        # Tab 1: scroll the right column a bit so the virtualizer shows rows.
        time.sleep(1.0)
        page.screenshot(path=str(OUT / "01-compare-initial.png"))

        # Load earlier on the left column to show window growth + anchor.
        page.click("text=加载更早消息（窗口")
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "02-compare-load-earlier.png"))

        # Tab 2: stream simulation, capture a mid-stream frame and final.
        page.click("text=② 流式双模模拟")
        page.click("text=播放模拟流")
        time.sleep(1.4)
        page.screenshot(path=str(OUT / "03-stream-mid.png"))
        # Wait for the run to finish (deterministic script ~4.5s total).
        page.wait_for_selector("text=✓ 已完成", timeout=20000)
        time.sleep(0.6)
        page.screenshot(path=str(OUT / "04-stream-done.png"))

        # Tab 3: projection invariants with fault injection.
        page.click("text=③ 投影不变量演示")
        page.click("text=① 正常序列 ×4")
        page.click("text=② 注入 seq 断档")
        page.wait_for_selector("text=RESUB", timeout=15000)
        time.sleep(0.4)
        page.screenshot(path=str(OUT / "05-projection-gap.png"))

        browser.close()
        if errors:
            print("CONSOLE/PAGE ERRORS:")
            for err in errors[:10]:
                print(" -", err)
            return 1
        print("OK: screenshots saved to", OUT)
        return 0


if __name__ == "__main__":
    sys.exit(main())
