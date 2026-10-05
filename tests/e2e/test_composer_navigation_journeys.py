"""New browser journeys around immediate navigation and failed submissions.

Use the real isolated backend for session setup/readback. Message submission
errors are injected at the browser transport so no model turn is started.
"""
from __future__ import annotations

import json
import uuid

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


def _switch(page, title, sid):
    from playwright.sync_api import expect

    page.get_by_role("button").filter(has=page.get_by_text(title, exact=True)).first.click()
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
    return page.locator(COMPOSER).first


def _assert_no_turns(instance, sessions, markers):
    for sid in sessions:
        detail = json.dumps(fetch_json(instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)
        assert all(marker not in detail for marker in markers if marker)


def test_immediate_typing_and_three_session_switches_preserve_separate_drafts(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    titles = [f"rapid draft {label} {suffix}" for label in "ABC"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    _ready_composer(page, e2e_instance, sessions[0])
    markers = [f"只属于会话 {label} 的未提交文字" for label in "ABC"]
    for title, sid, marker in zip(titles, sessions, markers, strict=True):
        composer = _switch(page, title, sid)
        expect(composer).to_have_value("")
        composer.click()
        composer.press_sequentially(marker, delay=1)
        # Intentionally no debounce wait before selecting the next session.
    for index in [0, 2, 1, 0, 1, 2]:
        expect(_switch(page, titles[index], sessions[index])).to_have_value(markers[index])
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[2], timeout=30000)
    expect(page.locator(COMPOSER).first).to_have_value(markers[2], timeout=15000)
    _assert_no_turns(e2e_instance, sessions, markers)


def test_hovered_session_tip_does_not_block_adjacent_session_after_keyboard_edit(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    title_a, title_b, title_c = [f"rapid draft {label} {suffix}" for label in "ABC"]
    sessions = [create_session(e2e_instance.port, title=title) for title in [title_a, title_b, title_c]]
    _ready_composer(page, e2e_instance, sessions[0])
    composer = _switch(page, title_b, sessions[1])
    # Keyboard focus may move without moving the mouse off the selected tab.
    # Keep that pointer stationary until the real tooltip has opened.
    composer.press_sequentially("键盘编辑但鼠标仍在会话标题上", delay=1)
    tip = page.locator('[data-vui="tooltip-content"]').filter(has_text=title_b).first
    expect(tip).to_be_visible(timeout=5000)
    page.get_by_role("button").filter(has=page.get_by_text(title_c, exact=True)).first.click(timeout=5000)
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[2], timeout=30000)


def test_intentional_clear_survives_immediate_reload(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="immediate clear and reload")
    marker = "用户主动删除的草稿不能重新出现"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(marker, delay=1)
    expect(composer).to_have_value(marker)
    composer.press("ControlOrMeta+A")
    composer.press("Backspace")
    expect(composer).to_have_value("")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
    expect(page.locator(COMPOSER).first).to_have_value("", timeout=15000)
    stored = page.evaluate("() => JSON.parse(localStorage.getItem('vibelution.chat.drafts.v1') || '[]')")
    assert not any(row.get("sessionId") == sid and row.get("draft") for row in stored)
    _assert_no_turns(e2e_instance, [sid], [marker])


def test_pending_send_failure_after_leaving_chat_recovers_on_browser_back(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="pending failure after leaving chat")
    marker = "离开聊天页面后仍应恢复的未发送文字"
    composer = _ready_composer(page, e2e_instance, sid)
    pending, captured = [], []
    pattern = "**/api/sessions/*/messages"

    def hold(route):
        captured.append(route.request.post_data_json)
        pending.append(route)

    page.route(pattern, hold)
    try:
        composer.fill(marker)
        page.get_by_role("button", name="发送", exact=True).click()
        page.wait_for_function("() => document.querySelector('textarea[aria-label=\"发送消息\"]').value === ''")
        for _ in range(100):
            if pending:
                break
            page.wait_for_timeout(50)
        assert len(pending) == 1
        page.get_by_role("button", name="设置", exact=True).click()
        page.get_by_role("link", name="全部设置", exact=True).click()
        expect(page.locator('[data-vui-domain-recipe="config-settings"]').first).to_be_visible(timeout=30000)
        pending.pop().abort("internetdisconnected")
        page.wait_for_function(
            "({sid, marker}) => JSON.parse(localStorage.getItem('vibelution.chat.drafts.v1') || '[]').some(row => row.sessionId === sid && row.draft === marker)",
            arg={"sid": sid, "marker": marker}, timeout=15000,
        )
        assert "/config" in page.url, "Late failure must not navigate the user back to chat"
        page.go_back(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(marker, timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        assert len(captured) == 1
        _assert_no_turns(e2e_instance, [sid], [marker])
    finally:
        for route in pending:
            route.abort("internetdisconnected")
        page.unroute(pattern, hold)


@pytest.mark.parametrize("status", [409, 503])
def test_server_rejection_with_double_click_preserves_draft_and_withdraws_optimistic_row(page, e2e_instance, status):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title=f"server rejection {status}")
    marker = f"HTTP {status} 拒绝后可继续编辑的文字"
    composer = _ready_composer(page, e2e_instance, sid)
    captured, pending = [], []
    pattern = "**/api/sessions/*/messages"

    def hold(route):
        captured.append(route.request.post_data_json)
        pending.append(route)

    page.route(pattern, hold)
    try:
        composer.fill(marker)
        page.get_by_role("button", name="发送", exact=True).dblclick()
        for _ in range(100):
            if pending:
                break
            page.wait_for_timeout(50)
        assert len(pending) == 1, "Double click must make one pending submission"
        pending.pop().fulfill(status=status, json={"detail": "Injected server rejection"})
        expect(page.locator('[role="alert"]').filter(has_text="没有发出").first).to_be_visible(timeout=15000)
        expect(composer).to_have_value(marker)
        expect(composer).to_be_enabled()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        assert len(captured) == 1
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(marker, timeout=15000)
        _assert_no_turns(e2e_instance, [sid], [marker])
    finally:
        for route in pending:
            route.abort("internetdisconnected")
        page.unroute(pattern, hold)
