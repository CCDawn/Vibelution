"""Pointer movement over sidebar tooltips while the composer retains keyboard focus."""
from __future__ import annotations

import json
import uuid
from itertools import pairwise
from urllib.parse import urlparse

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


@pytest.mark.parametrize("long_title", [False, True], ids=["short-title", "wrapped-title"])
def test_hover_then_actual_pointer_click_preserves_session_drafts(page, e2e_instance, tmp_path, long_title):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    prefix = "检查会话提示浮层与相邻按钮的实际鼠标点击" * (3 if long_title else 1)
    titles = [f"{prefix} {label} {suffix}" for label in "ABC"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    submitted = []

    def capture_submission(request):
        path = urlparse(request.url).path
        if request.method == "POST" and path.startswith("/api/sessions/") and path.endswith("/messages"):
            submitted.append(path)

    def block_submission(route):
        if route.request.method == "POST":
            route.abort()
        else:
            route.continue_()

    page.on("request", capture_submission)
    page.route("**/api/sessions/*/messages", block_submission)
    _ready_composer(page, e2e_instance, sessions[0])
    drafts = [f"会话 {label} 的鼠标与键盘草稿 {suffix}" for label in "ABC"]

    sequence = [0, 1, 2, 0, 2, 1, 0]
    edited = set()
    for index, target_index in pairwise(sequence):
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[index])
        composer = page.locator(COMPOSER).first
        composer.click()
        composer.press("ControlOrMeta+A")
        page.keyboard.type(drafts[index], delay=5)
        edited.add(index)
        row = page.get_by_role("button").filter(has=page.get_by_text(titles[index], exact=True)).first
        row.hover()
        expect(composer).to_be_focused()
        tip = page.locator('[data-vui="tooltip-content"]').filter(has_text=titles[index]).first
        expect(tip).to_be_visible(timeout=5000)
        target = page.get_by_role("button").filter(has=page.get_by_text(titles[target_index], exact=True)).first
        target.scroll_into_view_if_needed()
        box = target.bounding_box()
        assert box is not None
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        target.evaluate("""original => {
          window.__pointerTrace = [];
          const events = ['pointerover', 'pointerdown', 'mousedown', 'focusin', 'pointerup', 'mouseup', 'click'];
          const record = event => {
            const button = event.target.closest?.('button');
            if (window.__pointerTrace.length < 24) window.__pointerTrace.push({
              event: event.type, button: button?.textContent?.slice(0, 120),
              hit: button ? undefined : event.target.outerHTML?.slice(0, 200),
              same: button === original, connected: original.isConnected,
              prevented: event.defaultPrevented, time: Math.round(performance.now())
            });
          };
          events.forEach(name => document.addEventListener(name, record, true));
          window.__clearPointerTrace = () => events.forEach(name => document.removeEventListener(name, record, true));
        }""")
        page.mouse.move(x, y, steps=5)
        page.mouse.down()
        page.mouse.up()
        try:
            expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[target_index], timeout=15000)
        except AssertionError:
            diagnostics = page.evaluate("""({x, y}) => ({
              hit: document.elementFromPoint(x, y)?.outerHTML.slice(0, 300),
              events: window.__pointerTrace,
              focused: document.activeElement?.getAttribute('aria-label'),
              tips: Array.from(document.querySelectorAll('[data-vui="tooltip-content"]')).map(el => ({
                text: el.textContent?.slice(0, 240), rect: el.getBoundingClientRect().toJSON()
              }))
            })""", {"x": x, "y": y})
            screenshot = tmp_path / "sidebar-pointer-failure.png"
            page.screenshot(path=str(screenshot))
            print(f"[pointer-journey] {json.dumps(diagnostics, ensure_ascii=False)} screenshot={screenshot}")
            raise
        finally:
            page.evaluate("window.__clearPointerTrace?.()")
        expect(page.locator(COMPOSER).first).to_have_value(drafts[target_index] if target_index in edited else "")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[0], timeout=30000)
    expect(page.locator(COMPOSER).first).to_have_value(drafts[0], timeout=15000)
    for index in [1, 2, 0]:
        page.get_by_role("button").filter(has=page.get_by_text(titles[index], exact=True)).first.click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[index], timeout=15000)
        expect(page.locator(COMPOSER).first).to_have_value(drafts[index], timeout=15000)
    assert submitted == [], f"Draft navigation unexpectedly submitted messages: {submitted}"
    page.remove_listener("request", capture_submission)
    page.unroute("**/api/sessions/*/messages", block_submission)
    _assert_no_turns(e2e_instance, sessions, drafts)
