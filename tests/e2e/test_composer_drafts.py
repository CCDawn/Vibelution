"""Draft recovery through real browser actions, without starting model turns."""
from __future__ import annotations

import json
import time
import uuid
import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]

COMPOSER = 'textarea[aria-label="发送消息"]'
THREAD = 'div[data-agent-thread-message-count]'


def _ready_composer(page, instance, session_id):
    from playwright.sync_api import expect

    page.goto(f"{instance.base_url}/chat?session={session_id}", wait_until="domcontentloaded")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", session_id, timeout=30000)
    expect(page.get_by_text("这条会话还没有可展示的消息。", exact=True).first).to_be_visible(timeout=20000)
    composer = page.locator(COMPOSER).first
    expect(composer).to_be_enabled()
    # Wait for startup draft hydration before creating the draft being tested.
    page.wait_for_timeout(600)
    return composer


def test_actual_typing_survives_immediate_reload(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="draft immediate reload regression")
    composer = _ready_composer(page, e2e_instance, sid)
    marker = "逐字输入后立即刷新仍保留"
    composer.click()
    composer.press_sequentially(marker, delay=20)
    expect(composer).to_have_value(marker)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
    expect(page.locator(COMPOSER).first).to_have_value(marker, timeout=15000)
    assert marker not in json.dumps(fetch_json(e2e_instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)


def test_failed_send_restored_draft_survives_reload(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="failed send draft persistence regression")
    composer = _ready_composer(page, e2e_instance, sid)
    marker = "网络失败恢复后等待三秒刷新"
    blocked = []

    def fail_send(route):
        blocked.append(route.request.url)
        route.abort("internetdisconnected")

    composer.fill(marker)
    page.wait_for_timeout(800)
    page.route(f"**/api/sessions/{sid}/messages", fail_send)
    try:
        page.get_by_role("button", name="发送", exact=True).click()
        expect(page.locator('[role="alert"]').first).to_contain_text("没有发出", timeout=15000)
        expect(composer).to_have_value(marker)
        expect(composer).to_be_enabled()
        page.wait_for_timeout(3000)
        assert len(blocked) == 1
        assert marker not in json.dumps(fetch_json(e2e_instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)
        stored = page.evaluate('() => JSON.parse(localStorage.getItem("vibelution.chat.drafts.v1") || "[]")')
        assert any(row.get("sessionId") == sid and row.get("draft") == marker for row in stored)
    finally:
        page.unroute(f"**/api/sessions/{sid}/messages", fail_send)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(COMPOSER).first).to_have_value(marker, timeout=15000)
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
    assert marker not in json.dumps(fetch_json(e2e_instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)


def test_session_drafts_stay_separate_on_full_navigation(page, e2e_instance):
    from playwright.sync_api import expect

    a = create_session(e2e_instance.port, title="draft isolation A")
    b = create_session(e2e_instance.port, title="draft isolation B")
    _ready_composer(page, e2e_instance, a).fill("只属于会话 A")
    composer_b = _ready_composer(page, e2e_instance, b)
    expect(composer_b).to_have_value("")
    composer_b.fill("只属于会话 B")
    expect(_ready_composer(page, e2e_instance, a)).to_have_value("只属于会话 A")
    expect(_ready_composer(page, e2e_instance, b)).to_have_value("只属于会话 B")


def _assert_late_failure_preserves_edit(page, instance, *, clear_draft):
    from playwright.sync_api import expect

    sid = create_session(instance.port, title="late send failure draft regression")
    composer = _ready_composer(page, instance, sid)
    original = "已发送但仍在等待的旧草稿"
    newer = "等待期间逐字输入的新草稿"
    expected = "" if clear_draft else newer
    pending = []
    captured = []
    pattern = f"**/api/sessions/{sid}/messages"

    def hold_send(route):
        captured.append(route.request.url)
        pending.append(route)

    composer.fill(original)
    page.route(pattern, hold_send)
    try:
        page.get_by_role("button", name="发送", exact=True).click()
        deadline = time.monotonic() + 10
        while not pending and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert len(captured) == 1, "The original submission must reach the held transport"
        expect(composer).to_have_value("")
        expect(composer).to_be_enabled()
        composer.click()
        composer.press_sequentially(newer, delay=20)
        expect(composer).to_have_value(newer)
        if clear_draft:
            composer.press("ControlOrMeta+A")
            composer.press("Backspace")
            expect(composer).to_have_value("")

        pending.pop().abort("internetdisconnected")
        expect(page.locator('[role="alert"]').first).to_contain_text("没有发出", timeout=15000)
        expect(composer).to_have_value(expected)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        assert len(captured) == 1
        assert original not in json.dumps(fetch_json(instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)

        # Verify the user's latest choice also survives document replacement,
        # including an intentional empty draft.
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(expected, timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        stored = page.evaluate('() => JSON.parse(localStorage.getItem("vibelution.chat.drafts.v1") || "[]")')
        rows = [row for row in stored if row.get("sessionId") == sid]
        assert (rows[0].get("draft", "") if rows else "") == expected
        assert original not in json.dumps(fetch_json(instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)
    finally:
        for route in pending:
            route.abort("internetdisconnected")
        page.unroute(pattern, hold_send)


def test_late_send_failure_keeps_newer_draft_after_reload(page, e2e_instance):
    _assert_late_failure_preserves_edit(page, e2e_instance, clear_draft=False)


def test_late_send_failure_keeps_intentional_clear_after_reload(page, e2e_instance):
    _assert_late_failure_preserves_edit(page, e2e_instance, clear_draft=True)


def test_late_send_failure_stays_in_original_session_after_switch(page, e2e_instance):
    from playwright.sync_api import expect

    case_id = uuid.uuid4().hex[:8]
    title_a = f"等待失败的会话 A {case_id}"
    title_b = f"继续编辑的会话 B {case_id}"
    b = create_session(e2e_instance.port, title=title_b)
    a = create_session(e2e_instance.port, title=title_a)
    original = "只应恢复到会话 A 的发送文字"
    newer = "切换后只属于会话 B 的新草稿"
    composer = _ready_composer(page, e2e_instance, a)
    pending = []
    captured = []
    pattern = "**/api/sessions/*/messages"

    def hold_send(route):
        captured.append({"url": route.request.url, "method": route.request.method})
        pending.append(route)

    def switch_session(title, sid):
        page.get_by_role("button").filter(has=page.get_by_text(title, exact=True)).first.click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        assert page.evaluate("() => window.__draftIsolationDocument") == "same-document", "Switch must retain the pending request in the same document"
        return page.locator(COMPOSER).first

    composer.fill(original)
    page.evaluate("() => { window.__draftIsolationDocument = 'same-document'; }")
    page.route(pattern, hold_send)
    try:
        page.get_by_role("button", name="发送", exact=True).click()
        deadline = time.monotonic() + 10
        while not pending and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert len(captured) == 1 and captured[0]["method"] == "POST"
        assert captured[0]["url"].endswith(f"/api/sessions/{a}/messages")
        expect(composer).to_have_value("")
        page.wait_for_function("sid => !JSON.parse(localStorage.getItem('vibelution.chat.drafts.v1') || '[]').some(row => row.sessionId === sid && row.draft)", arg=a)

        composer_b = switch_session(title_b, b)
        expect(composer_b).to_have_value("")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        composer_b.click()
        composer_b.press_sequentially(newer, delay=20)
        expect(composer_b).to_have_value(newer)
        pending.pop().abort("internetdisconnected")
        # A's persisted recovery proves its late failure has been processed
        # before inspecting the still-active B session.
        page.wait_for_function("({sid, draft}) => JSON.parse(localStorage.getItem('vibelution.chat.drafts.v1') || '[]').some(row => row.sessionId === sid && row.draft === draft)", arg={"sid": a, "draft": original})
        expect(composer_b).to_have_value(newer)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", b)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        expect(page.locator('[role="alert"]').filter(has_text="没有发出")).to_have_count(0)
        # Selecting a session dismisses its transient composer error; the
        # restored text and withdrawn optimistic message must remain correct.
        expect(switch_session(title_a, a)).to_have_value(original)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        expect(switch_session(title_b, b)).to_have_value(newer)
        assert len(captured) == 1, "Switching and recovery must not submit B's draft"

        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", b, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(newer, timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        stored = page.evaluate('() => JSON.parse(localStorage.getItem("vibelution.chat.drafts.v1") || "[]")')
        drafts = {row.get("sessionId"): row.get("draft") for row in stored}
        assert drafts.get(a) == original and drafts.get(b) == newer
        for sid in (a, b):
            detail = json.dumps(fetch_json(e2e_instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)
            assert original not in detail and newer not in detail
    finally:
        for route in pending:
            route.abort("internetdisconnected")
        page.unroute(pattern, hold_send)
