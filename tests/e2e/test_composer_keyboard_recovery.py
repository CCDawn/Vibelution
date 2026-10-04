"""Keyboard delivery and real browser offline recovery, without model turns.

The composition case exercises browser events, not a native Windows IME.
All online message/guidance requests are stopped at the transport boundary.
"""
from __future__ import annotations

import json
import time

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


def _assert_not_recorded(instance, sid, *drafts):
    detail = json.dumps(fetch_json(instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)
    for draft in drafts:
        assert draft not in detail, "Blocked keyboard submission must not reach server transcript"


def _wait_pending(page, pending):
    deadline = time.monotonic() + 10
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert len(pending) == 1


def test_shift_enter_and_composition_do_not_submit_but_plain_enter_does(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="keyboard multiline and composition")
    composer = _ready_composer(page, e2e_instance, sid)
    captured = []
    pattern = f"**/api/sessions/{sid}/messages"

    def fail_send(route):
        captured.append(route.request.post_data_json)
        route.abort("internetdisconnected")

    page.route(pattern, fail_send)
    try:
        composer.click()
        composer.press_sequentially("键盘第一行", delay=20)
        composer.press("Shift+Enter")
        composer.press_sequentially("第二行确认中文", delay=20)
        draft = "键盘第一行\n第二行确认中文"
        expect(composer).to_have_value(draft)
        # Browser composition signal must yield Enter delivery. This does not
        # pretend to operate or verify the OS input method / candidate window.
        composer.dispatch_event("compositionstart", {"data": "中文"})
        composer.dispatch_event("keydown", {"key": "Enter", "code": "Enter", "isComposing": True, "bubbles": True, "cancelable": True})
        page.wait_for_timeout(300)
        expect(composer).to_have_value(draft)
        assert captured == []
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        composer.dispatch_event("compositionend", {"data": "中文"})
        composer.press("Enter")
        expect(page.locator('[role="alert"]').filter(has_text="没有发出").first).to_be_visible(timeout=15000)
        expect(composer).to_have_value(draft)
        assert len(captured) == 1 and captured[0]["content"] == draft
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        _assert_not_recorded(e2e_instance, sid, draft)
    finally:
        page.unroute(pattern, fail_send)


def test_pending_keyboard_submit_keeps_new_input_and_blocks_early_delivery(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="pending keyboard delivery guard")
    composer = _ready_composer(page, e2e_instance, sid)
    original, newer = "等待确认的键盘发送", "请求等待时编辑的新内容"
    pending, captured = [], []
    pattern = f"**/api/sessions/{sid}/**"

    def hold_delivery(route):
        if route.request.method == "POST" and route.request.url.rsplit("/", 1)[-1] in {"messages", "guidance"}:
            captured.append({"url": route.request.url, "body": route.request.post_data_json})
            pending.append(route)
        else:
            route.continue_()

    page.route(pattern, hold_delivery)
    try:
        composer.fill(original)
        composer.press("Enter")
        _wait_pending(page, pending)
        expect(composer).to_have_value("")
        expect(composer).to_be_enabled()
        # Repeated Enter with an empty composer, then a new draft while the
        # original acceptance is still withheld, must not submit or steer it.
        composer.press("Enter")
        composer.press("Enter")
        composer.press_sequentially(newer, delay=20)
        composer.press("Enter")
        page.wait_for_timeout(500)
        expect(composer).to_have_value(newer)
        assert len(captured) == 1, "No second message or guidance before initial acceptance"
        assert captured[0]["url"].endswith(f"/api/sessions/{sid}/messages")
        assert captured[0]["body"]["content"] == original
        pending.pop().abort("internetdisconnected")
        expect(page.locator('[role="alert"]').filter(has_text="没有发出").first).to_be_visible(timeout=15000)
        expect(composer).to_have_value(newer)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(newer, timeout=15000)
        assert len(captured) == 1
        _assert_not_recorded(e2e_instance, sid, original, newer)
    finally:
        for route in pending:
            route.abort("internetdisconnected")
        page.unroute(pattern, hold_delivery)


def test_offline_keyboard_failure_keeps_edit_and_requires_explicit_retry(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="browser offline keyboard retry")
    composer = _ready_composer(page, e2e_instance, sid)
    original, newer = "离线发送的第一份草稿", "联网前改写的新草稿"
    target = f"{e2e_instance.base_url}/api/sessions/{sid}/messages"
    requests, failures, retries = [], [], []
    resource_failures = []

    def observe(request):
        if request.url == target and request.method == "POST":
            requests.append(request.post_data_json)

    def observe_failure(request):
        if request.url == target and request.method == "POST":
            failures.append(request.failure)
        if request.resource_type in {"script", "document"}:
            resource_failures.append({"type": request.resource_type, "url": request.url, "error": request.failure})

    def fail_retry(route):
        retries.append(route.request.post_data_json)
        route.abort("failed")  # Retry boundary is exercised without running a model.

    page.on("request", observe)
    page.on("requestfailed", observe_failure)
    try:
        composer.fill(original)
        page.evaluate("() => { window.__offlineDocument = 'original-document'; }")
        page.context.set_offline(True)
        composer.press("Enter")
        expect(page.locator('[role="alert"]').filter(has_text="没有发出").first).to_be_visible(timeout=15000)
        expect(composer).to_have_value(original)
        assert page.evaluate("() => window.__offlineDocument") == "original-document", "Offline asset failure must not automatically reload the page"
        expect(composer).to_be_enabled()
        assert len(requests) == 1 and requests[0]["content"] == original
        assert any("INTERNET_DISCONNECTED" in str(error) for error in failures)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        composer.press("ControlOrMeta+A")
        composer.press_sequentially(newer, delay=20)
        expect(composer).to_have_value(newer)
        # Install the safety boundary before reconnecting: a regression in
        # automatic resubmit would be counted and cannot invoke a real model.
        page.route(target, fail_retry)
        page.context.set_offline(False)
        page.wait_for_timeout(1000)
        assert len(requests) == 1 and retries == [], "Reconnection must not resend a rejected draft"
        assert page.evaluate("() => window.__offlineDocument") == "original-document"
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        composer = page.locator(COMPOSER).first
        expect(composer).to_have_value(newer, timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        assert len(requests) == 1 and retries == []
        composer.press("Enter")
        expect(page.locator('[role="alert"]').filter(has_text="没有发出").first).to_be_visible(timeout=15000)
        expect(composer).to_have_value(newer)
        assert len(requests) == 2 and len(retries) == 1
        assert requests[1]["content"] == retries[0]["content"] == newer
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        _assert_not_recorded(e2e_instance, sid, original, newer)
    except Exception:
        print("[e2e offline diagnostic] " + json.dumps({
            "browser": page.evaluate("""() => ({
              online: navigator.onLine,
              url: location.href, title: document.title, documentMarker: window.__offlineDocument,
              body: document.body?.textContent?.slice(0, 400),
              composer: Array.from(document.querySelectorAll('textarea[aria-label="发送消息"]')).map(el => ({value: el.value, disabled: el.disabled})),
              alerts: Array.from(document.querySelectorAll('[role="alert"]')).map(el => el.textContent?.slice(0, 200)),
              threadCounts: Array.from(document.querySelectorAll('[data-agent-thread-message-count]')).map(el => el.getAttribute('data-agent-thread-message-count')),
              actionButtons: Array.from(document.querySelectorAll('button[aria-label]')).map(el => ({name: el.getAttribute('aria-label'), disabled: el.disabled})).filter(el => /发送|终止|引导|排队/.test(el.name))
            })"""), "requestContents": [row.get("content") for row in requests[:5]], "failures": failures[:5], "retryContents": [row.get("content") for row in retries[:5]],
            "resourceFailures": resource_failures[:8],
        }, ensure_ascii=False))
        raise
    finally:
        page.context.set_offline(False)
        page.unroute(target, fail_retry)
        page.remove_listener("request", observe)
        page.remove_listener("requestfailed", observe_failure)
