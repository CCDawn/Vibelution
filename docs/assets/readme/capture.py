"""Regenerate README UI images from an isolated Vite server and public fixtures."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5188")
    parser.add_argument("--chromium", help="Optional path to an installed Chromium executable.")
    parser.add_argument("--view", choices=("all", "conversation", "memory"), default="all")
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
                for view in (("conversation", "memory") if args.view == "all" else (args.view,)):
                    for mobile in (False, True):
                        width, height = (390, 820 if view == "conversation" else 780) if mobile else (960, 740 if view == "conversation" else 660)
                        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme="light", timezone_id="Asia/Shanghai")
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        # Defense in depth: even if a fixture fails to intercept fetch,
                        # no product API may be contacted by the screenshot browser.
                        page.route("**/*", lambda route: route.continue_() if (route.request.url.startswith(base + "/") and not urlsplit(route.request.url).path.startswith("/api/")) or route.request.url.startswith("data:") else route.abort())
                        try:
                            page.goto(f"{base}/docs/assets/readme/capture.html?lang={lang}&view={view}", wait_until="networkidle")
                            page.evaluate("document.fonts.ready")
                            page.wait_for_timeout(500)
                            if mobile and view == "memory":
                                page.get_by_role("button").filter(has=page.get_by_text("review-notes.json", exact=True)).click()
                            if errors:
                                raise RuntimeError("Component example failed: " + errors[0])
                            if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
                                raise RuntimeError("Example overflows the viewport.")
                            if view == "conversation":
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
