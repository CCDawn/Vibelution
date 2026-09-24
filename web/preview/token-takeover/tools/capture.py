"""Capture screenshots for the token-takeover preview and verify takeover behavior.

Run from this directory after `npm run dev`:
    python tools/capture.py

Outputs PNGs into ./screenshots and prints a pass/fail summary.
Exits nonzero on console errors or failed takeover assertions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5185/"
OUT_DIR = Path(__file__).resolve().parent.parent / "screenshots"

# (name, selector or None for viewport-top, extra JS before shot)
SHOTS: list[tuple[str, str | None, str]] = [
    ("01-overview-ab.png", None, ""),
    (
        "02-dense-chips.png",
        "#dense-chips",
        "",
    ),
    (
        "03-mapping-table.png",
        "#mapping-table",
        "",
    ),
    (
        "04-global-takeover-on.png",
        None,
        "document.getElementById('toggle-takeover').click();"
        "document.getElementById('toggle-lh').click();",
    ),
]

# Computed-style assertions: (scope selector, probe class, expected font-size, expected line-height px)
# Native defaults at 16px root: xs 12px/16px, sm 14px/20px, base 16px/24px, lg 18px/28px, xl 20px/28px.
# Takeover (size-only): xs 12px/16px, sm 14px/20px, base 16px/24px, lg 18px/28px, xl 19px/26.6px(1.4*19).
# With lh pairing on: xs/sm 1.25, base 1.58, lg 1.375, xl 1.25.
EXPECTED_NATIVE = {
    "text-xs": ("12px", "16px"),
    "text-sm": ("14px", "20px"),
    "text-base": ("16px", "24px"),
    "text-lg": ("18px", "28px"),
    "text-xl": ("20px", "28px"),
}

TAKEOVER_SIZES = {
    "text-xs": "12px",
    "text-sm": "14px",
    "text-base": "16px",
    "text-lg": "18px",
    "text-xl": "19px",  # nearest vui slot: --vui-font-title
}


def computed_style(page, scope: str, cls: str) -> tuple[str, str]:
    return page.evaluate(
        """([scope, cls]) => {
            const root = document.querySelector(scope);
            const el = root.querySelector('.' + cls);
            const cs = getComputedStyle(el);
            return [cs.fontSize, cs.lineHeight];
        }""",
        [scope, cls],
    )


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    failures: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.on(
            "console",
            lambda msg: console_errors.append(f"[console.{msg.type}] {msg.text}") if msg.type == "error" else None,
        )
        page.on("pageerror", lambda err: page_errors.append(f"[pageerror] {err}"))

        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(600)

        # --- behavior assertions: native scope pins Tailwind v4 defaults ---
        for cls, (size, lh) in EXPECTED_NATIVE.items():
            got = computed_style(page, ".native-scope", cls)
            if got[0] != size:
                failures.append(f"native-scope {cls}: font-size {got[0]} != {size}")
            if got[1] != lh:
                failures.append(f"native-scope {cls}: line-height {got[1]} != {lh}")

        # --- takeover scope (off-by-default page, scoped class active) ---
        for cls, size in TAKEOVER_SIZES.items():
            got = computed_style(page, ".takeover-scope", cls)
            if got[0] != size:
                failures.append(f"takeover-scope {cls}: font-size {got[0]} != {size}")
        # size-only mode: native line-height is a unitless ratio, so it tracks the
        # retargeted font size (zero-shift slots keep identical px; text-xl 28 -> 26.6).
        TAKEOVER_RATIO_LH = {
            "text-xs": "16px",
            "text-sm": "20px",
            "text-base": "24px",
            "text-lg": "28px",
            "text-xl": "26.6px",  # 19px * native ratio 1.4
        }
        for cls, lh in TAKEOVER_RATIO_LH.items():
            got = computed_style(page, ".takeover-scope", cls)
            if abs(float(got[1].replace("px", "")) - float(lh.replace("px", ""))) > 0.15:
                failures.append(f"takeover-scope {cls}: size-only line-height {got[1]} != {lh}")

        # --- global toggle: whole page retargets, native scope stays pinned ---
        page.evaluate("document.getElementById('toggle-takeover').click()")
        page.wait_for_timeout(120)
        got_xl_native = computed_style(page, ".native-scope", "text-xl")
        if got_xl_native[0] != "20px":
            failures.append(f"native-scope text-xl under global takeover: {got_xl_native[0]} != 20px")
        body_xl = page.evaluate(
            """() => {
                const probe = document.createElement('span');
                probe.className = 'text-xl';
                document.body.appendChild(probe);
                const size = getComputedStyle(probe).fontSize;
                probe.remove();
                return size;
            }"""
        )
        if body_xl != "19px":
            failures.append(f"body-level text-xl under global takeover: {body_xl} != 19px")

        # --- lh pairing mode ---
        page.evaluate("document.getElementById('toggle-lh').click()")
        page.wait_for_timeout(120)
        got = computed_style(page, ".takeover-scope", "text-sm")
        expected_pair_lh = 14 * 1.25  # 17.5px
        if abs(float(got[1].replace("px", "")) - expected_pair_lh) > 0.6:
            failures.append(f"takeover-scope text-sm lh-paired: {got[1]} != ~{expected_pair_lh}px")

        page.evaluate("document.getElementById('toggle-lh').click()")  # pairing off
        page.evaluate("document.getElementById('toggle-takeover').click()")  # global takeover off

        # --- screenshots (scoped A/B visible in every shot) ---
        for name, selector, before_js in SHOTS:
            if before_js:
                page.evaluate(before_js)
                page.wait_for_timeout(200)
            if selector:
                page.locator(selector).scroll_into_view_if_needed()
                page.wait_for_timeout(120)
                page.locator(selector).screenshot(path=str(OUT_DIR / name))
            else:
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(120)
                page.screenshot(path=str(OUT_DIR / name))
            print(f"shot: {name}")

        browser.close()

    report = {
        "console_errors": console_errors,
        "page_errors": page_errors,
        "assertion_failures": failures,
        "passed": not (console_errors or page_errors or failures),
    }
    (OUT_DIR / "capture-report.json").write_text(json.dumps(report), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
