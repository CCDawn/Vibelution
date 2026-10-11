"""Regenerate README UI images from an isolated Vite server and public fixtures."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5188")
    parser.add_argument("--chromium", help="Optional path to an installed Chromium executable.")
    parser.add_argument("--view", choices=("all", "workbench", "workbench-overview", "conversation", "memory"), default="all")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    origin = urlsplit(base)
    if origin.scheme != "http" or origin.hostname != "127.0.0.1" or origin.port != 5188 or origin.path or origin.query or origin.fragment or origin.username or origin.password:
        parser.error("--base-url must be the isolated http://127.0.0.1:5188 preview origin.")
    assets = Path(__file__).resolve().parent
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({"executable_path": args.chromium} if args.chromium else {}))
        try:
            for lang in ("zh", "en"):
                for view in (("workbench", "workbench-overview", "conversation", "memory") if args.view == "all" else (args.view,)):
                    for mobile in (False, True):
                        if view == "workbench-overview" and mobile:
                            continue
                        is_workbench = view.startswith("workbench")
                        sizes = {"workbench": ((960, 820), (390, 900)), "workbench-overview": ((1440, 900), (390, 1000)), "conversation": ((960, 740), (390, 820)), "memory": ((960, 660), (390, 780))}
                        width, height = sizes[view][int(mobile)]
                        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme="light", timezone_id="Asia/Shanghai")
                        if is_workbench:
                            page.add_init_script('localStorage.setItem("vibelution.pane-layouts.v1", JSON.stringify({chat:{left:260,right:340}}))')
                            if view == "workbench" and not mobile:
                                page.add_init_script('localStorage.setItem("vibelution.workbench.font-base-px", "18")')
                        errors = []
                        page.on("pageerror", lambda error, scene_errors=errors: scene_errors.append(str(error)))
                        # Defense in depth: even if a fixture fails to intercept fetch,
                        # no product API may be contacted by the screenshot browser.
                        page.route("**/*", lambda route: route.continue_() if (route.request.url.startswith(base + "/") and not urlsplit(route.request.url).path.startswith("/api/")) or route.request.url.startswith("data:") else route.abort())
                        try:
                            entry = "workbench-capture.html" if is_workbench else "capture.html"
                            page.goto(f"{base}/docs/assets/readme/{entry}?lang={lang}&view={view}", wait_until="domcontentloaded" if is_workbench else "networkidle", timeout=60000)
                            if is_workbench:
                                page.get_by_role("heading", name="Keyboard guide drafted" if lang == "en" else "键盘操作说明已整理", exact=True).wait_for(state="visible")
                            page.evaluate("document.fonts.ready")
                            page.wait_for_timeout(500)
                            if mobile and view == "memory":
                                page.get_by_role("button").filter(has=page.get_by_text("review-notes.json", exact=True)).click()
                            if view == "memory":
                                next_check = page.get_by_text("Try the keyboard flow in a browser and confirm focus returns." if lang == "en" else "在浏览器走一遍键盘流程，核对焦点返回。", exact=False).last
                                next_check.wait_for(state="visible")
                                if next_check.bounding_box()["y"] + next_check.bounding_box()["height"] > height - 35:
                                    raise RuntimeError("The selected memory note is cut off.")
                            if is_workbench:
                                page.locator("textarea").wait_for(state="visible")
                                shell = page.locator("[data-chat-status-rail]")
                                if view == "workbench-overview" and shell.get_attribute("data-chat-responsive-mode") != "wide":
                                    raise RuntimeError("The desktop workbench is not using three docked panes.")
                                if view == "workbench-overview" and shell.get_attribute("data-chat-status-rail") == "collapsed":
                                    page.get_by_role("button", name="Side" if lang == "en" else "侧栏", exact=True).click()
                                processed = page.get_by_text("Processed" if lang == "en" else "已处理", exact=True)
                                if processed.count():
                                    processed.click()
                                for summary in page.locator(".vui-components-conversation-tool-activity.group > summary").all():
                                    if summary.locator("..").get_attribute("open") is None:
                                        summary.click()
                                # Use native scroll positions to show the additions, not Git metadata.
                                page.locator('[aria-label="文件变化"], [aria-label="File diff"]').evaluate_all("els => els.forEach(el => { el.scrollTop = 120; })")
                                page.mouse.move(0, 0)
                                page.wait_for_timeout(350)
                            if errors:
                                raise RuntimeError("Component example failed: " + errors[0])
                            if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
                                raise RuntimeError("Example overflows the viewport.")
                            if view == "conversation" or is_workbench:
                                page.locator("textarea").wait_for(state="visible")
                                # Keep the full exchange, including both identities, in frame.
                                timeline = page.locator(".timeline")
                                timeline.evaluate("el => { el.scrollTop = 0; }")
                                if timeline.evaluate("el => el.scrollHeight > el.clientHeight + 2"):
                                    raise RuntimeError("Conversation does not fit the documentation image.")
                            suffix = ".mobile" if mobile else ""
                            output = assets / f"{view}{suffix}.{lang}.png"
                            page.screenshot(path=str(output))
                            print(output.name)
                        finally:
                            page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
